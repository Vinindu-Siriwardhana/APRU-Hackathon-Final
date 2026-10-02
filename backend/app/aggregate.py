"""Roll the weekly paper form up into the monthly rows of Palmera's workbook."""
from __future__ import annotations

from typing import Any, Optional

from .models import FormRecord
from .schema import WEEKS, Template, load_template


def _weeks(rec: FormRecord, key: str) -> list[Any]:
    return [rec.get(f"weekly.{key}.{wk}") for wk in WEEKS]


def _tidy(n: Optional[float]) -> Optional[float]:
    """Whole numbers as int (what Palmera types), cents kept otherwise."""
    if n is None:
        return None
    return int(n) if float(n).is_integer() else round(n, 2)


def week_has_activity(rec: FormRecord, t: Template, wk: str) -> bool:
    """A week the group actually ran: a meeting marked yes, attendance, or any amount.
    A lone 'No' in the meeting row is not activity (nothing happened that week)."""
    for r in t.weekly:
        if not r.weeks:
            continue
        v = rec.get(r.field_id(wk))
        if v is None:
            continue
        if r.type == "yesno" and v is not True:
            continue                        # 'No' alone: no meeting, nothing moved
        if r.key == "attendance" and v == 0:
            continue
        return True
    return False


def last_active_week(rec: FormRecord, t: Template | None = None) -> Optional[str]:
    """The last week of the month with any activity; its cash in hand is month-end cash."""
    t = t or load_template(rec.template_id)
    return next((wk for wk in reversed(WEEKS) if week_has_activity(rec, t, wk)), None)


def monthly_value(rec: FormRecord, rule: str, field: str, t: Template | None = None) -> Optional[float]:
    if rule == "header":
        prefix = "page2" if field == "members_with_goals" else "header"
        return rec.get(f"{prefix}.{field}")
    vals = _weeks(rec, field)
    if rule == "count_yes":
        if all(v is None for v in vals):
            return None
        return sum(1 for v in vals if v is True)
    if rule == "sum":
        nums = [rec.number(f"weekly.{field}.{wk}") for wk in WEEKS]
        if all(v is None for v in nums):
            # nothing in the weeks: fall back on the Total cell (some groups only fill Total)
            return _tidy(rec.number(f"weekly.{field}.Total"))
        return _tidy(sum(v for v in nums if v is not None))
    if rule == "total":
        return _tidy(rec.number(f"weekly.{field}.Total"))
    if rule == "last_week":
        # Month-end balance = the LAST ACTIVE week's figure. If she left it blank the value
        # is missing (validation blocks with month_end_cash_missing); taking an earlier
        # week's figure would write a stale balance with no warning.
        wk = last_active_week(rec, t)
        return None if wk is None else _tidy(rec.number(f"weekly.{field}.{wk}"))
    if rule == "last_meeting":
        held = _weeks(rec, "meeting_held")
        for v, h in zip(reversed(vals), reversed(held)):
            if h and v is not None:
                return v
        return None
    raise ValueError(f"unknown aggregation rule {rule!r}")


def to_monthly(rec: FormRecord, t: Template, include_optional: bool = True) -> dict[str, Any]:
    """{workbook row label: value} for the month on this form. Blank months map to 0
    for flow rows so Palmera's 'all questions filled' completeness check passes.
    Month-end cash stays None when it's missing: it is never guessed."""
    out: dict[str, Any] = {}
    wb = t.workbook
    rows = list(wb["monthly_rows"]) + (list(wb.get("optional_rows", [])) if include_optional else [])
    for row in rows:
        v = monthly_value(rec, row["from"], row["field"], t)
        if v is None and row["from"] in ("sum", "count_yes", "total"):
            v = 0
        out[row["label"]] = v
    return out
