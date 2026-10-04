"""Core records passed between pipeline stages."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, Field


class Legibility(str, Enum):
    clear = "clear"
    unclear = "unclear"        # model could read it but isn't sure
    illegible = "illegible"    # something is written but can't be read
    blank = "blank"            # nothing written


class FieldStatus(str, Enum):
    auto = "auto"              # passed every check, accepted automatically
    needs_review = "needs_review"
    officer_confirmed = "officer_confirmed"
    officer_corrected = "officer_corrected"
    member_confirmed = "member_confirmed"
    member_corrected = "member_corrected"


class Box(BaseModel):
    """Where a value sits on the photo, normalised 0..1 (x0, y0, x1, y1)."""
    page: int = 1
    x0: float
    y0: float
    x1: float
    y1: float


class FieldValue(BaseModel):
    value: Any = None                          # normalised value
    raw: Optional[str] = None                  # text as read from the paper
    legibility: Legibility = Legibility.blank
    passes: list[Any] = Field(default_factory=list)   # normalised value from each extraction pass
    box: Optional[Box] = None                  # audit trail: where it came from
    status: FieldStatus = FieldStatus.auto
    history: list[dict[str, Any]] = Field(default_factory=list)  # who changed what, when

    @property
    def is_blank(self) -> bool:
        return self.value is None


class Severity(str, Enum):
    error = "error"            # blocks auto-acceptance; officer must look
    warning = "warning"        # accepted, but shown to the officer
    info = "info"


class Category(str, Enum):
    capture = "capture"        # extraction passes disagree / unreadable
    arithmetic = "arithmetic"  # numbers on the form don't add up
    continuity = "continuity"  # doesn't follow on from last month
    range = "range"            # outside allowed range
    completeness = "completeness"
    finding = "finding"        # a real issue for the SHG (e.g. cash short), not a reading problem


class Issue(BaseModel):
    rule: str
    severity: Severity
    category: Category
    message: str
    fields: list[str] = Field(default_factory=list)    # EVERY cell the check depends on
    expected: Any = None
    found: Any = None
    # For a sum that doesn't balance: the value each listed cell would need for this
    # check to balance on its own (only when that value is possible, i.e. >= 0).
    suggest: dict[str, Union[int, float]] = Field(default_factory=dict)
    label: Optional[str] = None                       # member_correction: the summary item it is about


class FormRecord(BaseModel):
    template_id: str
    fields: dict[str, FieldValue] = Field(default_factory=dict)
    image_ids: list[str] = Field(default_factory=list)

    def get(self, field_id: str) -> Any:
        fv = self.fields.get(field_id)
        return None if fv is None else fv.value

    def number(self, field_id: str) -> Optional[float]:
        """Numeric value, or None when the cell is blank or holds something that isn't a
        number (an unreadable cell is flagged by validation; it must never crash a sum)."""
        v = self.get(field_id)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return float(v)

    def num(self, field_id: str) -> float:
        """Numeric value, blank treated as 0 (the form leaves zero cells empty)."""
        v = self.number(field_id)
        return 0.0 if v is None else v

    def set(self, field_id: str, value: Any, **kw: Any) -> None:
        fv = self.fields.get(field_id) or FieldValue()
        fv.value = value
        for k, v in kw.items():
            setattr(fv, k, v)
        self.fields[field_id] = fv


class PriorMonth(BaseModel):
    """Month-end balances already in the workbook for the previous month."""
    month: Optional[str] = None                # YYYY-MM
    cash_in_hand: Optional[float] = None       # mother book
    savings_to_date: Optional[float] = None
    loans_outstanding: Optional[float] = None
    savings_refunded_to_date: Optional[float] = None   # lets us accept savings-to-date kept net of refunds
    members: Optional[int] = None
    # True when the month being submitted already has figures in the workbook
    # (set from GNWorkbook.month_recorded); validation then blocks the report.
    this_month_recorded: bool = False
    # "workbook" (last month's column) or "opening" (a new group's opening totals, built by
    # validation.prior_from_opening). Only changes how the week-1 checks word their messages.
    source: str = "workbook"
    # A new group the officer says started this month (opening totals all zero): validation
    # then checks the form's own to-date figures agree (opening_inconsistent).
    started_this_month: bool = False


# ---------------------------------------------------------------------------
# Normalisation of what was read off the paper
# ---------------------------------------------------------------------------
_YES = {"yes", "y", "ok", "held", "✓", "✔", "ඔව්", "ඔව", "ஆம்", "ஆம", "true"}
_NO = {"no", "n", "not held", "x", "✗", "✘", "නැත", "නෑ", "இல்லை", "false"}
# "1"/"0" and "-" are deliberately not yes/no: a count or a dash in the meeting row is
# ambiguous, so it goes to the officer instead of being guessed.
_BLANKS = {"", "-", "—", "–", "nil", "n/a", "na"}
_CURRENCY = re.compile(r"(rs\.?|රු\.?|ரூ\.?|lkr)")
_SUFFIX = re.compile(r"(/\s*[-=]+|[-=]+\s*/?)\s*$")        # "/-", "/=", "=", "-" after an amount
# 1500 | 1,500 | 1,50,000 (lakh grouping) | 1,234,567 ; optional decimals
_NUMBER = re.compile(r"-?(\d+|\d{1,3}(,\d{2,3})*,\d{3})(\.\d+)?")


def _ascii_digits(s: str) -> str:
    """Sinhala / Tamil digits (rare, but legal) -> 0-9."""
    return "".join(str(unicodedata.decimal(ch)) if not ch.isascii() and unicodedata.decimal(ch, None) is not None
                   else ch for ch in s)


def parse_number(value: Any, ftype: str = "money") -> Optional[float | int]:
    """A handwritten amount or count -> number. Raises ValueError for anything that
    isn't clearly ONE number, so the cell goes to an officer rather than being guessed:
    "300 310" (a crossed-out value next to its replacement), "1.2" as a count, "12.000"."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"not a number: {value!r}")
    if isinstance(value, (int, float)):
        n = float(value)
    else:
        s = _ascii_digits(str(value).strip().lower())
        if s in _BLANKS:
            return None
        s = _CURRENCY.sub("", s).strip()
        if s != "-":
            s = _SUFFIX.sub("", s).strip()
        if s in _BLANKS:
            return None
        if re.search(r"\d\s+[\d,.]|[\d,.]\s+\d", s):
            raise ValueError(f"more than one number: {value!r}")
        s = s.replace(" ", "")
        if not _NUMBER.fullmatch(s):
            raise ValueError(f"not a number: {value!r}")
        if "." in s and len(s.split(".")[1]) > 2:
            raise ValueError(f"not a clear amount: {value!r}")
        n = float(s.replace(",", ""))
    if ftype == "int":
        if not n.is_integer():
            raise ValueError(f"not a whole number: {value!r}")
        return int(n)
    return int(n) if n.is_integer() else round(n, 2)


def normalise(value: Any, ftype: str) -> Any:
    if value is None:
        return None
    if ftype in ("money", "int"):
        return parse_number(value, ftype)
    if ftype == "yesno":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in _YES:
            return True
        if s in _NO:
            return False
        if s in _BLANKS:
            return None
        raise ValueError(f"not yes/no: {value!r}")
    if ftype == "month":
        return normalise_month(value)
    if ftype == "date":
        return str(value).strip() or None
    s = str(value).strip()
    return s or None


MIN_YEAR, MAX_YEAR = 2000, 2100
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def normalise_month(value: Any) -> Optional[str]:
    """'05/2026', '5-26', 'May 2026', '2026-05' -> '2026-05'."""
    if value is None:
        return None
    if isinstance(value, date):
        if not MIN_YEAR <= value.year <= MAX_YEAR:
            raise ValueError(f"not a plausible year: {value!r}")
        return f"{value.year:04d}-{value.month:02d}"
    s = str(value).strip().lower()
    if not s:
        return None
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})", s)
    if m:
        y, mo = int(m[1]), int(m[2])
    else:
        m = re.fullmatch(r"(\d{1,2})\s*[-/.]\s*(\d{2}|\d{4})", s)
        if m:
            mo, y = int(m[1]), int(m[2])
        else:
            m = re.fullmatch(r"([a-z]{3})[a-z]*[\s\-/.,]*(\d{2}|\d{4})", s)
            if not m or m[1] not in _MONTHS:
                raise ValueError(f"not a month: {value!r}")
            mo, y = _MONTHS[m[1]], int(m[2])
    if y < 100:
        y += 2000
    if not 1 <= mo <= 12:
        raise ValueError(f"not a month: {value!r}")
    if not MIN_YEAR <= y <= MAX_YEAR:          # '10/1926', '10/3026': a misread year, never a column
        raise ValueError(f"not a plausible year: {value!r}")
    return f"{y:04d}-{mo:02d}"
