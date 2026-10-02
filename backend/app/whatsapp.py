"""WhatsApp Cloud API (Meta) connector: receive photos/text via webhook, send replies.

Setup (Meta developer account -> app -> WhatsApp product):
  WHATSAPP_TOKEN         access token
  WHATSAPP_PHONE_ID      phone number id of the programme number
  WHATSAPP_VERIFY_TOKEN  any secret string, also entered in the Meta webhook settings
                         (required: without it the webhook handshake is refused)
  WHATSAPP_APP_SECRET    the Meta app secret. When set, every webhook POST must carry a
                         valid X-Hub-Signature-256 header; unsigned or forged posts get 401.
                         Always set it in production: without it anyone who finds the URL
                         could post "OK" on a member's behalf.
  WHATSAPP_API_VERSION   Graph API version, e.g. v21.0 (check Meta's docs for the current one)
Test numbers can only message phones added to the app's recipient list.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Optional

import httpx

GRAPH = "https://graph.facebook.com"
MAX_MEDIA_BYTES = 15 * 1024 * 1024
IMAGE_MIMES = ("image/jpeg", "image/png", "image/webp")


def _cfg(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"{name} is not set")
    return v


def version() -> str:
    return os.environ.get("WHATSAPP_API_VERSION", "v21.0")


def configured() -> bool:
    """Can we send messages?"""
    return bool(os.environ.get("WHATSAPP_TOKEN") and os.environ.get("WHATSAPP_PHONE_ID"))


def verify(params: dict[str, str]) -> Optional[str]:
    """Webhook verification handshake: echo hub.challenge if the token matches.
    Refused when WHATSAPP_VERIFY_TOKEN isn't set (otherwise a missing token would match)."""
    expected = os.environ.get("WHATSAPP_VERIFY_TOKEN")
    given = params.get("hub.verify_token") or ""
    challenge = params.get("hub.challenge") or ""
    if not expected or params.get("hub.mode") != "subscribe":
        return None
    if not hmac.compare_digest(given.encode(), expected.encode()):
        return None
    if not challenge or len(challenge) > 128 or not challenge.replace("-", "").replace("_", "").isalnum():
        return None
    return challenge


def signature_required() -> bool:
    return bool(os.environ.get("WHATSAPP_APP_SECRET"))


def signature_ok(body: bytes, header: Optional[str]) -> bool:
    """X-Hub-Signature-256 = 'sha256=' + HMAC-SHA256(app secret, raw body). True when no
    secret is configured (local testing only)."""
    secret = os.environ.get("WHATSAPP_APP_SECRET")
    if not secret:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):].strip().lower())


def _list(x: Any) -> list:
    return x if isinstance(x, list) else []


def _dict(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def parse_incoming(payload: Any) -> list[dict[str, Any]]:
    """Flatten a webhook payload into [{sender, id, type: text|image|unsupported, text|media_id|kind}].
    Never raises: odd shapes are skipped, so Meta always gets its 200 and doesn't retry.
    Status callbacks (delivered/read) carry no messages and give an empty list."""
    out: list[dict[str, Any]] = []
    for entry in _list(_dict(payload).get("entry")):
        for change in _list(_dict(entry).get("changes")):
            for msg in _list(_dict(_dict(change).get("value")).get("messages")):
                m = _parse_message(_dict(msg))
                if m is not None:
                    out.append(m)
    return out


def _parse_message(msg: dict) -> Optional[dict[str, Any]]:
    sender = msg.get("from")
    if not isinstance(sender, str) or not sender.strip() or len(sender) > 32:
        return None
    typ = msg.get("type")
    mid = msg.get("id") if isinstance(msg.get("id"), str) else None
    m: dict[str, Any] = {"sender": sender.strip(), "id": mid, "type": "unsupported", "kind": str(typ)[:20]}
    if typ == "text":
        body = _dict(msg.get("text")).get("body")
        if isinstance(body, str) and body.strip():
            m.update(type="text", text=body)
    elif typ in ("image", "document"):
        media = _dict(msg.get(typ))
        mime = str(media.get("mime_type") or ("image/jpeg" if typ == "image" else "")).split(";")[0].strip().lower()
        if isinstance(media.get("id"), str) and media["id"] and mime in IMAGE_MIMES:
            m.update(type="image", media_id=media["id"], mime=mime)
        elif typ == "image" and isinstance(media.get("id"), str):
            m.update(type="image", media_id=media["id"], mime=mime)
        else:
            m["kind"] = f"{typ}:{mime or 'unknown'}"[:40]
    elif typ == "reaction":
        emoji = _dict(msg.get("reaction")).get("emoji")
        if not emoji:
            return None                        # a reaction was removed: nothing to answer
        m.update(type="text", text=str(emoji))
    elif typ == "button":
        text = _dict(msg.get("button")).get("text")
        if isinstance(text, str) and text.strip():
            m.update(type="text", text=text)
    elif typ == "interactive":
        it = _dict(msg.get("interactive"))
        title = _dict(it.get("button_reply")).get("title") or _dict(it.get("list_reply")).get("title")
        if isinstance(title, str) and title.strip():
            m.update(type="text", text=title)
    return m


def download_media(media_id: str) -> bytes:
    token = _cfg("WHATSAPP_TOKEN")
    h = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=30) as c:
        meta = c.get(f"{GRAPH}/{version()}/{media_id}", headers=h).raise_for_status().json()
        if int(meta.get("file_size") or 0) > MAX_MEDIA_BYTES:
            raise ValueError("media file too large")
        data = c.get(meta["url"], headers=h).raise_for_status().content
        if len(data) > MAX_MEDIA_BYTES:
            raise ValueError("media file too large")
        return data


def send_text(to: str, text: str) -> dict:
    return _send(to, {"type": "text", "text": {"body": text[:4096]}})


def send_image(to: str, media_id: str, caption: str = "") -> dict:
    return _send(to, {"type": "image", "image": {"id": media_id, "caption": caption[:1024]}})


def upload_media(data: bytes, mime: str, filename: str) -> str:
    token, phone = _cfg("WHATSAPP_TOKEN"), _cfg("WHATSAPP_PHONE_ID")
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{GRAPH}/{version()}/{phone}/media", headers={"Authorization": f"Bearer {token}"},
                   data={"messaging_product": "whatsapp"}, files={"file": (filename, data, mime)})
        return r.raise_for_status().json()["id"]


def _send(to: str, body: dict) -> dict:
    token, phone = _cfg("WHATSAPP_TOKEN"), _cfg("WHATSAPP_PHONE_ID")
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{GRAPH}/{version()}/{phone}/messages", headers={"Authorization": f"Bearer {token}"},
                   json={"messaging_product": "whatsapp", "to": to, **body})
        return r.raise_for_status().json()
