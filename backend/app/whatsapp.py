"""WhatsApp Cloud API (Meta) connector: receive photos/text via webhook, send replies.

Setup (Meta developer account -> app -> WhatsApp product):
  WHATSAPP_TOKEN         access token
  WHATSAPP_PHONE_ID      phone number id of the programme number
  WHATSAPP_VERIFY_TOKEN  any secret string, also entered in the Meta webhook settings
                         (required: without it the webhook handshake is refused)
  WHATSAPP_APP_SECRET    the Meta app secret. When set, every webhook POST must carry a
                         valid X-Hub-Signature-256 header; unsigned or forged posts get 401.
                         Always set it in production: without it anyone who finds the URL
                         could post "OK" on a member's behalf. With WHATSAPP_TOKEN set and
                         no app secret, the webhook REFUSES every post (503) unless
  WHATSAPP_ALLOW_UNSIGNED=1  is set (local testing only).
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


def allow_unsigned() -> bool:
    return os.environ.get("WHATSAPP_ALLOW_UNSIGNED") == "1"


UNSIGNED_REFUSED = ("WhatsApp is configured (WHATSAPP_TOKEN) but WHATSAPP_APP_SECRET is not set, so incoming "
                    "messages can't be checked and the webhook refuses them. Set WHATSAPP_APP_SECRET "
                    "(or WHATSAPP_ALLOW_UNSIGNED=1 for local testing only).")


def webhook_state() -> str:
    """'signed': every post must be signed by Meta. 'refused': WhatsApp can send but posts
    can't be checked, so they are refused. 'unsigned': posts are accepted unchecked (local
    testing: no token, or WHATSAPP_ALLOW_UNSIGNED=1)."""
    if signature_required():
        return "signed"
    if configured() and not allow_unsigned():
        return "refused"
    return "unsigned"


def signature_ok(body: bytes, header: Optional[str]) -> bool:
    """X-Hub-Signature-256 = 'sha256=' + HMAC-SHA256(app secret, raw body). True when no
    secret is configured (local testing only; see webhook_state). Never raises: a header with
    non-ASCII characters is simply wrong."""
    secret = os.environ.get("WHATSAPP_APP_SECRET")
    if not secret:
        return True
    if not header or not header.isascii() or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), header[len("sha256="):].strip().lower().encode())


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


def parse_statuses(payload: Any) -> list[dict[str, Any]]:
    """Delivery callbacks for messages WE sent: [{wamid, recipient, status, error}].
    Meta reports a send it accepted but could not deliver (e.g. outside the 24-hour window)
    only here, as status 'failed' with an errors[] list. Never raises."""
    out: list[dict[str, Any]] = []
    for entry in _list(_dict(payload).get("entry")):
        for change in _list(_dict(entry).get("changes")):
            for st in _list(_dict(_dict(change).get("value")).get("statuses")):
                st = _dict(st)
                wamid, to, status = st.get("id"), st.get("recipient_id"), st.get("status")
                if not (isinstance(wamid, str) and isinstance(to, str) and isinstance(status, str)):
                    continue
                err = _dict(next(iter(_list(st.get("errors"))), {}))
                out.append({"wamid": wamid[:200], "recipient": to.strip()[:32], "status": status[:20],
                            "error": describe_error(err.get("code"), err.get("title") or err.get("message"))
                            if status == "failed" else None})
    return out


def describe_error(code: Any, text: Any = None) -> str:
    """A WhatsApp error in words an officer can act on."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None
    if code == 131047:
        return ("Not delivered: more than 24 hours have passed since her last message, so WhatsApp only allows "
                "an approved template message. Ask her to send any message, then use Resend.")
    if code in (131026, 131030):
        return ("Not delivered: WhatsApp can't reach this number (it may not use WhatsApp, or it isn't on the "
                "test number's recipient list).")
    if code in (190, 0) or code == 401:
        return "Not delivered: the WhatsApp access token is wrong or has expired. Renew WHATSAPP_TOKEN, then use Resend."
    detail = f" ({str(text)[:200]})" if text else ""
    return f"Not delivered: WhatsApp refused the message{detail}. Use Resend to try again."


def describe_send_error(e: Exception) -> str:
    """Why send_text failed, for the officer."""
    resp = getattr(e, "response", None)
    if resp is not None:
        try:
            err = _dict(_dict(resp.json()).get("error"))
        except ValueError:
            err = {}
        if err:
            return describe_error(err.get("code"), err.get("message"))
        if resp.status_code == 401:
            return describe_error(401)
        return describe_error(None, f"HTTP {resp.status_code}")
    if isinstance(e, RuntimeError) and "is not set" in str(e):
        return f"Not sent: WhatsApp isn't set up on this server ({e})."
    return f"Not delivered: WhatsApp could not be reached ({type(e).__name__}). Use Resend to try again."


def sent_id(result: Any) -> Optional[str]:
    """The WhatsApp message id ('wamid…') Meta gave a message we sent."""
    msgs = _list(_dict(result).get("messages"))
    mid = _dict(msgs[0]).get("id") if msgs else None
    return mid if isinstance(mid, str) else None


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
