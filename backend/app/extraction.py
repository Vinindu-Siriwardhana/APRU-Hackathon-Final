"""Read the handwriting with Claude — twice, independently — and merge the readings.

Design rules
* The model TRANSCRIBES. It must not add up, correct or fill in anything: the ledger
  checks in validation.py only work if a wrong total on paper stays wrong in the data.
* Two passes see different views of the same paper (the whole flattened page vs. the
  rectified table at higher resolution) and run as separate requests, so one bad reading
  doesn't simply repeat itself.
* A third signal comes from the pixels: if a cell has ink but both passes say blank (or
  the reverse), that cell goes to the officer. This guards against invented values.
* Structured output guarantees the JSON shape. Rows are arrays with every field required
  (the API limits union/optional fields, so blanks are raw="" + legibility="blank").
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Optional, Protocol

import cv2
import numpy as np

from .imaging.layout import Alignment, FormLocator
from .models import Box, FieldValue, FormRecord, Legibility, normalise
from .schema import WEEKS, Template

DEFAULT_MODEL = os.environ.get("SHG_EXTRACTION_MODEL", "claude-opus-5-5")
LEGIBILITY = ["clear", "unclear", "illegible", "blank"]
MAX_TOKENS = 16000          # a full page 1 is ~6k tokens of JSON; stays under the SDK's non-streaming limit
# Per request. The SDK default is 10 minutes, and a report takes four sequential requests:
# a hung call would keep "Try again" out of the officer's reach for far too long.
READ_TIMEOUT = float(os.environ.get("SHG_READ_TIMEOUT", "120"))


class ExtractionError(Exception):
    """The page could not be read (API error, refusal, cut-off or malformed answer).
    The message is plain English: the officer sees it next to "Try again"."""


# --------------------------------------------------------------------------- schema
def _cell() -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["raw", "legibility"],
            "properties": {"raw": {"type": "string", "description": "Exactly what is written, character for character. Empty string if blank."},
                           "legibility": {"type": "string", "enum": LEGIBILITY}}}


def page1_schema(t: Template) -> dict:
    return {
        "type": "object", "additionalProperties": False, "required": ["header", "table"],
        "properties": {
            "header": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["key", "raw", "legibility"],
                "properties": {"key": {"type": "string", "enum": [f.key for f in t.header]},
                               "raw": {"type": "string"}, "legibility": {"type": "string", "enum": LEGIBILITY}}}},
            "table": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["key", "W1", "W2", "W3", "W4", "W5", "Total"],
                "properties": {"key": {"type": "string", "enum": [r.key for r in t.weekly]},
                               **{c: _cell() for c in WEEKS + ["Total"]}}}},
        }}


def page2_schema(t: Template) -> dict:
    simple = [f.key for f in t.page2 if f.type != "table"]
    return {
        "type": "object", "additionalProperties": False, "required": ["answers", "overdue_members", "issues"],
        "properties": {
            "answers": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["key", "raw", "legibility", "language", "english"],
                "properties": {"key": {"type": "string", "enum": simple}, "raw": {"type": "string"},
                               "legibility": {"type": "string", "enum": LEGIBILITY},
                               "language": {"type": "string", "enum": ["en", "si", "ta", "mixed", "none"]},
                               "english": {"type": "string", "description": "English translation of raw (same as raw if already English)."}}}},
            "overdue_members": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["name", "amount_left", "months_overdue", "last_meeting_attended"],
                "properties": {k: _cell() for k in ["name", "amount_left", "months_overdue", "last_meeting_attended"]}}},
            "issues": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["issue", "support_from_cluster"],
                "properties": {"issue": _cell(), "support_from_cluster": _cell()}}},
        }}


# --------------------------------------------------------------------------- prompts
RULES = """You are transcribing a handwritten monthly report from a women's Self-Help Group (SHG) in Sri Lanka.
Handwriting may be in English, Sinhala or Tamil; numbers are usually written with 0-9 digits.

Transcribe — do not interpret:
- Copy each cell exactly as written, including commas, "/-", "Rs", ticks or crosses. Do NOT convert, round, add up, or correct anything, even if a total looks wrong. Wrong arithmetic on the paper must stay wrong.
- If a cell is empty, raw="" and legibility="blank". Never fill an empty cell from other cells.
- legibility: "clear" = you are sure; "unclear" = you can read it but one or more characters could be something else; "illegible" = something is written but you cannot read it (put your best partial reading in raw).
- A crossed-out value with a replacement: transcribe the replacement and mark "unclear".
- Grey-shaded cells on the form are not used; return them as blank.
"""


def page1_prompt(t: Template) -> str:
    rows = "\n".join(f"- {r.key}: \"{r.label}\"" for r in t.weekly)
    hdr = "\n".join(f"- {f.key}: \"{f.label}\"" for f in t.header)
    return (RULES + "\nPage 1 has a header box and a weekly table with columns W1, W2, W3, W4, W5, Total.\n"
            f"Header fields:\n{hdr}\n\nTable rows (one entry per row, in this order; section headings like "
            f"'Financial Statement' are not rows):\n{rows}\n")


def page2_prompt(t: Template) -> str:
    simple = "\n".join(f"- {f.key}: \"{f.label}\"" for f in t.page2 if f.type != "table")
    return (RULES + "\nPage 2 has written answers and two small tables.\n"
            f"Answers (one entry each; for signature lines transcribe the printed/written name only):\n{simple}\n\n"
            "overdue_members: one entry per filled row of the 'Name / Amount left / Months overdue / Last meeting attended' table (skip empty rows).\n"
            "issues: one entry per filled row of the 'SHG Issues / Possible solutions' table (skip empty rows).\n"
            "For answers in Sinhala or Tamil, keep raw in the original script and give an English translation.\n")


# --------------------------------------------------------------------------- readers
class Reader(Protocol):
    def read(self, images: list[np.ndarray], prompt: str, schema: dict) -> dict: ...


def _jpeg_b64(img: np.ndarray, max_side: int = 1800) -> str:
    h, w = img.shape[:2]
    s = min(1.0, max_side / max(h, w))
    if s < 1:
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return base64.b64encode(buf.tobytes()).decode()


class ClaudeReader:
    def __init__(self, model: str = DEFAULT_MODEL, client: Any = None, timeout: float = READ_TIMEOUT):
        import anthropic
        self.timeout = timeout
        # one retry: two tries of `timeout` at most per request
        self.client = client or anthropic.Anthropic(timeout=timeout, max_retries=1)
        self.model = model

    def read(self, images: list[np.ndarray], prompt: str, schema: dict) -> dict:
        content: list[dict] = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                             "data": _jpeg_b64(im)}} for im in images]
        content.append({"type": "text", "text": prompt})
        try:
            resp = self.client.messages.create(
                model=self.model, max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": content}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
                timeout=self.timeout,
            )
        except Exception as e:                      # anthropic.APIError and friends, network errors
            if "Timeout" in type(e).__name__:
                raise ExtractionError(f"The reading service did not answer within {self.timeout:g} seconds. "
                                      "Try again in a few minutes.") from e
            raise ExtractionError(f"The reading service could not be reached ({type(e).__name__}: {e}).") from e
        stop = getattr(resp, "stop_reason", None)
        if stop == "refusal":
            raise ExtractionError("The reader declined to read this page.")
        if stop in ("max_tokens", "model_context_window_exceeded"):
            raise ExtractionError("The reading was cut off before it finished.")
        text = next((b.text for b in getattr(resp, "content", None) or []
                     if getattr(b, "type", None) == "text"), None)
        if not text:
            raise ExtractionError(f"The reader returned no answer (stop reason: {stop}).")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ExtractionError("The reader's answer was not valid JSON.") from e
        if not isinstance(data, dict):
            raise ExtractionError("The reader's answer had the wrong shape.")
        return data


# --------------------------------------------------------------------------- views
def page_view(al: Alignment, width: int = 1500) -> np.ndarray:
    """Whole page, flattened (perspective removed)."""
    h = int(width * 1.414)
    S = np.float64([[width, 0, 0], [0, h, 0], [0, 0, 1]])
    return cv2.warpPerspective(al.image, S @ np.linalg.inv(al.H), (width, h), borderValue=(255, 255, 255))


def table_views(loc: FormLocator, al: Alignment) -> list[np.ndarray]:
    """Pass B for page 1: header crop + the rectified table at full resolution."""
    ht = loc.L["header_table"]["quad_frac"]
    xs, ys = [p[0] for p in ht], [p[1] for p in ht]
    header = al.crop_box(al.page_box_to_photo([min(xs), min(ys), max(xs), max(ys)]), margin=0.01)
    return [header, al.grid.flat]


# --------------------------------------------------------------------------- merge
@dataclass
class PageReadings:
    page: int
    passes: list[dict]
    alignment: Alignment


def _cell_of(c: Any) -> tuple[str, str]:
    """(raw, legibility) from one returned cell, tolerating a malformed entry."""
    if not isinstance(c, dict):
        return "", "blank"
    raw = c.get("raw")
    leg = c.get("legibility")
    return ("" if raw is None else str(raw)), (leg if leg in LEGIBILITY else "unclear")


def _cells_page1(t: Template, data: dict) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    header_keys = {f.key for f in t.header}
    for h in data.get("header", []) or []:
        if isinstance(h, dict) and h.get("key") in header_keys:
            out[f"header.{h['key']}"] = _cell_of(h)
    weekly_keys = {r.key for r in t.weekly}
    for row in data.get("table", []) or []:
        if not isinstance(row, dict) or row.get("key") not in weekly_keys:
            continue
        r = t.weekly_row(row["key"])
        for col in r.columns:                     # shaded cells are ignored
            out[r.field_id(col)] = _cell_of(row.get(col))
    return out


def _cells_page2(t: Template, data: dict) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    out, english = {}, {}
    simple = {f.key for f in t.page2 if f.type != "table"}
    for a in data.get("answers", []) or []:
        if not isinstance(a, dict) or a.get("key") not in simple:
            continue
        out[f"page2.{a['key']}"] = _cell_of(a)
        if a.get("english") and a.get("language") not in ("en", "none"):
            english[f"page2.{a['key']}"] = a["english"]
    for table in ("overdue_members", "issues"):
        f = next(x for x in t.page2 if x.key == table)
        cols = {c["key"] for c in f.columns}
        for i, row in enumerate((data.get(table, []) or [])[: f.max_rows]):
            if not isinstance(row, dict):
                continue
            for col, c in row.items():
                if col in cols:
                    out[f"page2.{table}.{i}.{col}"] = _cell_of(c)
    return out, english


def _fillable_ids(t: Template, page: int) -> list[str]:
    """Every cell the officer may need to fill in, even when no reading returned it:
    all header fields and every non-shaded weekly cell (page 1), the answers (page 2)."""
    if page == 1:
        return [f"header.{f.key}" for f in t.header] + [r.field_id(c) for r in t.weekly for c in r.columns]
    return [f"page2.{f.key}" for f in t.page2 if f.type != "table"]


_RANK = {"clear": 0, "blank": 0, "unclear": 1, "illegible": 2}


def merge(t: Template, loc: FormLocator, pages: list[PageReadings], ink_threshold: float = 0.006) -> FormRecord:
    rec = FormRecord(template_id=t.id)
    for pr in pages:
        per_pass: list[dict[str, tuple[str, str]]] = []
        english: dict[str, str] = {}
        for data in pr.passes:
            if pr.page == 1:
                per_pass.append(_cells_page1(t, data))
            else:
                cells, eng = _cells_page2(t, data)
                per_pass.append(cells)
                english = english or eng
        ink = loc.weekly_ink(pr.alignment) if pr.page == 1 else {}
        ids = set().union(*[p.keys() for p in per_pass]) | set(ink) | set(_fillable_ids(t, pr.page))
        for fid in sorted(ids):
            ftype = t.field_type(fid)
            vals, raws, legs = [], [], []
            for p in per_pass:
                raw, leg = p.get(fid, ("", "blank"))
                raw = raw.strip()
                try:
                    v = normalise(raw, ftype) if raw else None
                except ValueError:
                    # Unreadable as this field's type ("2?00", "300 310"): no value, the raw text
                    # is kept for the officer, and the cell is marked illegible so it blocks.
                    v, leg = None, "illegible"
                vals.append(v); raws.append(raw); legs.append(leg if raw else "blank")
            worst = max(legs, key=lambda l: _RANK[l])
            fv = FieldValue(value=vals[0], raw=raws[0] or None, passes=vals,
                            legibility=Legibility(worst if any(raws) else "blank"))
            if fid in ink:
                has_ink = ink[fid] > ink_threshold
                if has_ink and all(v is None for v in vals):
                    fv.legibility = Legibility.unclear
                    fv.history.append({"event": "capture_check", "note": "ink in cell but both readings are blank"})
                elif not has_ink and any(v is not None for v in vals):
                    fv.legibility = Legibility.unclear
                    fv.history.append({"event": "capture_check", "note": "value read but the cell looks empty"})
            box = loc.field_box(pr.alignment, fid)
            if box:
                fv.box = Box(page=pr.page, x0=box[0], y0=box[1], x1=box[2], y1=box[3])
            if fid in english:
                fv.history.append({"event": "translation", "english": english[fid]})
            rec.fields[fid] = fv
    return rec


def extract(t: Template, loc: FormLocator, alignments: dict[int, Alignment], reader: Reader) -> FormRecord:
    """Run both passes on every page we have and merge them into one record."""
    if 1 not in alignments:
        raise ExtractionError("The form could not be found on the page 1 photo.")
    pages = []
    for page, al in sorted(alignments.items()):
        if page == 1:
            schema, prompt = page1_schema(t), page1_prompt(t)
            views = [[page_view(al)], table_views(loc, al)]
        else:
            schema, prompt = page2_schema(t), page2_prompt(t)
            views = [[page_view(al)], [al.image]]
        passes = []
        for v in views:
            try:
                passes.append(reader.read(v, prompt, schema))
            except ExtractionError:
                raise
            except Exception as e:                  # any reader (offline demo, tests) fails the same way
                raise ExtractionError(str(e) or type(e).__name__) from e
        pages.append(PageReadings(page=page, passes=passes, alignment=al))
    return merge(t, loc, pages)


# --------------------------------------------------------------------------- offline reader
class SimulatedReader:
    """Stands in for Claude when there is no API key (tests, offline demo). Returns the
    ground truth written on a synthetic form, with optional reading errors:
        errors = {"weekly.savings.W3": {"pass": 1, "raw": "8000"}}   # only pass B misreads
        errors = {"weekly.savings.W3": {"pass": "both", "raw": "8000"}}  # both agree, both wrong
    """

    def __init__(self, t: Template, truth: dict[str, Any], errors: Optional[dict[str, dict]] = None):
        self.t, self.truth, self.errors = t, truth, errors or {}
        self.calls = 0

    def _raw(self, fid: str, pass_idx: int) -> tuple[str, str]:
        err = self.errors.get(fid)
        if err and err.get("pass") in (pass_idx, "both"):
            return err["raw"], err.get("legibility", "clear")
        v = self.truth.get(fid)
        if v is None:
            return "", "blank"
        if isinstance(v, bool):
            return ("Yes" if v else "No"), "clear"
        if isinstance(v, str) and len(v) == 7 and v[4] == "-" and fid == "header.month_year":
            return f"{v[5:]}/{v[:4]}", "clear"
        return str(v), "clear"

    def read(self, images: list[np.ndarray], prompt: str, schema: dict) -> dict:
        idx = self.calls % 2
        self.calls += 1
        t = self.t
        if "table" in schema["properties"]:
            return {
                "header": [dict(key=f.key, **dict(zip(("raw", "legibility"), self._raw(f"header.{f.key}", idx))))
                           for f in t.header],
                "table": [{"key": r.key, **{c: dict(zip(("raw", "legibility"), self._raw(r.field_id(c), idx)))
                                            if c in r.columns else {"raw": "", "legibility": "blank"}
                                            for c in WEEKS + ["Total"]}} for r in t.weekly],
            }
        answers = []
        for f in t.page2:
            if f.type == "table":
                continue
            raw, leg = self._raw(f"page2.{f.key}", idx)
            answers.append({"key": f.key, "raw": raw, "legibility": leg, "language": "en" if raw else "none", "english": raw})
        tables = {}
        for key in ("overdue_members", "issues"):
            f = next(x for x in t.page2 if x.key == key)
            rows = []
            for i in range(f.max_rows):
                cells = {c["key"]: dict(zip(("raw", "legibility"), self._raw(f"page2.{key}.{i}.{c['key']}", idx)))
                         for c in f.columns}
                if any(c["raw"] for c in cells.values()):
                    rows.append(cells)
            tables[key] = rows
        return {"answers": answers, **tables}
