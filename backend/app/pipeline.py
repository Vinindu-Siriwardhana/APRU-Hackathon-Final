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
replaced atomically. Reading the handwriting is slow (Claude mode: several API calls),
so it runs outside the lock: process() saves the photos, reads them unlocked, then
re-loads the submission under the lock to store the result.
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

import numpy as np
from pydantic import BaseModel, Field

from . import messages as M
from .aggregate import last_active_week, to_monthly
from .conversations import Conversation, Conversations
from .extraction import ExtractionError, Reader, extract
from .imaging.io import read_image, write_image
from .imaging.layout import Alignment, FormLocator, save_crop
from .imaging.quality import check
from .labels import short_label
from .locking import atomic_write_text, lock
from .messages import Reply
from .models import Category, FieldStatus, FieldValue, FormRecord, Issue, Legibility, PriorMonth, Severity, normalise
from .schema import WEEKS, Template, load_template
from .validation import ValidationResult, Validator
from .workbook import GNWorkbook, WorkbookError, WriteReport


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
    Status.collecting: "This report is still being collected: no page has been read yet.",
    Status.needs_review: "This report is waiting for an officer's review.",
    Status.awaiting_member: "This report was sent to the member and is waiting for her reply.",
    Status.written: "This report is already in the workbook. It can't be changed here.",
    Status.failed: "The photos could not be read. Use Try again, or Reject it.",
    Status.superseded: "A newer report for this group and month replaced this one.",
    Status.rejected: "This report was rejected.",
}


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
    superseded_by: Optional[str] = None
    rejected_reason: Optional[str] = None
    log: list[dict[str, Any]] = Field(default_factory=list)              # chat transcript + events

    def say(self, reply: str) -> Reply:
        entry: dict[str, Any] = {"at": now(), "from": "bot", "text": str(reply)}
        en = getattr(reply, "en", None)
        if en:
            entry["text_en"] = en
        self.log.append(entry)
        return reply if isinstance(reply, Reply) else Reply(reply)

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
                 image_name: Optional[str] = None, source: Optional[str] = None) -> tuple[Optional[Submission], Reply]:
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
            reply = self._with_privacy(conv, reply)
            conv.add_member(is_image=True, image=image_name, sid=sub.id if sub else None, at=at)
            conv.add_bot(reply, sub.id if sub else None)
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
            conv.add_bot(reply, sub.id if sub else None)
            self.conversations.save(conv)
        return sub, reply

    def on_other(self, sender: str, kind: str, reply_key: str = "unsupported") -> tuple[None, Reply]:
        """A voice note, sticker, file, an undecodable photo…: say what we can read."""
        with lock:
            conv = self.conversations.load(sender)
            reply = self._with_privacy(conv, M.msg(reply_key, conv.lang))
            conv.add_member(text=f"[{kind}]")
            conv.add_bot(reply)
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
        offline demo reader needs."""
        with lock:
            sub = self._collecting_for(sender) or Submission(sender=sender, lang=lang or self.lang_of(sender))
            if sub.id in self._busy:                   # she re-sent a page while we read the report
                return sub, M.msg("reading", sub.lang)
            sub.log.append({"at": now(), "from": "member", "image": True})
            q = check(img, self.loc)
            if not q.ok:
                reply = sub.say(Reply(q.message(sub.lang), q.message("en") if sub.lang != "en" else None))
                sub.event("quality_rejected", problem=q.problem, metrics=_jsonable(q.metrics))
                self.store.save(sub)
                return sub, reply
            path = self.store.ensure_dir(sub.id) / f"page{q.page}.jpg"
            write_image(path, img)
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
        return self.store.load(sub.id), reply

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
            rec, error, key = self._read(sub), None, None
        except Exception as e:
            rec, error, key = None, _describe(e), getattr(e, "member_key", "extraction_failed")
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
            if error is not None:
                sub.status, sub.failure = Status.failed, error
                sub.event("extraction_failed", reason=error)
                reply = None if quiet_failure else sub.say(M.msg(key, sub.lang))
                self.store.save(sub)
                return reply
            sub.record, sub.failure = rec, None
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
        d = self.store.ensure_dir(sid) / "crops"
        for fid in rec.fields:
            page = 1 if fid.startswith(("header.", "weekly.")) else 2
            if page in als:
                crop = self.loc.crop(als[page], fid)
                if crop is not None and crop.size:
                    save_crop(crop, d / f"{fid}.jpg")

    def _lookup_prior(self, sub: Submission) -> None:
        """Find the SHG's tab and last month's balances. Run again whenever the officer
        changes the SHG name or the month."""
        sub.prior, sub.prior_error, sub.shg_tab, sub.shg_candidates = None, None, None, []
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
                sub.event("shg_not_found", name=name, candidates=sub.shg_candidates)
                return
            if not month:
                return
            prior = wb.prior_month(tab, str(month)) or PriorMonth()
            prior.this_month_recorded = bool(wb.month_recorded(tab, str(month)))
            sub.prior = prior
        except Exception as e:                         # WorkbookError, a bad month, a damaged file…
            sub.prior_error = _describe(e)
            sub.event("prior_lookup_failed", error=sub.prior_error)

    def revalidate(self, sub: Submission) -> None:
        res = self.validator.validate(sub.record, sub.prior)
        self._member_correction_issues(sub, res)
        name = sub.record.get("header.shg_name")
        if name and sub.shg_tab is None and not any(i.rule == "unknown_shg" for i in res.issues):
            did_you_mean = f" Did you mean {', '.join(sub.shg_candidates)}?" if sub.shg_candidates else ""
            if sub.new_group:
                res.add(Issue(rule="unknown_shg", severity=Severity.warning, category=Category.continuity,
                              message=f"'{name}' is a new group (confirmed by an officer): a new tab will be "
                                      "created in the GN workbook when this report is written.",
                              fields=["header.shg_name"]))
            else:
                res.add(Issue(rule="unknown_shg", severity=Severity.error, category=Category.continuity,
                              message=f"No tab for SHG '{name}' in the GN workbook.{did_you_mean} "
                                      "Fix the name, or confirm this is a new group.",
                              fields=["header.shg_name"], expected=sub.shg_candidates or None, found=name))
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
            if issue.severity != Severity.error or issue.rule in PIPELINE_RULES:
                continue
            if issue.category not in (Category.arithmetic, Category.capture, Category.range):
                continue
            fids = [f for f in issue.fields if f in sub.record.fields]
            if fids and len(fids) == len(issue.fields) and all(sub.record.fields[f].status in checked for f in fids):
                issue.severity = Severity.warning
                issue.category = Category.finding
                issue.message = "Checked against the photo, kept as written: " + issue.message
        self.validator.finish(sub.record, res, sub.prior)   # rebuilds `flagged` and the `likely` ranking
        sub.validation = res
        # field status follows the checks: flagged -> needs_review, no longer flagged -> auto
        for fid, fv in sub.record.fields.items():
            if fid in res.flagged and fv.status == FieldStatus.auto:
                fv.status = FieldStatus.needs_review
            elif fid not in res.flagged and fv.status == FieldStatus.needs_review:
                fv.status = FieldStatus.auto

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
            if self._same(found, v):
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

    def _same(self, a: Any, b: Any) -> bool:
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
            return abs(a - b) <= float(self.t.validation.get("money_tolerance", 1))
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
                    raise NotFound(f"unknown field {field_id!r}")
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
                    sub.new_group = False
            sub.write_error = None
            if field_id in ("header.shg_name", "header.month_year"):
                self._lookup_prior(sub)
            self.revalidate(sub)
            self.store.save(sub)

    def check_value(self, field_id: str, raw: Any) -> Any:
        """Normalise an officer's value, refusing anything that can't be a real cell value."""
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        ftype = self.t.field_type(field_id)
        if isinstance(raw, (list, dict)):
            raise ValueError("Enter a single value.")
        if ftype in ("money", "int"):
            if isinstance(raw, bool):
                raise ValueError("Enter a number.")
            if isinstance(raw, float) and not math.isfinite(raw):
                raise ValueError("Enter a real number.")
            v = normalise(raw, ftype)
            if v is None:
                return None
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"Not a number: {raw!r}")
            if ftype == "int":
                if float(v) != int(v):
                    raise ValueError("Enter a whole number.")
                v = int(v)
                if not 0 <= v <= MAX_COUNT:
                    raise ValueError(f"Enter a number between 0 and {MAX_COUNT:,}.")
            elif not 0 <= v <= MAX_MONEY:
                raise ValueError(f"Amounts must be between 0 and {MAX_MONEY:,.0f}.")
            return v
        if ftype == "yesno":
            return normalise(raw, ftype)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and not math.isfinite(raw):
            raise ValueError("Enter a real value.")
        v = normalise(raw, ftype)
        if isinstance(v, str) and len(v) > MAX_TEXT:
            raise ValueError(f"Keep it under {MAX_TEXT} characters.")
        return v

    def officer_override(self, sub: Submission, label: str, accept: bool, officer: str) -> None:
        """Decide on a member's correction. accept=False keeps the form's figure.
        accept=True is only possible when the figure comes from ONE cell: it sets that cell
        (status member_corrected) and everything is checked again. A figure that is a sum
        of weekly cells must be fixed in those cells; the correction then resolves itself."""
        with lock:
            self._require(sub, EDITABLE, "decide on the member's correction")
            if label not in sub.overrides:
                raise NotFound(f"no pending member correction for {label!r}")
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
                    sub.new_group = False
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
                raise StateError(f"{n} check{'s' if n != 1 else ''} still failing. Fix them, "
                                 "or approve anyway with a reason.")
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

    def confirm_new_group(self, sub: Submission, officer: str) -> None:
        """The SHG name is a new group: unknown_shg stops blocking and the writer may create a tab."""
        with lock:
            self._require(sub, EDITABLE, "confirm a new group")
            name = sub.record.get("header.shg_name")
            if not name:
                raise StateError("Can't confirm a new group: the SHG name is empty.")
            if sub.shg_tab is not None:
                raise StateError(f"'{name}' already has a tab in the workbook ({sub.shg_tab}).")
            sub.new_group = True
            sub.event("new_group_confirmed", name=name, by=officer)
            self._reopen(sub, officer, "new group confirmed")
            self.revalidate(sub)
            self.store.save(sub)

    def actions(self, sub: Submission) -> dict[str, bool]:
        """What the dashboard may offer for this report right now."""
        has = sub.record is not None
        return {
            "edit": has and sub.status in EDITABLE,
            "approve": has and sub.status == Status.needs_review,
            "reject": sub.status in OPEN + (Status.failed,),
            "retry": sub.status == Status.failed,
            "process_now": sub.status == Status.collecting and 1 in sub.pages and sub.id not in self._busy,
            "new_group": has and sub.status in EDITABLE and sub.shg_tab is None and not sub.new_group
                         and bool(sub.record.get("header.shg_name")),
        }

    def _send_summary(self, sub: Submission) -> Reply:
        sub.status = Status.awaiting_member
        sub.summary_sent = True
        return sub.say(M.member_summary(sub.record, self.t, sub.lang))

    # ================================================================ member replies
    def member_reply(self, sender: str, text: str, lang: Optional[str] = None) -> tuple[Optional[Submission], Reply]:
        """A text from a member. It goes to her NEWEST open report and the answer depends on
        that report's state, always in her language."""
        with lock:
            sub = self.store.open_for(sender)
            kind, arg = M.parse_member_reply(text)
            if sub is None:
                return self._no_open_report(sender, kind, lang)
            sub.log.append({"at": now(), "from": "member", "text": text})
            reply = self._answer(sub, kind, arg)
            if sub.status != Status.written:
                self.store.save(sub)
            return sub, reply

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
        if self._same(current, value):
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
        integer = row["from"] == "count_yes" or self.t.weekly_row(row["field"]).type == "int"
        return M.parse_amount(raw, integer=integer)

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
            if blocking and not sub.forced:
                return self._write_failed(sub, f"Not written: {len(blocking)} check(s) failing "
                                               f"({'; '.join(i.message for i in blocking[:3])}).", notify_failure)
            name = sub.shg_tab or sub.record.get("header.shg_name")
            month = sub.record.get("header.month_year")
            if not name or not month:
                return self._write_failed(sub, "Not written: the SHG name or the month is empty.", notify_failure)
            values = to_monthly(sub.record, self.t)
            try:
                wb = GNWorkbook(self.workbook_path, self.t)
                rep = wb.write_month(str(name), str(month), values, gn_name=sub.record.get("header.village_gn"),
                                     overwrite=bool(sub.overwrite), create_tab=sub.new_group)
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
                savings_to_date=_savings_to_date(wb, rep.sheet, str(month))))
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


PIPELINE_RULES = {"member_correction", "write_failed", "unknown_shg", "prior_lookup_failed", "month_already_recorded"}


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
    if isinstance(e, ExtractionError) or getattr(e, "member_key", None):
        return text or type(e).__name__
    return f"{type(e).__name__}: {text}" if text else type(e).__name__


def _mask(sender: str) -> str:
    """Phone numbers stay out of the server log."""
    return sender if sender.startswith("sim:") else f"…{sender[-3:]}"


def _jsonable(d: dict) -> dict:
    import json
    return json.loads(json.dumps(d, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
