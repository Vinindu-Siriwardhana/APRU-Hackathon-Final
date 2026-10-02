"""HTTP API for the officer dashboard, the in-app WhatsApp simulator and the real webhook.

    uvicorn app.api:app --reload            (from backend/)

Environment
  SHG_DATA_DIR            where submissions and conversations are stored (default: ../data)
  SHG_WORKBOOK            the GN workbook .xlsx to write into (default: ../data/gn_workbook.xlsx,
                          seeded with demo groups on first run)
  ANTHROPIC_API_KEY       if set, handwriting is read by Claude; if not, the API runs in
                          OFFLINE DEMO mode and only recognises the synthetic sample photos
  SHG_DISABLE_SIMULATOR=1 turn off /api/sim/* (do this in production)
  SHG_ALLOW_RESET=1       allow /api/demo/reset outside offline demo mode
  WHATSAPP_*              see whatsapp.py

Privacy: there is no login. The server must stay bound to 127.0.0.1 (the default);
data/ holds phone numbers, chats and photos in plain files.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

from . import messages as M
from . import whatsapp
from .aggregate import to_monthly
from .conversations import SeenMessages
from .demo_reader import DemoReader, SampleIndex
from .labels import short_label
from .locking import lock, replace
from .pipeline import NotFound, Pipeline, StateError, Status, Store, Submission
from .schema import load_template
from .workbook import GNWorkbook, WorkbookError

log = logging.getLogger("shg.api")

ROOT = Path(__file__).parents[2]
SYN = ROOT / "samples" / "synthetic"
DIST = ROOT / "frontend" / "dist"
T = load_template()

MAX_UPLOAD = 15 * 1024 * 1024          # bytes
MAX_PIXELS = 40_000_000                # a decompression bomb is refused before decoding
MAX_SIDE = 4000                        # larger photos are scaled down (plenty for the reader)
FIELD_RE = re.compile(r"^[A-Za-z0-9_.]{1,80}$")
SENDER_RE = re.compile(r"^[A-Za-z0-9_.:+-]{1,48}$")


class BadImage(ValueError):
    pass


def decode_image(data: bytes) -> np.ndarray:
    """Bytes -> BGR image, refusing empty, huge or undecodable uploads."""
    if not data:
        raise BadImage("The upload is empty.")
    if len(data) > MAX_UPLOAD:
        raise BadImage("The photo is larger than 15 MB.")
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as im:        # reads the header only
            w, h = im.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise BadImage("This is not a photo we can open (send a JPG or PNG).") from None
    if w * h > MAX_PIXELS:
        raise BadImage(f"The photo is too large ({w}×{h} pixels).")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise BadImage("This is not a photo we can open (send a JPG or PNG).")
    s = MAX_SIDE / max(img.shape[:2])
    if s < 1:
        img = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
    return img


class _RedactToken(logging.Filter):
    """Keep the webhook verify token out of uvicorn's access log (it is in the query string)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and any("verify_token" in str(a) for a in record.args):
            record.args = tuple(re.sub(r"(hub\.verify_token=)[^&\s]*", r"\1***", a) if isinstance(a, str) else a
                                for a in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactToken())


def seed_workbook(path: Path) -> None:
    """(Re)create the demo workbook atomically: seed a temp file, then replace."""
    sys.path.insert(0, str(ROOT / "tools"))
    from seed_demo_workbook import seed
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.{uuid.uuid4().hex[:8]}.seed.xlsx")
    try:
        seed(tmp)
        replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- request bodies
class FieldUpdate(BaseModel):
    value: Any = None
    officer: str = "officer"


class OverrideDecision(BaseModel):
    label: str
    accept: bool
    officer: str = "officer"


class Approve(BaseModel):
    officer: str = "officer"
    force: bool = False
    reason: str = ""
    overwrite: bool = False


class Reject(BaseModel):
    officer: str = "officer"
    reason: str = "other"
    note: str = ""


class Officer(BaseModel):
    officer: str = "officer"


def _officer(name: str) -> str:
    name = " ".join(str(name or "").split())[:60]
    return name or "officer"


def _flags(series: list[dict], last_month: str) -> list[dict]:
    """Early warnings a monitoring officer would want to see first."""
    flags: list[dict] = []
    if not series:
        return [{"level": "warning", "text": "No months recorded yet"}]
    cur = series[-1]
    if cur["month"] < last_month:
        flags.append({"level": "warning", "text": f"No report since {cur['month']}"})
    rates = [m["attendance_rate"] for m in series if m["attendance_rate"] is not None]
    if rates and rates[-1] < 0.6:
        flags.append({"level": "critical", "text": f"Attendance {rates[-1]:.0%} of members"})
    elif len(rates) >= 2 and max(rates[-4:]) - rates[-1] >= 0.15:
        flags.append({"level": "warning", "text": f"Attendance down from {max(rates[-4:]):.0%} to {rates[-1]:.0%}"})
    for key, what in (("principal", "Loan repayments"), ("savings", "Savings")):
        v = [m[key] for m in series[-4:]]
        if len(v) >= 4 and all(b < a for a, b in zip(v, v[1:])):
            flags.append({"level": "warning", "text": f"{what} fell 3 months in a row"})
    if cur["cash"] is not None and abs(cur["cash"] - cur["ledger_cash"]) > 1:
        flags.append({"level": "critical", "text": f"Mother-book cash differs from the ledger by Rs {abs(cur['cash'] - cur['ledger_cash']):,.0f}"})
    return flags


def create_app(data_dir: Path | str | None = None, workbook: Path | str | None = None,
               reader: Any = None, offline: Optional[bool] = None) -> FastAPI:
    data = Path(data_dir or os.environ.get("SHG_DATA_DIR") or ROOT / "data")
    wb_path = Path(workbook or os.environ.get("SHG_WORKBOOK") or data / "gn_workbook.xlsx")
    if not wb_path.exists():
        seed_workbook(wb_path)
    samples = SampleIndex(SYN)
    if offline is None:
        offline = reader is None and not os.environ.get("ANTHROPIC_API_KEY")
    if reader is None:
        if offline:
            reader = DemoReader(T, samples)
        else:
            from .extraction import ClaudeReader
            reader = ClaudeReader()
    pipeline = Pipeline(Store(data), wb_path, reader, T)
    seen = SeenMessages(data)

    app = FastAPI(title="SHG report digitiser — Palmera")
    app.state.pipeline, app.state.data, app.state.workbook = pipeline, data, wb_path
    # No CORS middleware: the dashboard is served from the same origin (Vite proxies /api in dev).

    @app.exception_handler(StateError)
    def _state_error(request: Request, e: StateError):
        return JSONResponse({"detail": str(e)}, status_code=409)

    @app.exception_handler(NotFound)
    def _not_found(request: Request, e: NotFound):
        return JSONResponse({"detail": str(e)}, status_code=404)

    # ------------------------------------------------------------ helpers
    def load(sid: str) -> Submission:
        return pipeline.store.load(sid)          # NotFound -> 404 (also for malformed ids)

    def view(s: Submission) -> dict:
        d = json.loads(s.model_dump_json())
        r = s.record
        if r:
            d["monthly"] = to_monthly(r, T)       # exactly what would be written
            d["labels"] = {fid: T.field_label(fid) for fid in r.fields}
            d["short_labels"] = {fid: short_label(T, fid) for fid in r.fields}
        else:
            d["monthly"], d["labels"], d["short_labels"] = None, {}, {}
        if d.get("validation") is not None:
            d["validation"].setdefault("likely", [])
        d["corrections"] = pipeline.corrections(s)
        d["actions"] = pipeline.actions(s)
        return d

    def summary_row(s: Submission) -> dict:
        r, v = s.record, s.validation
        likely = getattr(v, "likely", None) or []
        return {
            "id": s.id, "created": s.created, "updated": s.updated, "status": s.status, "sender": s.sender,
            "lang": s.lang, "shg": r.get("header.shg_name") if r else None,
            "shg_tab": s.shg_tab, "gn": r.get("header.village_gn") if r else None,
            "month": r.get("header.month_year") if r else None,
            "errors": len(v.errors) if v else 0,
            "warnings": len([i for i in v.issues if i.severity == "warning"]) if v else 0,
            "likely_field": likely[0].field if likely else None,
            "pages": sorted(s.pages), "superseded_by": s.superseded_by,
            "failure": s.failure if s.status == Status.failed else None,
            "write_error": s.write_error, "corrections": len(s.overrides),
            "rejected_reason": s.rejected_reason if s.status == Status.rejected else None,
        }

    def deliver(sender: str, reply: Optional[str]) -> dict:
        """Send a bot message to a real member over WhatsApp. Never raises: the state change
        is already saved, so a failed send is reported, not retried by the client."""
        if reply is None:
            return {"delivered": False}
        if sender.startswith("sim:"):
            return {"delivered": True, "channel": "simulator"}
        if not whatsapp.configured():
            return {"delivered": False, "delivery_error": "WhatsApp is not configured (WHATSAPP_TOKEN, WHATSAPP_PHONE_ID)."}
        try:
            whatsapp.send_text(sender, str(reply))
            return {"delivered": True, "channel": "whatsapp"}
        except Exception as e:
            log.warning("WhatsApp send failed: %s", e)
            return {"delivered": False, "delivery_error": f"WhatsApp send failed: {e}"}

    def action_result(sid: str, reply: Optional[str]) -> dict:
        """The officer action's result; the WhatsApp send happens outside the lock."""
        with lock:
            s = load(sid)
            v = view(s)
        return {"reply": None if reply is None else str(reply), "reply_en": getattr(reply, "en", None),
                **deliver(s.sender, reply), "submission": v}

    def handle_image(sender: str, data: bytes, lang: Optional[str], filename: Optional[str] = None):
        try:
            img = decode_image(data)
        except BadImage as e:
            log.info("bad image from sender: %s", e)
            return pipeline.on_other(sender, "unreadable photo", "bad_image")
        source = samples.match(data)                # exact sample bytes: the demo reader may read it
        shown = source or (filename if filename in samples.names() else None)
        return pipeline.on_image(sender, img, lang=lang, image_name=shown, source=source)

    def sim_enabled() -> None:
        if os.environ.get("SHG_DISABLE_SIMULATOR") == "1":
            raise HTTPException(404, "the simulator is disabled")

    def sim_sender(sender: str) -> str:
        sender = (sender or "").strip()
        sender = sender if sender.startswith("sim:") else f"sim:{sender}"
        if not SENDER_RE.fullmatch(sender):
            raise HTTPException(400, "sender must be 1-44 letters, digits or _.:+-")
        return sender

    # ------------------------------------------------------------ dashboard
    @app.get("/api/status")
    def status() -> dict:
        return {"mode": "offline-demo" if offline else "claude", "workbook": str(wb_path), "template": T.id,
                "whatsapp": whatsapp.configured(), "webhook_signed": whatsapp.signature_required(),
                "simulator": os.environ.get("SHG_DISABLE_SIMULATOR") != "1"}

    @app.get("/api/template")
    def template() -> dict:
        """Form structure for the dashboard: table rows, shaded cells, how months are built."""
        return {
            "id": T.id,
            "header": [{"key": f.key, "label": f.label} for f in T.header],
            "weekly": [{"key": r.key, "label": r.label, "row": r.row, "columns": r.columns, "kind": r.kind,
                        "type": r.type, "section": next((T.sections[k] for k in sorted(T.sections, reverse=True) if k < r.row), None)}
                       for r in T.weekly],
            "page2": [{"key": f.key, "label": f.label, "type": f.type,
                       "columns": [c["key"] for c in f.columns], "max_rows": f.max_rows} for f in T.page2],
            "monthly": T.workbook["monthly_rows"],
            "summary_items": [{"item": i, "label": k, "short": s} for i, (k, s) in enumerate(M.SUMMARY_ITEMS, 1)],
        }

    @app.get("/api/reject-reasons")
    def reject_reasons() -> list[dict]:
        return [{"code": c, "en": v["en"] or "Other (no reason given to the member)"} for c, v in M.REJECT_REASONS.items()]

    @app.get("/api/submissions")
    def list_submissions() -> list[dict]:
        with lock:
            return [summary_row(s) for s in pipeline.store.all()]

    @app.get("/api/submissions/{sid}")
    def get_submission(sid: str) -> dict:
        with lock:
            return view(load(sid))

    @app.get("/api/submissions/{sid}/crops/{field_id}")
    def crop(sid: str, field_id: str):
        if not FIELD_RE.fullmatch(field_id) or ".." in field_id:
            raise HTTPException(404)
        p = pipeline.store.dir(sid) / "crops" / f"{field_id}.jpg"
        if not p.is_file():
            raise HTTPException(404)
        return Response(p.read_bytes(), media_type="image/jpeg")

    @app.get("/api/submissions/{sid}/pages/{page}")
    def page_image(sid: str, page: int):
        with lock:
            name = load(sid).pages.get(page)
        if not name:
            raise HTTPException(404)
        return Response((pipeline.store.dir(sid) / name).read_bytes(), media_type="image/jpeg")

    @app.post("/api/submissions/{sid}/fields/{field_id}")
    def set_field(sid: str, field_id: str, body: FieldUpdate) -> dict:
        with lock:
            s = load(sid)
            try:
                pipeline.officer_set(s, field_id, body.value, _officer(body.officer))
            except ValueError as e:
                raise HTTPException(400, str(e))
            return view(s)

    @app.post("/api/submissions/{sid}/overrides")
    def decide_override(sid: str, body: OverrideDecision) -> dict:
        with lock:
            s = load(sid)
            pipeline.officer_override(s, body.label, body.accept, _officer(body.officer))
            return view(s)

    @app.post("/api/submissions/{sid}/approve")
    def approve(sid: str, body: Approve) -> dict:
        with lock:
            s = load(sid)
            try:
                reply = pipeline.officer_approve(s, _officer(body.officer), body.force, body.reason, body.overwrite)
            except ValueError as e:
                raise HTTPException(400, str(e))
        return action_result(sid, reply)

    @app.post("/api/submissions/{sid}/reject")
    def reject(sid: str, body: Reject) -> dict:
        with lock:
            s = load(sid)
            reply = pipeline.officer_reject(s, _officer(body.officer), body.reason, body.note)
        return action_result(sid, reply)

    @app.post("/api/submissions/{sid}/retry")
    def retry(sid: str, body: Optional[Officer] = None) -> dict:
        reply = pipeline.retry(sid, _officer(body.officer if body else ""))
        return action_result(sid, reply)

    @app.post("/api/submissions/{sid}/process-now")
    def process_now(sid: str, body: Optional[Officer] = None) -> dict:
        reply = pipeline.process_now(sid, _officer(body.officer if body else ""))
        return action_result(sid, reply)

    @app.post("/api/submissions/{sid}/new-group")
    def new_group(sid: str, body: Optional[Officer] = None) -> dict:
        with lock:
            s = load(sid)
            pipeline.confirm_new_group(s, _officer(body.officer if body else ""))
            return view(s)

    @app.get("/api/shg-tabs")
    def shg_tabs() -> list[str]:
        with lock:
            return GNWorkbook(wb_path, T).shg_tabs()

    @app.get("/api/groups")
    def groups() -> list[dict]:
        from datetime import date
        today = date.today()
        last = f"{today.year - (today.month == 1):04d}-{(today.month - 2) % 12 + 1:02d}"
        with lock:
            wb = GNWorkbook(wb_path, T)
            subs = pipeline.store.all()
        open_subs: dict[str, list] = {}
        for s in subs:
            if s.status in (Status.needs_review, Status.awaiting_member) and s.record:
                key = s.shg_tab or s.record.get("header.shg_name")
                open_subs.setdefault(key, []).append({"id": s.id, "status": s.status})
        out = []
        for tab in wb.shg_tabs():
            try:
                ser = wb.series(tab)
                flags = _flags(ser, last)
            except (WorkbookError, ValueError) as e:      # one damaged tab mustn't hide the others
                ser, flags = [], [{"level": "critical", "text": f"Can't read this tab: {e}"}]
            out.append({"name": tab, "gn": wb.gn_of(tab), "series": ser, "flags": flags,
                        "open_submissions": open_subs.get(tab, [])})
        return out

    @app.post("/api/demo/reset")
    def demo_reset() -> dict:
        """Start the demo over: re-seed the workbook FIRST (atomically), then empty the
        inbox, the conversations and the language choices."""
        if not (offline or os.environ.get("SHG_ALLOW_RESET") == "1"):
            raise HTTPException(403, "reset is only available in demo mode")
        with lock:
            try:
                seed_workbook(wb_path)
            except PermissionError:
                raise HTTPException(409, f"Close {wb_path.name} in Excel and try again.")
            except Exception as e:
                log.exception("re-seeding failed")
                raise HTTPException(500, f"Couldn't re-create the demo workbook ({e}); nothing was cleared.")
            subs = data / "submissions"
            trash = data / f".trash-{uuid.uuid4().hex[:8]}"
            try:
                subs.rename(trash)
            except OSError:
                trash = subs
            shutil.rmtree(trash, ignore_errors=True)
            subs.mkdir(parents=True, exist_ok=True)
            pipeline.conversations.clear()
            (data / "languages.json").unlink(missing_ok=True)
        return {"ok": True}

    @app.get("/api/workbook")
    def download_workbook():
        with lock:
            content = wb_path.read_bytes()
        return Response(content, headers={"Content-Disposition": f'attachment; filename="{wb_path.name}"'},
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ------------------------------------------------------------ WhatsApp simulator
    @app.post("/api/sim/message")
    def sim_message(sender: str = Form(...), lang: Optional[str] = Form(None), text: Optional[str] = Form(None),
                    image: Optional[UploadFile] = File(None)) -> dict:
        """A plain def: FastAPI runs it in the thread pool, so reading a report doesn't block
        the server."""
        sim_enabled()
        sender = sim_sender(sender)
        if lang is not None and lang not in M.LANGS:
            raise HTTPException(400, "lang must be en, si or ta")
        if image is not None:
            data_ = image.file.read(MAX_UPLOAD + 1)
            if not data_:
                raise HTTPException(400, "The upload is empty.")
            sub, reply = handle_image(sender, data_, lang, image.filename)
        elif text and text.strip():
            sub, reply = pipeline.on_text(sender, text, lang=lang)
        else:
            raise HTTPException(400, "send text or image")
        if sub is not None:
            with lock:
                sub = load(sub.id)
        return {"reply": str(reply), "reply_en": getattr(reply, "en", None),
                "submission_id": sub.id if sub else None, "status": sub.status if sub else None}

    @app.get("/api/sim/conversation")
    def sim_conversation(sender: str = Query(...)) -> dict:
        sim_enabled()
        sender = sim_sender(sender)
        with lock:
            conv = pipeline.conversations.load(sender)
            mine = pipeline.store.for_sender(sender)
        latest = {"id": mine[0].id, "status": mine[0].status} if mine else None
        return {"sender": sender, "lang": conv.lang, "messages": conv.messages, "latest": latest}

    @app.get("/api/sim/samples")
    def sample_list() -> list[str]:
        sim_enabled()
        return samples.names()

    @app.get("/api/sim/samples/{name}")
    def sample(name: str):
        sim_enabled()
        if name not in samples.names():           # only the listed files: no paths
            raise HTTPException(404)
        return FileResponse(SYN / name, media_type="image/jpeg")

    # ------------------------------------------------------------ real WhatsApp webhook
    @app.get("/webhook/whatsapp")
    def wa_verify(request: Request):
        challenge = whatsapp.verify(dict(request.query_params))
        if challenge is None:
            raise HTTPException(403)
        return PlainTextResponse(challenge)

    def wa_process(m: dict) -> None:
        sender = m["sender"]
        try:
            if m["type"] == "image":
                try:
                    data_ = whatsapp.download_media(m["media_id"])
                except Exception as e:
                    log.warning("media download failed: %s", e)
                    _, reply = pipeline.on_other(sender, "photo (download failed)", "send_again")
                else:
                    _, reply = handle_image(sender, data_, None)
            elif m["type"] == "text":
                _, reply = pipeline.on_text(sender, m["text"])
            else:
                _, reply = pipeline.on_other(sender, m.get("kind") or "unsupported")
        except Exception:
            log.exception("WhatsApp message failed")
            reply = M.msg("error_fallback", pipeline.conversations.load(sender).lang)
        deliver(sender, reply)

    @app.post("/webhook/whatsapp")
    async def wa_incoming(request: Request, background: BackgroundTasks):
        body = await request.body()
        if not whatsapp.signature_ok(body, request.headers.get("X-Hub-Signature-256")):
            raise HTTPException(401, "bad or missing X-Hub-Signature-256")
        try:
            payload = json.loads(body)
        except ValueError:
            return JSONResponse({"ok": False, "detail": "body is not JSON"}, status_code=400)
        msgs = whatsapp.parse_incoming(payload)
        fresh = []
        for m in msgs:                              # Meta re-delivers; handle each message once
            if await run_in_threadpool(seen.first_time, m.get("id")):
                fresh.append(m)
        for m in fresh:
            background.add_task(wa_process, m)      # answer Meta fast; do the work after
        return {"ok": True, "received": len(msgs), "duplicates": len(msgs) - len(fresh)}

    # ------------------------------------------------------------ the dashboard (built React app)
    if (DIST / "assets").exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "webhook/", "docs", "openapi")):
            raise HTTPException(404)
        root = DIST.resolve()
        if path:
            try:
                f = (DIST / path).resolve()
            except (OSError, ValueError):
                raise HTTPException(404)
            if f.is_relative_to(root) and f.is_file():   # never anything outside frontend/dist
                return FileResponse(f)
        index = DIST / "index.html"
        if not index.exists():
            return PlainTextResponse("Dashboard not built. Run: cd frontend && npm install && npm run build", 404)
        return FileResponse(index)

    return app


app = create_app()
pipeline = app.state.pipeline
