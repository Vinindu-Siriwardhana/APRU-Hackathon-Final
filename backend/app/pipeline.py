"""One submission = one SHG's monthly report, from first photo to workbook + receipt.

    collecting ──(page 1 [+2] accepted)──► read twice + validate ──(reading failed)──► failed ─(retry)─┐
        │   ▲                                 ├─ errors ─► needs_review ─(officer fixes, approves)─┐   │
        │   └─────────────────────────────────┼───────────────────────────────────────────────────┼───┘
        ▼                                     └─ clean ───────────────────────────────────────────┤
   retake message                                                                   awaiting_member
                                    member "OK" ──► written ──► receipt                  │  member "5 12000"
                                         └─(workbook refused)─► needs_review (write_failed)  └──► needs_review
    any open report ──(newer report, same SHG + month)──► superseded      officer "reject" ──► rejected

Every change to a value is recorded in that field's history (who, what, when), and every
bot message in the submission log carries `text` (member's language) and `text_en`.

Concurrency: every load → change → save holds `lock` (one process-wide RLock); files are
replaced atomically. Slow work runs outside the lock: the photo quality check and JPEG
encoding (receive_image), and reading the handwriting (process(): Claude mode makes several
API calls). process() re-loads the submission under the lock to store the result, and drops
the result if the report was rejected or withdrawn (STOP) while it was being read.

Delivery: every bot message has an id (`mid`) shared by the submission log and the
conversation log, and `delivered` (None = simulator / not attempted yet, True, False with
`delivery_error`). The API records each WhatsApp send through record_delivery().
"""
from __future__ import annotations

import logging
import math
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
from pydantic import BaseModel, Field

from . import messages as M
from .aggregate import last_active_week, to_monthly
from .conversations import Conversation, Conversations, new_mid
from .extraction import ExtractionError, Reader, extract
from .imaging.io import read_image, write_image
from .imaging.layout import Alignment, FormLocator, save_crop
from .imaging.quality import check
from .labels import short_label
from .locking import atomic_write_bytes, atomic_write_text, lock
from .messages import Reply
from .models import Category, FieldStatus, FieldValue, FormRecord, Issue, Legibility, PriorMonth, Severity, normalise
from .schema import WEEKS, Template, load_template
from .validation import (OPENING_LABELS, ValidationResult, Validator, add_months, opening_suggestion,
                         prior_from_opening)
from .workbook import FIRST_COL, LAST_COL, GNWorkbook, WorkbookError, WriteReport


log = logging.getLogger("shg.pipeline")

__all__ = ["lock", "Status", "Submission", "Store", "Pipeline", "StateError", "NotFound"]

ID_RE = re.compile(r"^[0-9a-f]{10}$")
MAX_MONEY = 1e8
MAX_COUNT = 100_000
MAX_TEXT = 500


class Status(str, Enum):
    collecting = "collecting"
    needs_review = "needs_review"
    awaiting_member = "awaiting_member"
    written = "written"
    failed = "failed"              # the photos couldn't be read; the officer can try again
    superseded = "superseded"      # a newer report for the same SHG + month replaced it; never written
    rejected = "rejected"          # the officer asked for a retake / discarded it (or the member opted out)


OPEN = (Status.collecting, Status.needs_review, Status.awaiting_member)
EDITABLE = (Status.needs_review, Status.awaiting_member)

# Why an action isn't possible, per status, in words an officer understands.
WHY_NOT = {
    Status.collecting: "this report is still being collected, and no page has been read yet.",
    Status.needs_review: "this report is waiting for an officer's review.",
    Status.awaiting_member: "this report was sent to the member and is waiting for her reply.",
    Status.written: "this report is already in the workbook, so it can't be changed here.",
    Status.failed: "the photos could not be read. Use Try again, or ask the member for a new photo.",
    Status.superseded: "a newer report for this group and month replaced this one.",
    Status.rejected: "this report was rejected.",
}

# Never turned into a warning by "checked against the photo, kept as written": Palmera's hard
# limits, and checks that are about the workbook rather than the handwriting.
NEVER_DOWNGRADE = {"above_max", "attendance_above_capacity", "month_out_of_range", "unknown_shg",
                   "opening_inconsistent"}

# "Send anyway" can't skip these: each needs its own decision first (a write would fail or
# land in the wrong place). month_already_recorded is skipped only by a confirmed correction.
NOT_FORCEABLE = {
    "unknown_shg": "this group has no tab in the workbook. Fix the group name, or use “It's a new group” first.",
    "opening_inconsistent": "the new group's opening totals don't match the form. Enter its totals from the "
                            "mother book first.",
    "month_out_of_range": "the month is outside this group's columns in the workbook. Check the month on the photo.",
    "month_unexpected": "the month on the form is not the one expected. Check it on the photo and confirm it "
                        "as written if it is right.",
    "month_already_recorded": "this month is already in the workbook. To replace it, confirm it as a correction "
                              "of the recorded month, with a reason.",
}
UNKNOWN_SAMPLE_KINDS = ("unknown_sample", "mixed_samples")


class StateError(Exception):
    """The action isn't allowed in the submission's current status (HTTP 409)."""


class NotFound(KeyError):
    """No such submission / field / pending correction (HTTP 404)."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else "not found"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Submission(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    sender: str = ""
    lang: str = "en"
    created: str = Field(default_factory=now)
    updated: Optional[str] = None
    status: Status = Status.collecting
    pages: dict[int, str] = Field(default_factory=dict)                  # page -> image file
    page_sources: dict[int, Optional[str]] = Field(default_factory=dict)  # page -> sample photo it is (simulator)
    record: Optional[FormRecord] = None
    validation: Optional[ValidationResult] = None
    prior: Optional[PriorMonth] = None
    prior_error: Optional[str] = None                                    # why last month couldn't be read
    shg_tab: Optional[str] = None
    shg_candidates: list[str] = Field(default_factory=list)              # close tab names when not found
    new_group: bool = False                                              # officer confirmed: a new SHG
    overrides: dict[str, Any] = Field(default_factory=dict)              # member corrections awaiting an officer
    summary_sent: bool = False
    member_confirmed: bool = False
    forced: Optional[dict[str, Any]] = None                              # {by, reason, at} of a forced approval
    overwrite: Optional[dict[str, Any]] = None                           # officer confirmed a correction of a recorded month
    write_error: Optional[str] = None
    write_report: Optional[WriteReport] = None
    failure: Optional[str] = None                                        # why reading failed (status failed)
    failure_kind: Optional[str] = None                                   # unknown_sample | mixed_samples | reading | error
    opening: Optional[dict[str, float]] = None                           # new group: the nine totals BEFORE this month
    started_this_month: Optional[bool] = None                            # new group: officer says it started this month
    month_error: Optional[str] = None                                    # the month is outside the tab (month_out_of_range)
    superseded_by: Optional[str] = None
    rejected_reason: Optional[str] = None
    log: list[dict[str, Any]] = Field(default_factory=list)              # chat transcript + events

    def say(self, reply: str) -> Reply:
        """Log a bot message to the member and return it carrying its id (`mid`)."""
        mid = new_mid()
        entry: dict[str, Any] = {"at": now(), "from": "bot", "text": str(reply), "mid": mid,
                                 "delivered": None, "delivery_error": None}
        en = getattr(reply, "en", None)
        if en:
            entry["text_en"] = en
        self.log.append(entry)
        return Reply(str(reply), en, mid)

    def bot_entry(self, mid: Optional[str]) -> Optional[dict[str, Any]]:
        return next((e for e in reversed(self.log) if mid and e.get("from") == "bot" and e.get("mid") == mid), None)

    def undelivered(self) -> list[dict[str, Any]]:
        """Bot messages a WhatsApp send failed for (oldest first)."""
        return [e for e in self.log if e.get("from") == "bot" and e.get("delivered") is False]

    def event(self, kind: str, /, **kw: Any) -> None:
        self.log.append({"at": now(), "event": kind, **kw})


class Store:
    """Submissions as JSON files on disk: simple, inspectable, fine for a pilot."""

    def __init__(self, root: Path):
        self.root = Path(root)
        (self.root / "submissions").mkdir(parents=True, exist_ok=True)

    @staticmethod
    def valid_id(sid: str) -> bool:
        return bool(isinstance(sid, str) and ID_RE.fullmatch(sid))

    def dir(self, sid: str) -> Path:
        """The submission's folder. Never creates it (a GET must not make folders) and
        never accepts anything but a 10-hex-digit id (no path tricks)."""
        if not self.valid_id(sid):
            raise NotFound("no such submission")
        return self.root / "submissions" / sid

    def ensure_dir(self, sid: str) -> Path:
        d = self.dir(sid)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, sub: Submission) -> None:
        with lock:
            sub.updated = now()
            atomic_write_text(self.ensure_dir(sub.id) / "submission.json", sub.model_dump_json(indent=1))

    def load(self, sid: str) -> Submission:
        p = self.dir(sid) / "submission.json"
        try:
            return Submission.model_validate_json(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise NotFound("no such submission") from None

    def all(self) -> list[Submission]:
        """Every readable submission, newest first. An unreadable file is skipped and
        logged, so one bad file can't take down the inbox or the member chat."""
        out = []
        for p in sorted((self.root / "submissions").glob("*/submission.json")):
            try:
                out.append(Submission.model_validate_json(p.read_text(encoding="utf-8")))
            except (OSError, ValueError) as e:
                log.warning("skipping unreadable submission %s: %s", p.parent.name, e)
        return sorted(out, key=lambda s: s.created, reverse=True)

    def for_sender(self, sender: str) -> list[Submission]:
        return [s for s in self.all() if s.sender == sender]

    def awaiting_for(self, sender: str) -> Optional[Submission]:
        """Her newest report whose summary is waiting for her OK (where OK / "5 12000" go)."""
        return next((s for s in self.for_sender(sender) if s.status == Status.awaiting_member), None)

    def open_for(self, sender: str) -> Optional[Submission]:
        """The member's newest open report (where her next text goes); see Pipeline._route_text."""
        for s in self.for_sender(sender):
            if s.status in (Status.needs_review, Status.awaiting_member, Status.failed) or \
                    (s.status == Status.collecting and s.pages):
                return s
        return None


class Pipeline:
    def __init__(self, store: Store, workbook_path: Path, reader: Reader, template: Template | None = None,
                 conversations: Conversations | None = None):
        self.store = store
        self.t = template or load_template()
        self.loc = FormLocator(self.t)
        self.validator = Validator(self.t)
        self.workbook_path = Path(workbook_path)
        self.reader = reader
        self.conversations = conversations or Conversations(store.root)
        self._busy: set[str] = set()                  # submissions being read right now
        self._monthly_rows = {r["label"]: r for r in self.t.workbook["monthly_rows"]}

    # ================================================================ member front door
    # Both the WhatsApp webhook and the simulator come in here, so the member gets the
    # same answers on both, and every message lands in her conversation log.
    def on_image(self, sender: str, img: np.ndarray, *, lang: Optional[str] = None,
                 image_name: Optional[str] = None, source: Optional[str] = None
                 ) -> tuple[Optional[Submission], Optional[Reply]]:
        """The reply is None only when the report was rejected or withdrawn (STOP) while it
        was being read: she has already been told, so nothing more is sent."""
        at = now()
        with lock:
            conv = self.conversations.load(sender)
            self._apply_lang(conv, lang)
            if conv.opted_out:                         # sending a photo again opts her back in
                conv.opted_out = False
                conv.event("opted_in")
            self._sync_lang(sender, conv.lang)
            self.conversations.save(conv)
        sub: Optional[Submission] = None
        try:
            sub, reply = self.receive_image(sender, img, conv.lang, source=source)
        except Exception:                              # never leave the member without an answer
            log.exception("photo from %s failed", _mask(sender))
            reply = M.msg("error_fallback", conv.lang)
        with lock:
            conv = self.conversations.load(sender)
            conv.add_member(is_image=True, image=image_name, sid=sub.id if sub else None, at=at)
            if reply is not None:
                reply = self._with_privacy(conv, reply)
                reply.mid = conv.add_bot(reply, sub.id if sub else None)
            self.conversations.save(conv)
        return sub, reply

    def on_text(self, sender: str, text: str, *, lang: Optional[str] = None) -> tuple[Optional[Submission], Reply]:
        at = now()
        text = (text or "").strip()[:2000]
        sub: Optional[Submission] = None
        with lock:
            conv = self.conversations.load(sender)
            self._apply_lang(conv, lang)
            try:
                if M.is_stop(text):
                    reply = self._stop(conv)
                elif M.language_keyword(text):
                    conv.lang, conv.lang_chosen = M.language_keyword(text), True
                    self._sync_lang(sender, conv.lang)
                    reply = M.msg("lang_set", conv.lang)
                else:
                    if not conv.lang_chosen and M.script_lang(text):
                        conv.lang, conv.lang_chosen = M.script_lang(text), True
                    if conv.opted_out:
                        conv.opted_out = False
                        conv.event("opted_in")
                    self._sync_lang(sender, conv.lang)
                    sub, reply = self.member_reply(sender, text, lang=conv.lang)
                    if sub is None and not conv.lang_chosen:
                        reply = reply.then(M.msg("choose_language", "en"))
            except Exception:
                log.exception("text from %s failed", _mask(sender))
                reply = M.msg("error_fallback", conv.lang)
            if not conv.opted_out:
                reply = self._with_privacy(conv, reply)
            conv.add_member(text=text, sid=sub.id if sub else None, at=at)
            reply.mid = conv.add_bot(reply, sub.id if sub else None)
            self.conversations.save(conv)
        return sub, reply

    def on_other(self, sender: str, kind: str, reply_key: str = "unsupported") -> tuple[None, Reply]:
        """A voice note, sticker, file, an undecodable photo…: say what we can read."""
        with lock:
            conv = self.conversations.load(sender)
            reply = self._with_privacy(conv, M.msg(reply_key, conv.lang))
            conv.add_member(text=f"[{kind}]")
            reply.mid = conv.add_bot(reply)
            self.conversations.save(conv)
        return None, reply

    def _apply_lang(self, conv: Conversation, lang: Optional[str]) -> None:
        if lang in M.LANGS:
            conv.lang, conv.lang_chosen = lang, True

    def _sync_lang(self, sender: str, lang: str) -> None:
        """Her open reports answer in the language she uses now."""
        for s in self.store.for_sender(sender):
            if s.status in OPEN + (Status.failed,) and s.lang != lang:
                s.lang = lang
                self.store.save(s)

    def _with_privacy(self, conv: Conversation, reply: Reply) -> Reply:
        """The privacy note goes once per sender, under the first reply she gets."""
        if conv.privacy_sent:
            return reply
        conv.privacy_sent = True
        conv.event("privacy_note_sent")
        return reply.then(M.msg("privacy", conv.lang))

    def _stop(self, conv: Conversation) -> Reply:
        """STOP: stop using her photos. Her open reports are withdrawn (never written)."""
        conv.opted_out, conv.privacy_sent = True, False
        conv.event("opted_out")
        for s in self.store.for_sender(conv.sender):
            if s.status in OPEN + (Status.failed,):
                s.status, s.rejected_reason = Status.rejected, "member_opted_out"
                s.event("opted_out", note="The member replied STOP; this report will not be used.")
                self.store.save(s)
        return M.msg("stopped", conv.lang)

    # ================================================================ photos
    def receive_image(self, sender: str, img: np.ndarray, lang: Optional[str] = None,
                      source: Optional[str] = None) -> tuple[Submission, Reply]:
        """A photo from a member. `lang` is used when this starts a new report (default: the
        language she used last); `source` is the sample photo it is (simulator), which the
        offline demo reader needs.

        The quality check and the JPEG encoding take seconds, so they run OUTSIDE the lock
        (the dashboard keeps answering); the lock is held only to attach the page."""
        with lock:
            cur = self._collecting_for(sender)
            if cur is not None and cur.id in self._busy:   # she re-sent a page while we read the report
                return cur, M.msg("reading", cur.lang)
        q = check(img, self.loc)
        jpeg = _jpeg(img) if q.ok else None
        with lock:
            sub = self._collecting_for(sender) or Submission(sender=sender, lang=lang or self.lang_of(sender))
            if sub.id in self._busy:                   # reading started while we checked this photo
                return sub, M.msg("reading", sub.lang)
            sub.log.append({"at": now(), "from": "member", "image": True})
            if not q.ok:
                reply = sub.say(Reply(q.message(sub.lang), q.message("en") if sub.lang != "en" else None))
                sub.event("quality_rejected", problem=q.problem, metrics=_jsonable(q.metrics))
                self.store.save(sub)
                return sub, reply
            path = self.store.ensure_dir(sub.id) / f"page{q.page}.jpg"
            atomic_write_bytes(path, jpeg)
            sub.pages[q.page] = path.name
            sub.page_sources[q.page] = source
            sub.event("page_accepted", page=q.page, metrics=_jsonable(q.metrics), sample=source)
            if 1 not in sub.pages:
                reply = sub.say(M.msg("ask_page1", sub.lang))
            elif 2 not in sub.pages:
                reply = sub.say(M.msg("ask_page2", sub.lang))
            else:
                reply = None
            self.store.save(sub)
            if reply is not None:
                return sub, reply
        reply = self.process(sub.id)
        return self._load_quiet(sub.id) or sub, reply

    def finish_without_page2(self, sub: Submission) -> Optional[Reply]:
        """Officer (or a timeout) can process page 1 alone; page-2 answers stay empty."""
        return self.process_now(sub.id, officer="system")

    def lang_of(self, sender: str) -> str:
        """The member's language: her choice in the chat, else her last report's, else English."""
        conv = self.conversations.load(sender)
        if conv.lang_chosen:
            return conv.lang
        mine = self.store.for_sender(sender)
        return mine[0].lang if mine else conv.lang

    def _collecting_for(self, sender: str) -> Optional[Submission]:
        return next((s for s in self.store.for_sender(sender) if s.status == Status.collecting), None)

    # ================================================================ extraction + checks
    def process(self, sid: str, quiet_failure: bool = False) -> Optional[Reply]:
        """Read both pages twice, then validate. The reading runs outside the lock."""
        with lock:
            sub = self.store.load(sid)
            if sid in self._busy:
                return M.msg("reading", sub.lang)
            if sub.status != Status.collecting or 1 not in sub.pages:
                raise StateError(WHY_NOT.get(sub.status, "This report can't be read now."))
            self._busy.add(sid)
        try:
            rec, error, key, kind = self._read(sub), None, None, None
        except Exception as e:
            rec, error, key = None, _reading_failure(e), getattr(e, "member_key", "extraction_failed")
            kind = getattr(e, "kind", None) or ("reading" if isinstance(e, ExtractionError) else "error")
            if not isinstance(e, (ExtractionError,)) and key == "extraction_failed":
                log.exception("reading submission %s failed", sid)
        finally:
            with lock:
                self._busy.discard(sid)
        with lock:
            try:
                sub = self.store.load(sid)
            except NotFound:                           # deleted meanwhile (demo reset)
                return None
            if sub.status != Status.collecting:        # rejected, or she said STOP, while we read
                sub.event("reading_discarded", status=sub.status.value)
                self.store.save(sub)
                return None
            if error is not None:
                sub.status, sub.failure, sub.failure_kind = Status.failed, error, kind
                sub.event("extraction_failed", reason=error)
                reply = None if quiet_failure else sub.say(M.msg(key, sub.lang))
                self.store.save(sub)
                return reply
            sub.record, sub.failure, sub.failure_kind = rec, None, None
            self._lookup_prior(sub)
            self.revalidate(sub)
            self._supersede_older(sub)
            if sub.validation.auto_accept:
                reply = self._send_summary(sub)
            else:
                sub.status = Status.needs_review
                reply = sub.say(M.msg("checking", sub.lang))
            self.store.save(sub)
            return reply

    def _read(self, sub: Submission) -> FormRecord:
        reader_for = getattr(self.reader, "for_submission", None)
        reader = reader_for(sub) if reader_for else self.reader
        als = self._alignments(sub)
        if 1 not in als:
            raise ExtractionError("The form could not be found on the page 1 photo.")
        rec = extract(self.t, self.loc, als, reader)
        self._save_crops(sub.id, rec, als)
        return rec

    def _alignments(self, sub: Submission) -> dict[int, Alignment]:
        out = {}
        for page, name in sub.pages.items():
            img = read_image(self.store.dir(sub.id) / name)
            al = self.loc.align(img) if img is not None else None
            if al is not None:
                out[int(page)] = al
        return out

    def _save_crops(self, sid: str, rec: FormRecord, als: dict[int, Alignment]) -> None:
        d = self.store.dir(sid) / "crops"
        try:
            d.mkdir(exist_ok=True)                 # never re-creates a folder a demo reset removed
        except FileNotFoundError:
            return
        for fid in rec.fields:
            page = 1 if fid.startswith(("header.", "weekly.")) else 2
            if page in als:
                crop = self.loc.crop(als[page], fid)
                if crop is not None and crop.size:
                    save_crop(crop, d / f"{fid}.jpg")

    def _lookup_prior(self, sub: Submission) -> None:
        """Find the SHG's tab and last month's balances. Run again whenever the officer
        changes the SHG name or the month. A new group's 'last month' is its opening totals."""
        sub.prior, sub.prior_error, sub.shg_tab, sub.shg_candidates = None, None, None, []
        sub.month_error = None
        name = sub.record.get("header.shg_name") if sub.record else None
        month = sub.record.get("header.month_year") if sub.record else None
        if not name:
            return
        try:
            with lock:
                wb = GNWorkbook(self.workbook_path, self.t)
            tab, candidates = wb.find_shg(str(name))
            sub.shg_tab, sub.shg_candidates = tab, list(candidates or [])
            if tab is None:
                if not any(e.get("event") == "shg_not_found" and e.get("name") == name for e in sub.log):
                    sub.event("shg_not_found", name=name, candidates=sub.shg_candidates)
                if sub.new_group and sub.opening is not None and month:
                    sub.prior = prior_from_opening(sub.record, sub.opening, bool(sub.started_this_month))
                return
            if not month:
                return
            ws = wb.wb[tab]
            start = wb.start_month(ws)
            try:
                wb.month_col(ws, str(month))
            except WorkbookError:
                end = add_months(start, LAST_COL - FIRST_COL)
                sub.month_error = (f"The form says {M.month_name(month, 'en')}, but the {tab} tab in the workbook "
                                   f"only has columns for {M.month_name(start, 'en')} to {M.month_name(end, 'en')}. "
                                   "Check the month on the photo. If it is right, this group needs a new sheet "
                                   "in the workbook: ask the person who manages it.")
                return
            prior = wb.prior_month(tab, str(month)) or PriorMonth()
            prior.this_month_recorded = bool(wb.month_recorded(tab, str(month)))
            sub.prior = prior
        except Exception as e:                         # WorkbookError, a bad month, a damaged file…
            sub.prior_error = _describe(e)
            sub.event("prior_lookup_failed", error=sub.prior_error)

    def revalidate(self, sub: Submission) -> None:
        mismatch = self._opening_mismatch(sub)
        prior = None if mismatch else sub.prior        # wrong opening totals: no week-1 checks from them
        res = self.validator.validate(sub.record, prior)
        self._member_correction_issues(sub, res)
        name = sub.record.get("header.shg_name")
        if name and sub.shg_tab is None and not any(i.rule == "unknown_shg" for i in res.issues):
            did_you_mean = f" Did you mean {', '.join(sub.shg_candidates)}?" if sub.shg_candidates else ""
            if sub.new_group and sub.opening is not None:
                how = ("it started this month, so its opening totals are all zero" if sub.started_this_month
                       else "its opening totals come from the mother book")
                res.add(Issue(rule="unknown_shg", severity=Severity.warning, category=Category.continuity,
                              message=f"“{name}” is a new group (confirmed by an officer; {how}). A new tab "
                                      "will be created in the GN workbook when this report is written.",
                              fields=["header.shg_name"]))
            else:
                res.add(Issue(rule="unknown_shg", severity=Severity.error, category=Category.continuity,
                              message=f"No tab for SHG “{name}” in the GN workbook.{did_you_mean} "
                                      "Fix the name, or confirm this is a new group.",
                              fields=["header.shg_name"], expected=sub.shg_candidates or None, found=name))
        if mismatch:
            res.add(mismatch)
        if sub.month_error:
            res.add(Issue(rule="month_out_of_range", severity=Severity.error, category=Category.continuity,
                          message=sub.month_error, fields=["header.month_year"],
                          found=sub.record.get("header.month_year")))
        if sub.prior_error:
            res.add(Issue(rule="prior_lookup_failed", severity=Severity.warning, category=Category.continuity,
                          message=f"Couldn't read last month from the workbook ({sub.prior_error}); "
                                  "the opening-balance checks were skipped.", fields=[]))
        if sub.write_error:
            res.add(Issue(rule="write_failed", severity=Severity.error, category=Category.continuity,
                          message=sub.write_error, fields=[]))
        # Once an officer has checked every cell of a failing ARITHMETIC/reading check against
        # the photo, the paper itself doesn't add up (the member's own arithmetic). Record it
        # as written and keep it visible, but stop it blocking the report. Never for a
        # member's correction, the workbook, a missing value or a duplicate month.
        checked = (FieldStatus.officer_confirmed, FieldStatus.officer_corrected)
        for issue in res.issues:
            if issue.severity != Severity.error or issue.rule in PIPELINE_RULES | NEVER_DOWNGRADE:
                continue
            if issue.category not in (Category.arithmetic, Category.capture, Category.range):
                continue
            fids = [f for f in issue.fields if f in sub.record.fields]
            if fids and len(fids) == len(issue.fields) and all(sub.record.fields[f].status in checked for f in fids):
                issue.severity = Severity.warning
                issue.category = Category.finding
                issue.message = "Checked against the photo, kept as written: " + issue.message
        self.validator.finish(sub.record, res, prior)   # rebuilds `flagged` and the `likely` ranking
        sub.validation = res
        # field status follows the checks: flagged -> needs_review, no longer flagged -> auto
        for fid, fv in sub.record.fields.items():
            if fid in res.flagged and fv.status == FieldStatus.auto:
                fv.status = FieldStatus.needs_review
            elif fid not in res.flagged and fv.status == FieldStatus.needs_review:
                fv.status = FieldStatus.auto

    def _opening_mismatch(self, sub: Submission) -> Optional[Issue]:
        """A new group's opening totals (from the mother book) against what the form itself
        says they were: savings to date and loans outstanding before the month. (For a group
        that 'started this month' validation raises opening_inconsistent itself.)"""
        if not (sub.record and sub.new_group and sub.opening and not sub.started_this_month
                and sub.shg_tab is None):
            return None
        form = opening_suggestion(sub.record, self.t)
        month = M.month_name(sub.record.get("header.month_year"), "en")
        parts, cells = [], []
        for label, what, row in (("Total savings to date (Rs.)", "total savings to date", "savings_to_date"),
                                 ("Total Loans outstanding to date (Rs.)", "total loans outstanding", "loans_outstanding")):
            want, given = form.get(label), sub.opening.get(label)
            if want is None or given is None or abs(float(want) - float(given)) <= self.validator.tol:
                continue
            parts.append(f"the form's own figures put {what} at Rs {M.number(want)} before {month}, "
                         f"but Rs {M.number(given)} was entered")
            cells += [f"weekly.{row}.{wk}" for wk in WEEKS if sub.record.get(f"weekly.{row}.{wk}") is not None][:1]
        if not parts:
            return None
        return Issue(rule="opening_inconsistent", severity=Severity.error, category=Category.continuity,
                     message="The opening totals don't match the form: " + "; and ".join(parts)
                             + ". Check the mother book, then enter the totals again.",
                     fields=["header.shg_name"] + cells)

    # ---------------------------------------------------------------- member corrections
    def summary_value(self, rec: FormRecord, key: str) -> Any:
        if key.startswith("header."):
            return rec.get(key)
        return to_monthly(rec, self.t, include_optional=False).get(key)

    def correction_cells(self, rec: FormRecord, key: str) -> list[str]:
        """The cells a summary figure is made from (what the officer checks)."""
        if key.startswith("header."):
            return [key]
        row = self._monthly_rows.get(key)
        if row is None:
            return []
        field, rule = row["field"], row["from"]
        if rule == "header":
            return [f"page2.{field}" if field == "members_with_goals" else f"header.{field}"]
        if rule == "total":
            return [f"weekly.{field}.Total"]
        if rule == "last_week":
            cell = self.single_cell(rec, key)
            return [cell] if cell else [f"weekly.{field}.{wk}" for wk in WEEKS]
        cols = self.t.weekly_row(field).columns
        return [f"weekly.{field}.{c}" for c in cols if c in WEEKS] + \
            ([f"weekly.{field}.Total"] if rule == "sum" and "Total" in cols else [])

    def single_cell(self, rec: FormRecord, key: str) -> Optional[str]:
        """The one cell a summary figure comes from, if it comes from exactly one (header,
        Total or month-end rows). A member's figure can only be used directly for these;
        a sum of weekly cells must be fixed in the weekly cells."""
        if key.startswith("header."):
            return key
        row = self._monthly_rows.get(key)
        if row is None:
            return None
        if row["from"] in ("header", "total"):
            return self.correction_cells(rec, key)[0]
        if row["from"] == "last_week":
            wk = last_active_week(rec, self.t)
            return f"weekly.{row['field']}.{wk}" if wk else None
        return None

    def corrections(self, sub: Submission) -> list[dict[str, Any]]:
        """Pending member corrections, for the dashboard."""
        if not sub.record:
            return []
        items = {key: (i, short) for i, (key, short) in enumerate(M.SUMMARY_ITEMS, 1)}
        out = []
        for key, v in sub.overrides.items():
            n, short = items.get(key, (None, key))
            cell = self.single_cell(sub.record, key)
            out.append({"label": key, "item": n, "short": short, "value": v,
                        "form_value": self.summary_value(sub.record, key),
                        "cells": self.correction_cells(sub.record, key), "cell": cell, "can_accept": cell is not None})
        return out

    def _member_correction_issues(self, sub: Submission, res: ValidationResult) -> None:
        """A pending member correction blocks until the cells agree with her figure (then it
        resolves itself) or an officer decides on it."""
        items = {key: short for key, short in M.SUMMARY_ITEMS}
        for key, v in list(sub.overrides.items()):
            found = self.summary_value(sub.record, key)
            if self._same(found, v, key):
                sub.overrides.pop(key)
                sub.event("member_correction_resolved", label=key, value=v)
                continue
            cell = self.single_cell(sub.record, key)
            what = items.get(key, key)
            how = ("fix that cell, use her figure, or keep the form's figure" if cell else
                   "fix the weekly cells until they add up to her figure, or keep the form's figure")
            kw: dict[str, Any] = {}
            if cell and isinstance(v, (int, float)) and not isinstance(v, bool):
                kw["suggest"] = {cell: v}
            res.add(Issue(rule="member_correction", severity=Severity.error, category=Category.capture,
                          message=f"The member says {what} should be {_show(key, v)}; the form gives "
                                  f"{_show(key, found)}. Check the photo, then {how}.",
                          fields=self.correction_cells(sub.record, key), expected=v, found=found, label=key, **kw))

    def _same(self, a: Any, b: Any, key: Optional[str] = None) -> bool:
        """Equal as she'd see it: amounts within the rounding tolerance, counts exactly
        (19 members is not 18)."""
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
            tol = float(self.t.validation.get("money_tolerance", 1)) if key is None or M.is_money_item(key) else 0
            return abs(a - b) <= tol
        if isinstance(a, str) and isinstance(b, str):
            return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()
        return a == b

    # ---------------------------------------------------------------- superseding
    def _supersede_older(self, sub: Submission) -> None:
        """A newer report for the same SHG + month replaces older open ones (any sender)."""
        key = self._report_key(sub)
        if key is None:
            return
        replaced = []
        for s in self.store.all():
            if s.id == sub.id or s.status not in OPEN or s.created > sub.created:
                continue
            if self._report_key(s) == key:
                s.status, s.superseded_by = Status.superseded, sub.id
                s.event("superseded", by=sub.id)
                self.store.save(s)
                replaced.append(s.id)
        if replaced:
            sub.event("supersedes", ids=replaced)

    @staticmethod
    def _report_key(s: Submission) -> Optional[tuple[str, str]]:
        if not s.record:
            return None
        name, month = s.record.get("header.shg_name"), s.record.get("header.month_year")
        if not name or not month:
            return None
        return (s.shg_tab or " ".join(str(name).split())).casefold(), str(month)

    # ================================================================ officer
    def _require(self, sub: Submission, allowed: tuple[Status, ...], action: str) -> None:
        if sub.status not in allowed:
            raise StateError(f"Can't {action}: {WHY_NOT.get(sub.status, sub.status.value)}")
        if sub.record is None and sub.status != Status.collecting:
            raise StateError(f"Can't {action}: this report hasn't been read yet.")

    def _reopen(self, sub: Submission, officer: str, why: str) -> None:
        """An officer changed something: the member must confirm the new figures."""
        sub.member_confirmed = False
        sub.write_error = None
        if sub.status == Status.awaiting_member:
            sub.status = Status.needs_review
            sub.event("reopened", by=officer, why=why)

    def officer_set(self, sub: Submission, field_id: str, raw: Any, officer: str) -> None:
        """Officer confirms or corrects one value after looking at its crop."""
        with lock:
            self._require(sub, EDITABLE, "edit a value")
            if field_id not in sub.record.fields:
                if field_id not in set(self.t.all_field_ids()):
                    raise NotFound(f"There is no cell called “{field_id}” on this form.")
                sub.record.fields[field_id] = FieldValue()   # a cell the reader left out
            value = self.check_value(field_id, raw)
            fv = sub.record.fields[field_id]
            fv.history = [h for h in fv.history if h.get("event") != "capture_check"]
            fv.history.append({"at": now(), "event": "officer", "by": officer, "old": fv.value, "new": value,
                               "readings": list(fv.passes)})      # keep what each reading said (audit)
            changed = value != fv.value
            fv.status = FieldStatus.officer_corrected if changed else FieldStatus.officer_confirmed
            fv.value, fv.passes = value, [value]
            fv.legibility = Legibility.clear if value is not None else Legibility.blank
            if changed:
                self._reopen(sub, officer, f"{short_label(self.t, field_id)} changed")
                if field_id == "header.shg_name":
                    self._forget_new_group(sub)
            sub.write_error = None
            if field_id in ("header.shg_name", "header.month_year"):
                self._lookup_prior(sub)
            self.revalidate(sub)
            self.store.save(sub)

    def check_value(self, field_id: str, raw: Any) -> Any:
        """Normalise an officer's value, refusing anything that can't be a real cell value.
        Every refusal is a ValueError with a sentence the dashboard can show as it is."""
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        ftype = self.t.field_type(field_id)
        if isinstance(raw, (list, dict)):
            raise ValueError("Enter a single value.")
        if isinstance(raw, str) and len(raw) > MAX_TEXT:
            raise ValueError(f"Keep it under {MAX_TEXT} characters.")
        if isinstance(raw, int) and not isinstance(raw, bool) and abs(raw) > 10 ** 12:
            raw = float("inf")                        # a 400-digit number: refused below, never a 500
        shown = _quoted(raw)
        try:
            if ftype in ("money", "int"):
                if isinstance(raw, bool):
                    raise ValueError("Enter a number.")
                if isinstance(raw, float) and not math.isfinite(raw):
                    raise ValueError("That number is too large. Enter the amount as it is written on the form.")
                try:
                    v = normalise(raw, ftype)
                except ValueError:
                    raise ValueError(f"{shown} isn't a number. Enter it in digits, like 1200.") from None
                if v is None:
                    return None
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    raise ValueError(f"{shown} isn't a number. Enter it in digits, like 1200.")
                if ftype == "int":
                    if float(v) != int(v):
                        raise ValueError("Enter a whole number.")
                    v = int(v)
                    if not 0 <= v <= MAX_COUNT:
                        raise ValueError(f"Enter a number between 0 and {MAX_COUNT:,}.")
                elif not 0 <= v <= MAX_MONEY:
                    raise ValueError(f"Amounts must be between 0 and {MAX_MONEY:,.0f}.")
                return v
            if isinstance(raw, float) and not math.isfinite(raw):
                raise ValueError("Enter a real value.")
            if ftype == "yesno":
                try:
                    return normalise(raw, ftype)
                except ValueError:
                    raise ValueError("Choose Yes or No.") from None
            if ftype == "month":
                bad = ValueError(f"{shown} isn't a month between 2000 and 2100. Enter it like 10/2026.")
                try:
                    v = normalise(raw, ftype)
                except ValueError:
                    raise bad from None
                year = re.search(r"\d{4}", str(raw))         # '0001-01' must not become January 2001
                if v is not None and year and year[0] != v[:4]:
                    raise bad
                return v
            v = normalise(raw, ftype)
            if isinstance(v, str) and len(v) > MAX_TEXT:
                raise ValueError(f"Keep it under {MAX_TEXT} characters.")
            return v
        except OverflowError:
            raise ValueError("That number is too large. Enter the amount as it is written on the form.") from None

    def officer_override(self, sub: Submission, label: str, accept: bool, officer: str) -> None:
        """Decide on a member's correction. accept=False keeps the form's figure.
        accept=True is only possible when the figure comes from ONE cell: it sets that cell
        (status member_corrected) and everything is checked again. A figure that is a sum
        of weekly cells must be fixed in those cells; the correction then resolves itself."""
        with lock:
            self._require(sub, EDITABLE, "decide on the member's correction")
            if label not in sub.overrides:
                raise NotFound(f"There is no member correction waiting for “{label}”. It may already have been decided.")
            v = sub.overrides[label]
            if accept:
                cell = self.single_cell(sub.record, label)
                if cell is None:
                    raise StateError("Can't use her figure directly: this figure adds up several weekly cells. "
                                     "Fix the weekly cells (the check clears itself when they match), "
                                     "or keep the form's figure.")
                fv = sub.record.fields.get(cell) or FieldValue()
                fv.history.append({"at": now(), "event": "member_correction", "by": officer,
                                   "old": fv.value, "new": v})
                fv.value, fv.passes, fv.status = v, [v], FieldStatus.member_corrected
                fv.legibility = Legibility.clear
                sub.record.fields[cell] = fv
                sub.overrides.pop(label)
                sub.event("override_accepted", label=label, value=v, cell=cell, by=officer)
                self._reopen(sub, officer, "member's figure used")
                if cell in ("header.shg_name", "header.month_year"):
                    if cell == "header.shg_name":
                        self._forget_new_group(sub)
                    self._lookup_prior(sub)
            else:
                sub.overrides.pop(label)
                sub.event("override_dismissed", label=label, value=v, by=officer)
            self.revalidate(sub)
            self.store.save(sub)

    def officer_approve(self, sub: Submission, officer: str, force: bool = False, reason: str = "",
                        overwrite: bool = False) -> Optional[Reply]:
        """Send the summary to the member (or, if she already confirmed it, write it).
        force=True approves despite failing checks; overwrite=True replaces a month already
        in the workbook. Both need a reason, which is logged."""
        with lock:
            self._require(sub, (Status.needs_review,), "approve")
            reason = (reason or "").strip()[:MAX_TEXT]
            if (force or overwrite) and not reason:
                raise ValueError("Give a reason for approving despite failing checks or replacing a recorded month.")
            self.revalidate(sub)
            ignore = {"write_failed"} | ({"month_already_recorded"} if overwrite else set())
            blocking = [i for i in sub.validation.errors if i.rule not in ignore]
            if blocking and not force:
                n = len(blocking)
                raise StateError(f"Can't send it yet: {n} check{'s are' if n != 1 else ' is'} still failing. "
                                 "Fix them, or use Send anyway with a reason.")
            stuck = _not_forceable(blocking)
            if stuck:
                raise StateError(f"Can't send anyway: {NOT_FORCEABLE[stuck]}")
            sub.forced = {"by": officer, "reason": reason, "at": now()} if force else None
            sub.overwrite = {"by": officer, "reason": reason, "at": now()} if overwrite else None
            sub.write_error = None
            if force:
                for label in list(sub.overrides):          # the officer decided; don't keep blocking
                    sub.event("override_dismissed", label=label, value=sub.overrides.pop(label), by=officer,
                              note="dismissed by a forced approval")
                for fid in sub.validation.flagged:          # she accepts these cells as they stand
                    fv = sub.record.fields.get(fid)
                    if fv is not None and fv.status in (FieldStatus.auto, FieldStatus.needs_review):
                        fv.status = FieldStatus.officer_confirmed
                        fv.history.append({"at": now(), "event": "forced_approval", "by": officer, "reason": reason})
            sub.event("officer_approved", by=officer, forced=force, overwrite=overwrite, reason=reason or None)
            self.revalidate(sub)
            if sub.member_confirmed:                        # she already said OK; the write had failed
                reply = self.write(sub, notify_failure=False)
            else:
                reply = self._send_summary(sub)
                self.store.save(sub)
            if reply is not None:
                self.conversations.append_bot(sub.sender, reply, sub.id)
            return reply

    def officer_reject(self, sub: Submission, officer: str, reason: str = "other", note: str = "") -> Reply:
        """Ask the member for new photos (or discard a report). She is told why, simply."""
        with lock:
            self._require(sub, OPEN + (Status.failed,), "reject")
            code = reason if reason in M.REJECT_REASONS else "other"
            sub.status, sub.rejected_reason = Status.rejected, code
            sub.event("officer_rejected", by=officer, reason=code, note=(note or reason or "").strip()[:MAX_TEXT] or None)
            reply = sub.say(M.rejected(sub.lang, code))
            self.store.save(sub)
            self.conversations.append_bot(sub.sender, reply, sub.id)
            return reply

    def retry(self, sid: str, officer: str = "officer") -> Optional[Reply]:
        """Read a failed report again (e.g. the network is back)."""
        with lock:
            sub = self.store.load(sid)
            if sub.status != Status.failed:
                raise StateError(f"Can't try again: {WHY_NOT.get(sub.status, sub.status.value)}")
            sub.status = Status.collecting
            sub.event("retry", by=officer)
            self.store.save(sub)
        reply = self.process(sid, quiet_failure=True)
        if reply is not None:
            self.conversations.append_bot(sub.sender, reply, sid)
        return reply

    def process_now(self, sid: str, officer: str = "officer") -> Optional[Reply]:
        """Read a report that only has page 1 (page-2 answers stay empty)."""
        with lock:
            sub = self.store.load(sid)
            if sub.status != Status.collecting:
                raise StateError(f"Can't read it now: {WHY_NOT.get(sub.status, sub.status.value)}")
            if 1 not in sub.pages:
                raise StateError("Can't read it now: page 1 hasn't arrived yet.")
            if sid in self._busy:
                raise StateError("This report is being read right now.")
            sub.event("processed_without_page2" if 2 not in sub.pages else "processed_by_officer", by=officer)
            self.store.save(sub)
        reply = self.process(sid)
        if reply is not None:
            self.conversations.append_bot(sub.sender, reply, sid)
        return reply

    def confirm_new_group(self, sub: Submission, officer: str, started_this_month: bool = False,
                          opening: Optional[dict[str, Any]] = None) -> None:
        """The SHG name is a new group: unknown_shg stops blocking and the writer may create a
        tab. Its opening 'to date' totals (BEFORE this month) are needed for Palmera's column C:
        zeros when it started this month, else all nine from the mother book. They also give
        the week-1 checks their 'last month'. Calling it again replaces the totals."""
        with lock:
            self._require(sub, EDITABLE, "confirm a new group")
            name = sub.record.get("header.shg_name")
            if not name:
                raise StateError("Can't confirm a new group: the SHG name is empty.")
            if sub.shg_tab is not None:
                raise StateError(f"Can't confirm a new group: “{name}” already has a tab in the workbook "
                                 f"({sub.shg_tab}).")
            values = self.check_opening(started_this_month, opening)
            sub.new_group, sub.opening, sub.started_this_month = True, values, bool(started_this_month)
            sub.event("new_group_confirmed", name=name, by=officer, started_this_month=bool(started_this_month),
                      opening=values)
            sub.member_confirmed, sub.write_error = False, None
            if sub.status == Status.awaiting_member:
                sub.status = Status.needs_review
                sub.event("reopened", by=officer, why="new group confirmed")
            self._lookup_prior(sub)
            self.revalidate(sub)
            self.store.save(sub)

    def check_opening(self, started_this_month: bool, opening: Optional[dict[str, Any]]) -> dict[str, float]:
        """The nine opening totals, all present and plausible (ValueError -> HTTP 400)."""
        if started_this_month:
            if opening and any(_amount(v) not in (0, None) for v in opening.values()):
                raise ValueError("Either say the group started this month (its opening totals are then zero), "
                                 "or enter its opening totals from the mother book, not both.")
            return {label: 0 for label in OPENING_LABELS}
        if not opening:
            raise ValueError("Say whether the group started this month, or enter its nine opening totals "
                             "from the mother book (0 is allowed).")
        if not isinstance(opening, dict):
            raise ValueError("Send the opening totals as a list of totals and amounts.")
        unknown = [k for k in opening if k not in OPENING_LABELS]
        if unknown:
            raise ValueError(f"“{str(unknown[0])[:80]}” isn't one of the nine opening totals.")
        missing = [k for k in OPENING_LABELS if opening.get(k) in (None, "")]
        if missing:
            raise ValueError("Enter all nine opening totals from the mother book (0 is allowed). Missing: "
                             + ", ".join(k.replace(" (Rs.)", "") for k in missing) + ".")
        out: dict[str, float] = {}
        for k in OPENING_LABELS:
            v = _amount(opening[k])
            if v is None:
                raise ValueError(f"{k.replace(' (Rs.)', '')}: {_quoted(opening[k])} isn't an amount. "
                                 "Enter it in digits, like 52600.")
            if not 0 <= v <= MAX_MONEY:
                raise ValueError(f"{k.replace(' (Rs.)', '')}: amounts must be between 0 and {MAX_MONEY:,.0f}.")
            out[k] = v
        return out

    def _forget_new_group(self, sub: Submission) -> None:
        """The group name changed: the new-group decision was about the old name."""
        if sub.new_group:
            sub.event("new_group_cleared", why="group name changed")
        sub.new_group, sub.opening, sub.started_this_month = False, None, None

    def actions(self, sub: Submission) -> dict[str, bool]:
        """What the dashboard may offer for this report right now."""
        has = sub.record is not None
        unknown = has and sub.status in EDITABLE and sub.shg_tab is None and bool(sub.record.get("header.shg_name"))
        return {
            "edit": has and sub.status in EDITABLE,
            "approve": has and sub.status == Status.needs_review,
            "reject": sub.status in OPEN + (Status.failed,),
            # Try again can't help when offline demo mode simply can't read this photo
            "retry": sub.status == Status.failed and not (sub.failure_kind in UNKNOWN_SAMPLE_KINDS and self.offline_demo),
            "process_now": sub.status == Status.collecting and 1 in sub.pages and sub.id not in self._busy,
            "new_group": unknown and not sub.new_group,
            "opening": unknown and sub.new_group,            # change the new group's opening totals
            "resend": bool(sub.undelivered()),
        }

    @property
    def offline_demo(self) -> bool:
        return hasattr(self.reader, "for_submission")      # the DemoReader

    # ================================================================ delivery
    def record_delivery(self, sender: str, mid: Optional[str], delivered: Optional[bool],
                        error: Optional[str] = None, wamid: Optional[str] = None) -> None:
        """Write a WhatsApp send's result onto the bot message, in her conversation and in
        the report's log (the same `mid`)."""
        if not mid:
            return
        with lock:
            conv = self.conversations.load(sender)
            m = conv.bot_message(mid=mid)
            sid = m.get("sid") if m else None
            if m is not None:
                m.update(delivered=delivered, delivery_error=error, attempted=now())
                if wamid:
                    m["wamid"] = wamid
                self.conversations.save(conv)
            for s in ([self._load_quiet(sid)] if sid else []):
                e = s.bot_entry(mid) if s else None
                if e is not None:
                    e.update(delivered=delivered, delivery_error=error)
                    self.store.save(s)

    def record_status(self, recipient: str, wamid: str, error: str) -> bool:
        """Meta's status callback says a message we sent was NOT delivered."""
        with lock:
            m = self.conversations.load(recipient).bot_message(wamid=wamid)
            if m is None:
                return False
            self.record_delivery(recipient, m.get("mid"), False, error, wamid)
            return True

    def to_resend(self, sub: Submission) -> list[tuple[str, str]]:
        """[(mid, text)] of her undelivered messages for this report, oldest first: the text
        as it was meant to go out (with the privacy note, if it carried one)."""
        conv = self.conversations.load(sub.sender)
        out = []
        for e in sub.undelivered():
            m = conv.bot_message(mid=e.get("mid"))
            out.append((e.get("mid"), str(m["text"]) if m else str(e.get("text", ""))))
        return out

    def _load_quiet(self, sid: Optional[str]) -> Optional[Submission]:
        try:
            return self.store.load(sid) if sid else None
        except NotFound:
            return None

    def _send_summary(self, sub: Submission) -> Reply:
        sub.status = Status.awaiting_member
        sub.summary_sent = True
        return sub.say(M.member_summary(sub.record, self.t, sub.lang))

    # ================================================================ member replies
    def member_reply(self, sender: str, text: str, lang: Optional[str] = None) -> tuple[Optional[Submission], Reply]:
        """A text from a member. It goes to her NEWEST open report and the answer depends on
        that report's state, always in her language."""
        with lock:
            kind, arg = M.parse_member_reply(text)
            # OK and "5 12000" answer a summary: her newest one waiting for a reply, even if she
            # has started sending next month's photos since. Anything else: her newest report.
            sub = (self._summary_for(sender) if kind in ("confirm", "correct") else None) \
                or self.store.open_for(sender)
            if sub is None:
                return self._no_open_report(sender, kind, lang)
            sub.log.append({"at": now(), "from": "member", "text": text})
            reply = self._answer(sub, kind, arg)
            if sub.status != Status.written:
                self.store.save(sub)
            return sub, reply

    def _summary_for(self, sender: str) -> Optional[Submission]:
        """Her newest report awaiting her OK, unless a newer open report for the same group
        and month (which will replace it) has arrived since: then her reply goes to that one."""
        a = self.store.awaiting_for(sender)
        if a is None:
            return None
        key = self._report_key(a)
        newer = [s for s in self.store.for_sender(sender)
                 if s.created > a.created and s.status in OPEN and self._report_key(s) == key]
        return None if newer else a

    def _no_open_report(self, sender: str, kind: str, lang: Optional[str]) -> tuple[Optional[Submission], Reply]:
        mine = self.store.for_sender(sender)
        lang = lang or self.lang_of(sender)
        if mine and mine[0].status == Status.written and kind == "confirm" and mine[0].record:
            last = mine[0]
            return last, M.msg("already_recorded", lang, group=last.shg_tab or last.record.get("header.shg_name"),
                               month=M.per_lang(lambda l: M.month_name(last.record.get("header.month_year"), l)))
        return None, M.msg("no_report", lang)

    def _answer(self, sub: Submission, kind: str, arg: Any) -> Reply:
        if sub.status == Status.collecting:
            if sub.id in self._busy or 2 in sub.pages and 1 in sub.pages:
                return sub.say(M.msg("reading", sub.lang))
            return sub.say(M.msg("waiting_page2" if 1 in sub.pages else "ask_page1", sub.lang))
        if sub.status == Status.failed:
            return sub.say(M.msg("officer_checking", sub.lang))
        if sub.status == Status.needs_review:
            if kind == "correct" and sub.summary_sent:  # a second correction right after the first
                return self._correction(sub, *arg)
            return sub.say(M.msg("officer_checking", sub.lang))
        # awaiting_member
        if kind == "confirm":
            sub.member_confirmed = True
            sub.event("member_confirmed")
            for fv in sub.record.fields.values():
                if fv.status == FieldStatus.auto:
                    fv.status = FieldStatus.member_confirmed
            return self.write(sub)
        if kind == "correct":
            return self._correction(sub, *arg)
        return sub.say(M.msg("not_understood", sub.lang))

    def _correction(self, sub: Submission, n: int, raw: str) -> Reply:
        key, short, current = M.summary_values(sub.record, self.t)[n - 1]
        try:
            value = self._member_value(key, raw)
        except ValueError:
            return sub.say(M.msg("not_understood_value", sub.lang, n=n))
        shown = M.per_lang(lambda l: M.display_value(key, value, l))
        if self._same(current, value, key):
            return sub.say(M.msg("correction_same", sub.lang, n=n, value=shown))
        sub.overrides[key] = value
        sub.status = Status.needs_review
        sub.member_confirmed = False
        sub.event("member_correction", item=n, label=key, value=value, form_value=current)
        reply = sub.say(M.msg("correction_noted", sub.lang, n=n, value=shown))
        self.revalidate(sub)
        return reply

    def _member_value(self, key: str, raw: str) -> Any:
        if key.startswith("header."):
            ftype = self.t.field_type(key)
            if ftype in ("money", "int"):
                return M.parse_amount(raw, integer=ftype == "int")
            v = normalise(raw, ftype)
            if v is None or (isinstance(v, str) and len(v) > 80):
                raise ValueError(raw)
            return v
        row = self._monthly_rows[key]
        cap = None
        if row["from"] == "header":                   # e.g. Members: a header cell
            prefix = "page2" if row["field"] == "members_with_goals" else "header"
            integer = self.t.field_type(f"{prefix}.{row['field']}") == "int"
            cap = next((f.max for f in self.t.header if f.key == row["field"]), None)
        else:
            integer = row["from"] == "count_yes" or self.t.weekly_row(row["field"]).type == "int"
        v = M.parse_amount(raw, integer=integer)
        if integer and v > (cap if cap is not None else MAX_COUNT):
            raise ValueError(raw)                     # "10 5000" members: ask again, never store it
        return v

    # ================================================================ workbook + receipt
    def write(self, sub: Submission, notify_failure: bool = True) -> Optional[Reply]:
        """Write the 16 cells, then send the receipt. Checked again against the workbook as
        it is NOW; any failure sends the report back to the officer with the reason
        (never silent) and the member is told an officer is checking."""
        with lock:
            self._lookup_prior(sub)
            self.revalidate(sub)
            ignore = {"write_failed"} | ({"month_already_recorded"} if sub.overwrite else set())
            blocking = [i for i in sub.validation.errors if i.rule not in ignore]
            stuck = _not_forceable(blocking)
            if blocking and (not sub.forced or stuck):
                return self._write_failed(sub, f"Not written: {len(blocking)} check(s) failing "
                                               f"({'; '.join(i.message for i in blocking[:3])}).", notify_failure)
            name = sub.shg_tab or sub.record.get("header.shg_name")
            month = sub.record.get("header.month_year")
            if not name or not month:
                return self._write_failed(sub, "Not written: the SHG name or the month is empty.", notify_failure)
            values = to_monthly(sub.record, self.t)
            creating = sub.new_group and sub.shg_tab is None
            try:
                wb = GNWorkbook(self.workbook_path, self.t)
                rep = wb.write_month(str(name), str(month), values, gn_name=sub.record.get("header.village_gn"),
                                     overwrite=bool(sub.overwrite), create_tab=creating,
                                     opening=sub.opening if creating else None)
                wb.save()
            except PermissionError:
                return self._write_failed(sub, f"Close {self.workbook_path.name} in Excel and try again.", notify_failure)
            except WorkbookError as e:
                return self._write_failed(sub, str(e), notify_failure)
            except Exception as e:
                log.exception("writing submission %s failed", sub.id)
                return self._write_failed(sub, f"Couldn't write to the workbook: {_describe(e)}", notify_failure)
            sub.write_report, sub.shg_tab = rep, rep.sheet
            sub.status, sub.write_error = Status.written, None
            for fv in sub.record.fields.values():          # nothing written stays "needs review"
                if fv.status == FieldStatus.needs_review:
                    fv.status = FieldStatus.officer_confirmed if sub.forced else FieldStatus.member_confirmed
            sub.event("written", cells=len(rep.writes), sheet=rep.sheet, column=rep.column)
            reply = sub.say(M.receipt(
                sub.lang, month=month, group=rep.sheet,
                savings=values.get("Savings (Rs.)"), repay=values.get("Principal loan repayments (Rs.)"),
                cash=values.get("Cash in Hand – at end of month (mother book) (Rs.)"),
                # a new tab's total is only right when backed by its opening totals
                savings_to_date=None if rep.created_tab and sub.opening is None
                else _savings_to_date(wb, rep.sheet, str(month))))
            self.store.save(sub)
            return reply

    def _write_failed(self, sub: Submission, message: str, notify: bool) -> Optional[Reply]:
        sub.status, sub.write_error = Status.needs_review, message
        sub.event("write_failed", error=message)
        self.revalidate(sub)
        key = "confirmed_pending" if sub.member_confirmed else "checking"
        reply = sub.say(M.msg(key, sub.lang)) if notify else None
        self.store.save(sub)
        return reply


PIPELINE_RULES = {"member_correction", "write_failed", "unknown_shg", "prior_lookup_failed", "month_already_recorded",
                  "month_out_of_range", "opening_inconsistent"}


def _not_forceable(blocking: list[Issue]) -> Optional[str]:
    """The first failing check "Send anyway" may not skip."""
    return next((i.rule for i in blocking if i.rule in NOT_FORCEABLE), None)


def _amount(v: Any) -> Optional[float]:
    """An opening total as a number (digits, '52,600', 52600.0), else None."""
    if isinstance(v, bool):
        return None
    try:
        n = normalise(v, "money")
    except (ValueError, OverflowError):
        return None
    if not isinstance(n, (int, float)) or not math.isfinite(n):
        return None
    return n


def _quoted(raw: Any) -> str:
    text = str(raw) if not isinstance(raw, str) else raw
    return f"“{text[:40]}{'…' if len(text) > 40 else ''}”"


def _jpeg(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError("could not encode the photo as JPEG")
    return buf.tobytes()


def _savings_to_date(wb: GNWorkbook, sheet: str, month: str) -> Optional[float]:
    """The group's total savings after this month, for the receipt's progress line."""
    try:
        return next((m["savings_to_date"] for m in wb.series(sheet) if m.get("month") == month), None)
    except Exception:                                  # the receipt must not fail over a nicety
        log.warning("savings to date unavailable for %s %s", sheet, month)
        return None


def _show(key: str, v: Any) -> str:
    if v is None:
        return "blank"
    if key == "header.month_year":
        return M.month_name(v, "en")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"Rs {M.number(v)}" if M.is_money_item(key) else M.number(v)
    return f"'{v}'"


def _describe(e: Exception) -> str:
    """A reason an officer can read."""
    text = str(e).strip()
    if isinstance(e, (ExtractionError, WorkbookError)) or getattr(e, "member_key", None):
        return text or "The photos could not be read."
    return f"{type(e).__name__}: {text}" if text else type(e).__name__


def _reading_failure(e: Exception) -> str:
    """Why reading the photos failed, for the failed report's card."""
    if isinstance(e, ExtractionError) or getattr(e, "member_key", None):
        return _describe(e)
    return (f"Something went wrong while reading the photos ({_describe(e)[:200]}). Use Try again; "
            "if it fails again, ask the member for a new photo.")


def _mask(sender: str) -> str:
    """Phone numbers stay out of the server log."""
    return sender if sender.startswith("sim:") else f"…{sender[-3:]}"


def _jsonable(d: dict) -> dict:
    import json
    return json.loads(json.dumps(d, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
