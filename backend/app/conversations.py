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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from .locking import atomic_write_text, lock

log = logging.getLogger("shg.conversations")

MAX_MESSAGES = 500          # per sender; older messages are dropped from the phone view
MAX_SEEN_IDS = 5000         # WhatsApp message ids remembered for de-duplication


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


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

    def add_bot(self, reply: str, sid: Optional[str] = None) -> None:
        m: dict[str, Any] = {"at": now(), "from": "bot", "text": str(reply)}
        en = getattr(reply, "en", None)
        if en:
            m["text_en"] = en
        if sid:
            m["sid"] = sid
        self._append(m)

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
    is slow or lost; without this, a re-delivered page 2 starts a second report."""

    def __init__(self, root: Path):
        self.path = Path(root) / "whatsapp_seen.json"

    def _load(self) -> list[str]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
        except (OSError, ValueError):
            return []

    def first_time(self, msg_id: Optional[str]) -> bool:
        """True (and remembered) the first time an id is seen. Messages without an id
        can't be de-duplicated and always count as new."""
        if not msg_id:
            return True
        with lock:
            seen = self._load()
            if msg_id in seen:
                return False
            seen.append(msg_id)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.path, json.dumps(seen[-MAX_SEEN_IDS:]))
            return True
