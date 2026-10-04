"""Per-sender chat history, language choice and consent state, plus WhatsApp de-duplication.

A submission's own log only covers that one report. The member's phone (real or
simulated) is one continuous conversation across reports, so every inbound and
outbound message is also kept here, one JSON file per sender:

    DATA/conversations/<safe-sender>.json

The simulated phone is rebuilt from this file after a reload. It also remembers the
member's language, whether she has had the privacy note, and whether she opted out.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from .locking import atomic_write_text, lock

log = logging.getLogger("shg.conversations")

MAX_MESSAGES = 500          # per sender; older messages are dropped from the phone view
MAX_SEEN_IDS = 5000         # WhatsApp message ids remembered for de-duplication
MAX_IN_FLIGHT = 500         # WhatsApp messages accepted but not processed yet (more: 503, Meta retries)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_mid() -> str:
    """Id of one bot message, shared by the submission log and the conversation log."""
    return uuid.uuid4().hex[:12]


def safe_name(sender: str) -> str:
    """A file name that can't escape the folder, unique per sender (the hash keeps
    'sim:a' and 'sim_a' apart)."""
    stem = re.sub(r"[^0-9A-Za-z_+-]", "_", sender)[:60] or "sender"
    return f"{stem}-{hashlib.sha1(sender.encode('utf-8')).hexdigest()[:8]}"


class Conversation(BaseModel):
    sender: str
    lang: str = "en"
    lang_chosen: bool = False          # the member picked a language (or wrote in si/ta script)
    privacy_sent: bool = False
    opted_out: bool = False
    messages: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)

    def add_member(self, *, text: Optional[str] = None, image: Optional[str] = None, is_image: bool = False,
                   sid: Optional[str] = None, at: Optional[str] = None) -> None:
        m: dict[str, Any] = {"at": at or now(), "from": "me"}
        if is_image:
            m["image"] = image                # sample file name in the simulator, else None
        else:
            m["text"] = text
        if sid:
            m["sid"] = sid
        self._append(m)

    def add_bot(self, reply: str, sid: Optional[str] = None) -> str:
        """Record a bot message. `delivered` is None until a WhatsApp send reports back
        (and stays None for the simulator, where nothing is sent). Returns its id."""
        mid = getattr(reply, "mid", None) or new_mid()
        m: dict[str, Any] = {"at": now(), "from": "bot", "text": str(reply), "mid": mid,
                             "delivered": None, "delivery_error": None}
        en = getattr(reply, "en", None)
        if en:
            m["text_en"] = en
        if sid:
            m["sid"] = sid
        self._append(m)
        return mid

    def bot_message(self, *, mid: Optional[str] = None, wamid: Optional[str] = None) -> Optional[dict[str, Any]]:
        """The newest bot message with this id (ours, or the WhatsApp id Meta gave it)."""
        for m in reversed(self.messages):
            if m.get("from") == "bot" and ((mid and m.get("mid") == mid) or (wamid and m.get("wamid") == wamid)):
                return m
        return None

    def event(self, kind: str, /, **kw: Any) -> None:
        self.events.append({"at": now(), "event": kind, **kw})
        self.events = self.events[-200:]

    def _append(self, m: dict[str, Any]) -> None:
        self.messages.append(m)
        if len(self.messages) > MAX_MESSAGES:
            self.messages = self.messages[-MAX_MESSAGES:]


class Conversations:
    def __init__(self, root: Path):
        self.dir = Path(root) / "conversations"

    def path(self, sender: str) -> Path:
        return self.dir / f"{safe_name(sender)}.json"

    def load(self, sender: str) -> Conversation:
        p = self.path(sender)
        if p.exists():
            try:
                return Conversation.model_validate_json(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:          # unreadable file: start afresh, keep the old one
                log.warning("unreadable conversation %s: %s", p.name, e)
        return Conversation(sender=sender)

    def save(self, conv: Conversation) -> None:
        with lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.path(conv.sender), conv.model_dump_json(indent=1))

    def append_bot(self, sender: str, reply: str, sid: Optional[str] = None) -> None:
        """Record a message the bot sent outside a member turn (officer approved, rejected…)."""
        with lock:
            conv = self.load(sender)
            conv.add_bot(reply, sid)
            self.save(conv)

    def clear(self) -> None:
        with lock:
            shutil.rmtree(self.dir, ignore_errors=True)


class SeenMessages:
    """WhatsApp message ids already handled. Meta re-delivers a message when our 200
    is slow or lost; without this, a re-delivered page 2 starts a second report.

    claim() is called by the webhook itself (in memory, no file I/O and no global lock, so a
    burst of photo uploads can't delay Meta's 200). An id is written to disk by done() only
    once its message has been processed (or failed for good); until then it is "in flight",
    so a re-delivery that arrives meanwhile is still ignored."""

    def __init__(self, root: Path):
        self.path = Path(root) / "whatsapp_seen.json"
        self._mu = threading.Lock()
        self._seen: dict[str, None] = dict.fromkeys(self._load())     # ordered, oldest first
        self._in_flight: set[str] = set()

    def _load(self) -> list[str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
            return [x for x in data if isinstance(x, str)] if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def busy(self) -> bool:
        """Too many messages accepted and not processed yet: refuse more for now."""
        return len(self._in_flight) >= MAX_IN_FLIGHT

    def claim(self, msg_id: Optional[str]) -> bool:
        """True the first time an id is seen (it is then in flight until done()). Messages
        without an id can't be de-duplicated and always count as new."""
        if not msg_id:
            return True
        with self._mu:
            if msg_id in self._seen or msg_id in self._in_flight:
                return False
            self._in_flight.add(msg_id)
            return True

    def done(self, msg_id: Optional[str]) -> None:
        """The message was processed (or failed for good): remember it on disk."""
        if not msg_id:
            return
        with self._mu:
            self._in_flight.discard(msg_id)
            self._seen[msg_id] = None
            while len(self._seen) > MAX_SEEN_IDS:
                del self._seen[next(iter(self._seen))]
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(self.path, json.dumps(list(self._seen)))
            except OSError as e:                      # memory still de-duplicates
                log.warning("could not save seen WhatsApp ids: %s", e)

    def release(self, msg_id: Optional[str]) -> None:
        """Forget an in-flight id without processing it (we answered Meta 503: it retries)."""
        if msg_id:
            with self._mu:
                self._in_flight.discard(msg_id)

    def first_time(self, msg_id: Optional[str]) -> bool:
        """claim() + done() in one step."""
        fresh = self.claim(msg_id)
        if fresh:
            self.done(msg_id)
        return fresh
