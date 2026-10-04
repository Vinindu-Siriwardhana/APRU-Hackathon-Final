"""Multi-layer validation of an extracted SHG monthly report.

Layers
1. capture      – the two extraction passes disagree, or the model says a cell is unclear
2. arithmetic   – the ledger on the form doesn't add up (row totals, loan-purpose split,
                  income/expense totals, expected balance, running balances)
3. continuity   – the month doesn't follow on from what's already in the workbook
4. range        – values outside Palmera's allowed ranges (from the Mapping sheet)
5. findings     – genuine issues for the group (cash short, overdue loans, high cash, …)

A confidently wrong number is worse than an unresolved one, so anything in layers 1–4
that fails marks the fields involved for officer review instead of guessing.

Every ledger check is written as a linear expression over form cells (`Lin`). That gives
two things for free:
* the issue lists EVERY cell the check depends on (so "checked against the photo" can only
  clear a check once the officer has looked at all of them), and
* for each of those cells, the value it would need for the check to balance (`suggest`).
`ValidationResult.likely` then ranks the cells most likely to be misread: "310 would make
3 checks balance".
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Optional, Union

from pydantic import BaseModel, Field, PrivateAttr

from .aggregate import _tidy, last_active_week, monthly_value
from .models import Category, FieldStatus, FieldValue, FormRecord, Issue, Legibility, PriorMonth, Severity
from .schema import WEEKS, Template

INCOME = ("savings", "principal_repaid", "interest_repaid", "other_income")
PURPOSES = ("loan_purpose_income", "loan_purpose_emergency", "loan_purpose_other")
CAPTURE_RULES = {"passes_disagree", "ink_mismatch", "unclear_handwriting", "not_a_number"}
# An officer looked at the cell on the photo (kept it, or typed a new value).
CHECKED = (FieldStatus.officer_confirmed, FieldStatus.officer_corrected)
KEPT = "Checked against the photo, kept as written: "
Number = Union[int, float]

# The nine "to date" totals Palmera's column C holds for a group's first month (exact
# workbook labels, as in the YAML's opening_rows).
SAVINGS_TD = "Total savings to date (Rs.)"
PRINCIPAL_TD = "Total Principal loan repayments to date (Rs.)"
INTEREST_TD = "Total Interest repayments to date (Rs.)"
OTHER_INC_TD = "Total Other income to date (Rs.)"
LOANS_TD = "Total Loans distributed to date (Rs.)"
REFUNDED_TD = "Total Savings refunded to date (Rs.)"
OTHER_EXP_TD = "Total Other expenses to date (Rs.)"
WRITE_OFF_TD = "Total Loan right off to date (Rs.)"
OUTSTANDING_TD = "Total Loans outstanding to date (Rs.)"
OPENING_LABELS = (SAVINGS_TD, PRINCIPAL_TD, INTEREST_TD, OTHER_INC_TD, LOANS_TD, REFUNDED_TD,
                  OTHER_EXP_TD, WRITE_OFF_TD, OUTSTANDING_TD)


class Likely(BaseModel):
    """One cell, ranked by how likely it is to be the misread behind the failing checks."""
    field: str
    checks: int                              # blocking issues that list this cell
    suggest: Optional[Number] = None         # a value those issues agree on
    balances: int = 0                        # how many of those issues that value clears
    also_clears: int = 0                     # warnings (e.g. cash_mismatch) that value clears too


class ValidationResult(BaseModel):
    issues: list[Issue] = Field(default_factory=list)
    flagged: dict[str, list[str]] = Field(default_factory=dict)   # field_id -> rules
    notes: dict[str, str] = Field(default_factory=dict)            # e.g. which expense definition matched
    likely: list[Likely] = Field(default_factory=list)             # most likely misread first
    # field -> number of ledger checks that include it AND balance (evidence it was read right)
    _support: dict[str, int] = PrivateAttr(default_factory=dict)
    _expense_seen: set[str] = PrivateAttr(default_factory=set)
    _expense_matched: bool = PrivateAttr(default=False)
    _today: Optional[str] = PrivateAttr(default=None)               # YYYY-MM the checks ran against

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == Severity.error]

    @property
    def auto_accept(self) -> bool:
        return not self.errors

    def add(self, issue: Issue) -> None:
        self.issues.append(issue)
        if issue.severity == Severity.error:
            for f in issue.fields:
                self.flagged.setdefault(f, []).append(issue.rule)


# --------------------------------------------------------------------------- helpers
def _num_text(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.2f}"


def _rs(x: float) -> str:
    """Rs 1,160 (cents only when there are any; minus sign in front)."""
    return f"-Rs {_num_text(-x)}" if x < 0 else f"Rs {_num_text(x)}"


def _month_name(ym: Optional[str]) -> str:
    try:
        y, m = map(int, str(ym).split("-"))
        return ["January", "February", "March", "April", "May", "June", "July", "August",
                "September", "October", "November", "December"][m - 1] + f" {y}"
    except (ValueError, IndexError):
        return str(ym)


def add_months(ym: str, n: int) -> str:
    y, m = map(int, ym.split("-"))
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _valid_ym(v: Any) -> Optional[str]:
    """A normalised YYYY-MM month, else None."""
    return v if isinstance(v, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v) else None


# --------------------------------------------------------------------------- opening totals
def _before(rec: FormRecord, balance: str, flows: dict[str, int], ambiguous: tuple[str, ...],
            tol: float = 1.0) -> Optional[Number]:
    """A balance BEFORE the month, from the form: a week's written balance minus the month's
    flows up to that week. Only weeks with no `ambiguous` flow so far count (a refund or
    write-off may or may not be in the written balance), and every such week must agree."""
    seen: list[float] = []
    run = amb = 0.0
    for wk in WEEKS:
        run += sum(sign * rec.num(f"weekly.{k}.{wk}") for k, sign in flows.items())
        amb += sum(abs(rec.num(f"weekly.{k}.{wk}")) for k in ambiguous)
        b = rec.number(f"weekly.{balance}.{wk}")
        if b is None or amb:
            continue
        seen.append(b - run)
    if not seen or max(seen) - min(seen) > tol or seen[0] < 0:
        return None
    return _tidy(seen[0])


def opening_suggestion(record: FormRecord, template: Any = None) -> dict[str, Optional[Number]]:
    """The nine opening "to date" totals BEFORE this month, where the form itself says them.
    Savings to date = a week's savings to date − the month's savings up to that week; loans
    outstanding likewise (+ distributed − principal − write-offs). Every other total (and any
    the form can't settle) is None: it has to come from the group's mother book."""
    out: dict[str, Optional[Number]] = {label: None for label in OPENING_LABELS}
    out[SAVINGS_TD] = _before(record, "savings_to_date", {"savings": 1}, ("savings_refunded",))
    out[OUTSTANDING_TD] = _before(record, "loans_outstanding",
                                  {"loans_distributed": 1, "principal_repaid": -1}, ("write_offs",))
    return out


def implied_opening_cash(opening: Optional[dict[str, Any]]) -> Optional[Number]:
    """The cash Palmera's formulas imply from the opening totals (its C20 formula without the
    month's own flows): savings + principal + interest + other income − loans distributed −
    savings refunded − other expenses, all to date. None when any of those is missing."""
    if not opening:
        return None
    vals = [opening.get(k) for k in (SAVINGS_TD, PRINCIPAL_TD, INTEREST_TD, OTHER_INC_TD,
                                     LOANS_TD, REFUNDED_TD, OTHER_EXP_TD)]
    if any(v is None or isinstance(v, bool) or not isinstance(v, (int, float)) for v in vals):
        return None
    s, p, i, o, l, r, x = (float(v) for v in vals)
    return _tidy(s + p + i + o - l - r - x)


def prior_from_opening(record: FormRecord, opening: Optional[dict[str, Any]],
                       started_this_month: bool = False) -> PriorMonth:
    """The 'last month' a new group's week-1 checks start from: its opening totals (zeros for
    a group that started this month), with the opening cash Palmera's formulas imply."""
    op = dict(opening or {})
    if started_this_month:
        op = {label: op.get(label) or 0 for label in OPENING_LABELS}
    try:
        month = add_months(str(_valid_ym(record.get("header.month_year"))), -1)
    except ValueError:
        month = None
    num = lambda k: float(op[k]) if isinstance(op.get(k), (int, float)) and not isinstance(op.get(k), bool) else None
    return PriorMonth(month=month, cash_in_hand=implied_opening_cash(op), savings_to_date=num(SAVINGS_TD),
                      savings_refunded_to_date=num(REFUNDED_TD), loans_outstanding=num(OUTSTANDING_TD),
                      members=None, source="opening", started_this_month=started_this_month)


def _key(issue: Issue) -> tuple[str, str]:
    """Identity of a check across re-runs: its rule and its first (anchor) cell."""
    return issue.rule, (issue.fields[0] if issue.fields else "")


def _unique(xs: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(xs))


@dataclass
class Lin:
    """sum(coef × cell) + const, over form cells. Blank cells count as 0."""
    terms: dict[str, float] = field(default_factory=dict)
    const: float = 0.0

    @staticmethod
    def cells(fids: Iterable[str]) -> "Lin":
        return Lin({f: 1.0 for f in fids})

    @staticmethod
    def of(x: Union["Lin", float, int]) -> "Lin":
        return x if isinstance(x, Lin) else Lin(const=float(x))

    def __add__(self, other: Union["Lin", float, int]) -> "Lin":
        o = Lin.of(other)
        terms = dict(self.terms)
        for f, c in o.terms.items():
            terms[f] = terms.get(f, 0.0) + c
        return Lin(terms, self.const + o.const)

    def __neg__(self) -> "Lin":
        return Lin({f: -c for f, c in self.terms.items()}, -self.const)

    def __sub__(self, other: Union["Lin", float, int]) -> "Lin":
        return self + (-Lin.of(other))

    def value(self, rec: FormRecord) -> float:
        return self.const + sum(c * rec.num(f) for f, c in self.terms.items())

    @property
    def fields(self) -> list[str]:
        return list(self.terms)


class _Blank:
    is_blank = True


_BLANK = _Blank()


# --------------------------------------------------------------------------- validator
class Validator:
    def __init__(self, template: Template, today: Optional[date] = None):
        self.t = template
        self.today = today                   # None: the real date (tests pin it)
        v = template.validation
        self.tol = float(v.get("money_tolerance", 1))
        self.expense_variants: list[list[str]] = v.get("total_expenses_variants", [])
        self._order = {f: i for i, f in enumerate(template.all_field_ids())}

    # ------------------------------------------------------------------ helpers
    def w(self, key: str, col: str) -> str:
        return f"weekly.{key}.{col}"

    def name(self, key: str) -> str:
        """Short row name for messages: 'Savings (Rs.)' -> 'Savings'."""
        return self.t.weekly_row(key).label.split(" (")[0]

    def ftype(self, fid: str) -> Optional[str]:
        try:
            return self.t.field_type(fid)
        except (KeyError, StopIteration, IndexError):
            return None

    def active_weeks(self, rec: FormRecord) -> list[str]:
        """Weeks with anything written in them."""
        out = []
        for wk in WEEKS:
            if any(not rec.fields.get(r.field_id(wk), _BLANK).is_blank
                   for r in self.t.weekly if r.weeks):
                out.append(wk)
        return out

    def filled(self, rec: FormRecord, ids: Iterable[str]) -> bool:
        return any(rec.get(i) is not None for i in ids)

    def eq(self, a: float, b: float) -> bool:
        return abs(a - b) <= self.tol

    def col_term(self, rec: FormRecord, key: str, col: str) -> Lin:
        """A row's figure in one column. In the Total column a blank Total cell means
        'not added up on paper', so the weeks are used instead (never a silent 0)."""
        if col != "Total":
            return Lin.cells([self.w(key, col)])
        if rec.get(self.w(key, "Total")) is not None or not self.t.weekly_row(key).weeks:
            return Lin.cells([self.w(key, "Total")])
        return Lin.cells(self.w(key, wk) for wk in WEEKS)

    def _suggest(self, rec: FormRecord, diff: Lin, residual: float) -> dict[str, Number]:
        """For each cell in a failing linear check: the value that makes it balance alone."""
        out: dict[str, Number] = {}
        for f, c in diff.terms.items():
            ftype = self.ftype(f)
            if c == 0 or ftype not in ("money", "int"):
                continue
            new = rec.num(f) - residual / c
            if new < 0:
                continue
            if abs(new - round(new)) < 1e-6:
                new = int(round(new))
            elif ftype == "int":
                continue
            else:
                new = round(new, 2)
            out[f] = new
        return out

    def _ledger(self, rec: FormRecord, res: ValidationResult, rule: str, diffs: list[Lin], message: str, *,
                fields: Iterable[str] = (), expected: object = None, found: object = None,
                severity: Severity = Severity.error, category: Category = Category.arithmetic) -> bool:
        """A ledger check: passes when any of `diffs` (alternative definitions the form
        allows, e.g. with or without write-offs) is 0 within tolerance. On failure the issue
        lists every cell any definition uses and suggests values from the first one."""
        vals = [d.value(rec) for d in diffs]
        for d, v in zip(diffs, vals):
            if abs(v) <= self.tol:
                for f in d.fields:
                    res._support[f] = res._support.get(f, 0) + 1
                return True
        res.add(Issue(rule=rule, severity=severity, category=category, message=message,
                      fields=_unique(list(fields) + [f for d in diffs for f in d.fields]),
                      expected=expected, found=found, suggest=self._suggest(rec, diffs[0], vals[0])))
        return False

    def _prior_is_last_month(self, rec: FormRecord, prior: Optional[PriorMonth]) -> bool:
        month = rec.get("header.month_year")
        if not prior or not prior.month or not month:
            return False
        try:
            return prior.month == add_months(str(month), -1)
        except ValueError:
            return False

    # ------------------------------------------------------------------ entry
    def validate(self, rec: FormRecord, prior: Optional[PriorMonth] = None,
                 today: Optional[date] = None) -> ValidationResult:
        res = self._check_all(rec, prior, _ym(today or self.today or date.today()))
        return self.finish(rec, res, prior, _base=res)

    def _check_all(self, rec: FormRecord, prior: Optional[PriorMonth],
                   today: Optional[str] = None) -> ValidationResult:
        res = ValidationResult()
        res._today = today or _ym(self.today or date.today())
        weeks = self.active_weeks(rec)
        self._capture(rec, res)
        self._required(rec, res)
        self._ranges(rec, res)
        self._structure(rec, res)
        self._row_totals(rec, res)
        for col in weeks + ["Total"]:
            self._loan_split(rec, res, col)
            self._income_total(rec, res, col)
            self._expense_total(rec, res, col)
        self._expense_definition(res)
        opening_ok = self._opening_consistency(rec, res, prior)
        self._running_balances(rec, res, weeks, prior if opening_ok else None)
        self._month_end_cash(rec, res)
        self._continuity(rec, res, prior)
        self._findings(rec, res, weeks)
        return res

    def finish(self, rec: FormRecord, res: ValidationResult, prior: Optional[PriorMonth] = None,
               _base: Optional[ValidationResult] = None) -> ValidationResult:
        """Rebuild `flagged` and `likely` from the issues as they stand. The pipeline calls
        this again after adding its own issues or downgrading checked-as-written ones."""
        res.flagged = {}
        for issue in res.errors:
            for f in issue.fields:
                res.flagged.setdefault(f, []).append(issue.rule)
        res.likely = self._rank(rec, res, prior, _base)
        return res

    # ------------------------------------------------------------------ layer 1
    def _show(self, fid: str, v: object) -> str:
        if v is None:
            return "blank"
        if isinstance(v, bool):
            return "Yes" if v else "No"
        if isinstance(v, (int, float)) and self.ftype(fid) == "money":
            return _rs(v)
        return str(v)

    def _capture(self, rec: FormRecord, res: ValidationResult) -> None:
        for fid, fv in rec.fields.items():
            if self.ftype(fid) in ("money", "int") and fv.value is not None and rec.number(fid) is None:
                res.add(Issue(rule="not_a_number", severity=Severity.error, category=Category.capture,
                              message=f"This should be a number, but it was read as '{fv.raw or fv.value}'.",
                              fields=[fid], found=fv.raw or str(fv.value)))
                continue
            distinct = {repr(p) for p in fv.passes}
            if len(fv.passes) >= 2 and len(distinct) > 1:
                res.add(Issue(
                    rule="passes_disagree", severity=Severity.error, category=Category.capture,
                    message=f"The two readings disagree ({' vs '.join(self._show(fid, p) for p in fv.passes)}).",
                    fields=[fid], found=fv.passes))
            elif any(h.get("event") == "capture_check" for h in fv.history):
                note = next(h["note"] for h in fv.history if h.get("event") == "capture_check")
                res.add(Issue(
                    rule="ink_mismatch", severity=Severity.error, category=Category.capture,
                    message=f"Check this cell: {note}.", fields=[fid], found=fv.raw))
            elif fv.legibility in (Legibility.unclear, Legibility.illegible):
                res.add(Issue(
                    rule="unclear_handwriting", severity=Severity.error, category=Category.capture,
                    message=f"The handwriting is {fv.legibility.value}"
                            + (f" (read as '{fv.raw}')" if fv.raw else "") + ".",
                    fields=[fid], found=fv.raw))

    def _required(self, rec: FormRecord, res: ValidationResult) -> None:
        for f in self.t.header:
            if f.required and rec.get(f"header.{f.key}") is None:
                res.add(Issue(rule="required_missing", severity=Severity.error,
                              category=Category.completeness,
                              message=f"'{f.label}' is empty.", fields=[f"header.{f.key}"]))

    # ------------------------------------------------------------------ layer 4
    def _caps(self) -> tuple[dict[str, float], Optional[float]]:
        v = self.t.validation
        caps = {"interest_repaid": v.get("max_interest"), "other_expenses": v.get("max_other_expenses")}
        return {k: c for k, c in caps.items() if c is not None}, v.get("max_money")

    def _ranges(self, rec: FormRecord, res: ValidationResult) -> None:
        caps, max_money = self._caps()
        for r in self.t.weekly:
            if r.type not in ("money", "int"):
                continue
            cap = caps.get(r.key) or (max_money if r.type == "money" and r.kind == "flow" else None)
            cell_over = False
            for col in r.columns:
                fid = r.field_id(col)
                x = rec.number(fid)
                if x is None:
                    continue
                if x < 0 and r.key != "expected_balance":
                    res.add(Issue(rule="negative_value", severity=Severity.error, category=Category.range,
                                  message=f"{self.name(r.key)} in {col} is negative ({x:g}).", fields=[fid], found=x))
                if cap is not None and x > cap:
                    cell_over = True
                    res.add(Issue(rule="above_max", severity=Severity.error, category=Category.range,
                                  message=f"{self.name(r.key)} in {col} is {_rs(x)}, above Palmera's maximum of {_rs(cap)}.",
                                  fields=[fid], expected=cap, found=x))
            # The figure written to the workbook is the month's sum: it must respect the cap too.
            if cap is not None and r.weeks and not cell_over:
                m = monthly_value(rec, "sum", r.key, self.t)
                if m is not None and m > cap:
                    res.add(Issue(rule="above_max", severity=Severity.error, category=Category.range,
                                  message=f"{self.name(r.key)} for the month adds up to {_rs(m)}, "
                                          f"above Palmera's maximum of {_rs(cap)}.",
                                  fields=[r.field_id(c) for c in r.columns], expected=cap, found=m))
        for f in self.t.header:
            fid = f"header.{f.key}"
            x = rec.number(fid) if f.type in ("int", "money") else None
            if x is not None and f.max is not None and x > f.max:
                res.add(Issue(rule="above_max", severity=Severity.error, category=Category.range,
                              message=f"{f.label} is {x:g}, above Palmera's maximum of {f.max:g}.",
                              fields=[fid], expected=f.max, found=x))
            if x is not None and f.min is not None and x < f.min:
                res.add(Issue(rule="negative_value", severity=Severity.error, category=Category.range,
                              message=f"{f.label} is {x:g}, below the minimum of {f.min:g}.",
                              fields=[fid], expected=f.min, found=x))

    def _structure(self, rec: FormRecord, res: ValidationResult) -> None:
        members = rec.number("header.total_members")
        flows = [r for r in self.t.weekly if r.weeks and r.type == "money" and r.kind != "balance"]
        balances = [r for r in self.t.weekly if r.weeks and r.kind == "balance"]
        for wk in WEEKS:
            held_id, att_id = self.w("meeting_held", wk), self.w("attendance", wk)
            held = rec.get(held_id)
            att = rec.number(att_id)
            if held is None:
                if (att or 0) > 0 or self.filled(rec, [r.field_id(wk) for r in flows]):
                    res.add(Issue(rule="meeting_flag_missing", severity=Severity.error,
                                  category=Category.completeness,
                                  message=f"{wk}: 'Was the SHG meeting held?' is blank, but the week has "
                                          "attendance or money entries. Check the photo: was there a meeting?",
                                  fields=[held_id]))
                elif self.filled(rec, [r.field_id(wk) for r in balances]):
                    res.add(Issue(rule="meeting_flag_missing", severity=Severity.warning,
                                  category=Category.completeness,
                                  message=f"{wk}: 'Was the SHG meeting held?' is blank (only balances are filled in).",
                                  fields=[held_id]))
            elif held is False and att:
                res.add(Issue(rule="attendance_without_meeting", severity=Severity.error,
                              category=Category.arithmetic,
                              message=f"{wk}: the meeting is marked as not held, but attendance is {att:g}.",
                              fields=[held_id, att_id]))
            if members is not None and att is not None and att > members:
                res.add(Issue(rule="attendance_above_members", severity=Severity.error,
                              category=Category.range,
                              message=f"{wk}: attendance is {att:g}, more than the {members:g} members.",
                              fields=[att_id, "header.total_members"],
                              expected=f"<= {members:g}", found=att))
        # Palmera's sheet only accepts attendance <= members x meetings (data validation on the row)
        att_m = monthly_value(rec, "sum", "attendance", self.t) or 0
        meetings = monthly_value(rec, "count_yes", "meeting_held", self.t) or 0
        if members is not None and att_m > members * meetings:
            res.add(Issue(rule="attendance_above_capacity", severity=Severity.error, category=Category.range,
                          message=f"Attendance for the month is {att_m:g}, but {members:g} members × {meetings} "
                                  f"meeting{'s' if meetings != 1 else ''} allows at most {members * meetings:g}. "
                                  "Palmera's sheet won't accept this: check the attendance and the yes/no row.",
                          fields=[self.w("attendance", c) for c in self.t.weekly_row("attendance").columns]
                                 + [self.w("meeting_held", wk) for wk in WEEKS] + ["header.total_members"],
                          expected=f"<= {members * meetings:g}", found=att_m))
        if members is not None:
            for fid, what in [(self.w("inactive_members", "Total"), "Inactive members"),
                              (self.w("members_loans_overdue", "Total"), "Members with overdue loans"),
                              ("page2.members_with_goals", "Members with written goals")]:
                x = rec.number(fid)
                if x is not None and x > members:
                    res.add(Issue(rule="count_above_members", severity=Severity.error, category=Category.range,
                                  message=f"{what} ({x:g}) is more than the {members:g} members.",
                                  fields=[fid, "header.total_members"], expected=f"<= {members:g}", found=x))

    # ------------------------------------------------------------------ layer 2
    def _row_totals(self, rec: FormRecord, res: ValidationResult) -> None:
        """The handwritten Total column must equal the weeks (flows) or the last week (balances)."""
        for r in self.t.weekly:
            if not (r.weeks and r.total) or r.type not in ("money", "int"):
                continue
            tot_id = r.field_id("Total")
            written = rec.number(tot_id)
            week_ids = [r.field_id(wk) for wk in WEEKS]
            if written is None or not self.filled(rec, week_ids):
                continue
            fmt = _rs if r.type == "money" else (lambda x: f"{x:g}")
            if r.kind in ("flow", "derived"):
                weeks = Lin.cells(week_ids)
                s = weeks.value(rec)
                self._ledger(rec, res, "row_total", [weeks - Lin.cells([tot_id])],
                             f"{self.name(r.key)}: the weeks add up to {fmt(s)}, but the Total says {fmt(written)}.",
                             expected=s, found=written)
            elif r.kind == "balance":
                last_id = next(i for i in reversed(week_ids) if rec.get(i) is not None)
                last = rec.num(last_id)
                self._ledger(rec, res, "balance_total", [Lin.cells([tot_id]) - Lin.cells([last_id])],
                             f"{self.name(r.key)}: the Total ({fmt(written)}) is not the last week's figure ({fmt(last)}).",
                             expected=last, found=written, severity=Severity.warning)

    def _col_name(self, col: str) -> str:
        return "Total column" if col == "Total" else col

    def _loan_split(self, rec: FormRecord, res: ValidationResult, col: str) -> None:
        parts = Lin()
        for p in PURPOSES:
            parts = parts + self.col_term(rec, p, col)
        dist = self.col_term(rec, "loans_distributed", col)
        if not self.filled(rec, parts.fields + dist.fields):
            return
        s, d = parts.value(rec), dist.value(rec)
        self._ledger(rec, res, "loan_purpose_split", [parts - dist],
                     f"{self._col_name(col)}: the loan purposes add up to {_rs(s)}, but loans distributed is {_rs(d)}.",
                     expected=d, found=s)

    def _income_total(self, rec: FormRecord, res: ValidationResult, col: str) -> None:
        tid = self.w("total_income", col)
        written = rec.number(tid)
        if written is None:
            return
        parts = Lin()
        for k in INCOME:
            parts = parts + self.col_term(rec, k, col)
        s = parts.value(rec)
        self._ledger(rec, res, "total_income", [parts - Lin.cells([tid])],
                     f"{self._col_name(col)}: savings + principal + interest + other income = {_rs(s)}, "
                     f"but Total Income says {_rs(written)}.", expected=s, found=written)

    def _expenses(self, rec: FormRecord, col: str, variant: list[str]) -> Lin:
        out = Lin()
        for k in variant:
            out = out + self.col_term(rec, k, col)
        return out

    def _expense_total(self, rec: FormRecord, res: ValidationResult, col: str) -> None:
        tid = self.w("total_expenses", col)
        written = rec.number(tid)
        if written is None or not self.expense_variants:
            return
        exps = [self._expenses(rec, col, v) for v in self.expense_variants]
        matched = [v for v, e in zip(self.expense_variants, exps) if self.eq(e.value(rec), written)]
        if matched:
            res._expense_matched = True
            if len(matched) == 1:          # only a week WITH write-offs tells the definitions apart
                res._expense_seen.add("+".join(matched[0]))
        base, with_wo = exps[0].value(rec), exps[-1].value(rec)
        self._ledger(rec, res, "total_expenses", [e - Lin.cells([tid]) for e in exps],
                     f"{self._col_name(col)}: loans + savings refunded + other expenses = {_rs(base)}"
                     + (f" ({_rs(with_wo)} with write-offs)" if with_wo != base else "")
                     + f", but Total Expenses says {_rs(written)}.", expected=base, found=written)

    def _expense_definition(self, res: ValidationResult) -> None:
        """Record which Total Expenses definition this group uses (see findings, issue 3)."""
        if len(res._expense_seen) == 1:
            res.notes["total_expenses_definition"] = next(iter(res._expense_seen))
        elif res._expense_seen:
            res.notes["total_expenses_definition"] = "mixed: " + " / ".join(sorted(res._expense_seen))
        elif res._expense_matched and self.expense_variants:
            res.notes["total_expenses_definition"] = "+".join(self.expense_variants[0])

    def _expense_order(self, rec: FormRecord, res: ValidationResult, wk: str) -> list[list[str]]:
        """Expense definitions for one week, most likely first: the one this week's own Total
        Expenses matches, else the group's usual one, else the first (no write-offs)."""
        variants = list(self.expense_variants) or [[]]
        written = rec.number(self.w("total_expenses", wk))
        if written is not None:
            for v in variants:
                if self.eq(self._expenses(rec, wk, v).value(rec), written):
                    return [v] + [x for x in variants if x is not v]
        usual = res.notes.get("total_expenses_definition")
        return sorted(variants, key=lambda v: "+".join(v) != usual)

    def _running_balances(self, rec: FormRecord, res: ValidationResult, weeks: list[str],
                          prior: Optional[PriorMonth]) -> None:
        """Week-to-week ledger: expected balance, cash in hand, savings to date, loans outstanding.
        Last month's balances are used only when they really are LAST month's."""
        use_prior = self._prior_is_last_month(rec, prior)
        last_wk = last_active_week(rec, self.t)

        prev_cash: Optional[Lin] = Lin(const=prior.cash_in_hand) if use_prior and prior.cash_in_hand is not None else None
        prev_sav: list[Lin] = []
        if use_prior and prior.savings_to_date is not None:
            prev_sav = [Lin(const=prior.savings_to_date)]
            if prior.savings_refunded_to_date:      # a group may keep savings to date net of refunds
                prev_sav.append(Lin(const=prior.savings_to_date - prior.savings_refunded_to_date))
        sav_net = False
        prev_out: Optional[Lin] = Lin(const=prior.loans_outstanding) if use_prior and prior.loans_outstanding is not None else None
        if prior is not None and prior.source == "opening":
            whose = "new group" if prior.started_this_month else "mother book"
            cash_src = f"opening cash ({'new group' if prior.started_this_month else 'from the mother-book totals'})"
            sav_src, out_src = f"opening savings to date ({whose})", f"opening loans outstanding ({whose})"
        else:
            cash_src, sav_src = "last month's closing cash", "last month's savings to date"
            out_src = "last month's loans outstanding"

        for wk in weeks:
            inc = Lin.cells(self.w(k, wk) for k in INCOME)
            variants = self._expense_order(rec, res, wk)
            exps = [Lin.cells(self.w(k, wk) for k in v) for v in variants]
            flow_ids = _unique([self.w(k, wk) for k in INCOME] + [self.w(k, wk) for v in variants for k in v])
            exp_id, cash_id = self.w("expected_balance", wk), self.w("cash_in_hand", wk)
            expected_written, cash = rec.number(exp_id), rec.number(cash_id)

            # Expected balance = last week's actual cash + this week's income − expenses
            if prev_cash is not None and expected_written is not None:
                calc = (prev_cash + inc - exps[0]).value(rec)
                self._ledger(
                    rec, res, "expected_balance",
                    [Lin.cells([exp_id]) - (prev_cash + inc - e) for e in exps],
                    f"{wk}: {cash_src} {_rs(prev_cash.value(rec))} + income {_rs(inc.value(rec))} − "
                    f"expenses {_rs(exps[0].value(rec))} = {_rs(calc)}, but Expected Balance says {_rs(expected_written)}.",
                    fields=[exp_id] + prev_cash.fields + flow_ids, expected=calc, found=expected_written)

            # Actual cash vs expected: usually a real shortfall or surplus for the group (a finding).
            # In the month's last week it is the cash written to the workbook, so it must be looked at.
            wo_lin = Lin.cells([self.w("write_offs", wk)])
            if expected_written is not None:
                refs = [Lin.cells([exp_id])]
                if "write_offs" in variants[0]:
                    # This week's Total Expenses counts write-offs, so Expected Balance is short by
                    # them, but a write-off is not cash leaving the box: cash = expected + write-offs.
                    refs.append(Lin.cells([exp_id]) + wo_lin)
            elif prev_cash is not None:
                refs = [prev_cash + inc - e for e in exps]
            else:
                refs = []
            if cash is not None and refs and any(self.eq(cash, r.value(rec)) for r in refs):
                for f in _unique([cash_id] + next(r for r in refs if self.eq(cash, r.value(rec))).fields):
                    res._support[f] = res._support.get(f, 0) + 1      # cash agrees: evidence both were read right
            elif cash is not None and refs:
                ref = refs[0].value(rec)
                diff = cash - ref
                how = f"{_rs(abs(diff))} {'more' if diff > 0 else 'less'} than"
                if wk == last_wk:
                    self._ledger(rec, res, "month_end_cash_mismatch", [Lin.cells([cash_id]) - r for r in refs],
                                 f"{wk}: cash in hand {_rs(cash)} is {how} the expected balance {_rs(ref)}. "
                                 "This is the month-end cash for the workbook: check both figures on the photo.",
                                 fields=[cash_id, exp_id], expected=ref, found=cash)
                else:
                    res.add(Issue(rule="cash_mismatch", severity=Severity.warning, category=Category.finding,
                                  message=f"{wk}: cash in hand {_rs(cash)} is {how} expected {_rs(ref)}.",
                                  fields=[cash_id, exp_id], expected=ref, found=cash))

            # Savings to date = previous + this week's savings (− refunds, if the group keeps it net)
            sav_id = self.w("savings_to_date", wk)
            sav = rec.number(sav_id)
            s_id, r_id = self.w("savings", wk), self.w("savings_refunded", wk)
            s_lin, r_lin = Lin.cells([s_id]), Lin.cells([r_id])
            if sav is not None and prev_sav:
                gross = [Lin.cells([sav_id]) - (p + s_lin) for p in prev_sav]
                net = [Lin.cells([sav_id]) - (p + s_lin - r_lin) for p in prev_sav]
                ok_gross = any(abs(d.value(rec)) <= self.tol for d in gross)
                ok_net = any(abs(d.value(rec)) <= self.tol for d in net)
                if rec.num(r_id) and ok_net and not ok_gross:
                    sav_net = True
                p0, s, r = prev_sav[0].value(rec), rec.num(s_id), rec.num(r_id)
                self._ledger(rec, res, "savings_to_date", (net + gross) if sav_net else (gross + net),
                             f"{wk}: {sav_src} {_rs(p0)} + savings {_rs(s)} = {_rs(p0 + s)}"
                             + (f" ({_rs(p0 + s - r)} after the {_rs(r)} refund)" if r else "")
                             + f", but Total savings to date says {_rs(sav)}.",
                             fields=[sav_id, s_id, r_id], expected=p0 + s, found=sav)

            # Loans outstanding = previous + distributed − principal repaid (− write-offs)
            out_id = self.w("loans_outstanding", wk)
            out = rec.number(out_id)
            d_lin = Lin.cells([self.w("loans_distributed", wk)])
            p_lin = Lin.cells([self.w("principal_repaid", wk)])
            if out is not None and prev_out is not None:
                calc = (prev_out + d_lin - p_lin - wo_lin).value(rec)
                self._ledger(rec, res, "loans_outstanding",
                             [Lin.cells([out_id]) - (prev_out + d_lin - p_lin - wo_lin),
                              Lin.cells([out_id]) - (prev_out + d_lin - p_lin)],
                             f"{wk}: {out_src} {_rs(prev_out.value(rec))} + distributed {_rs(d_lin.value(rec))} − "
                             f"principal {_rs(p_lin.value(rec))} − write-offs {_rs(wo_lin.value(rec))} = {_rs(calc)}, "
                             f"but Total loans outstanding says {_rs(out)}.",
                             expected=calc, found=out)

            dep_id = self.w("cash_deposited_bank", wk)
            dep = rec.number(dep_id)
            if dep is not None and cash is not None and dep > cash + self.tol:
                res.add(Issue(rule="deposit_above_cash", severity=Severity.error, category=Category.arithmetic,
                              message=f"{wk}: {_rs(dep)} deposited in the bank, but cash in hand is only {_rs(cash)}.",
                              fields=[dep_id, cash_id], expected=f"<= {cash:g}", found=dep))

            # Carry forward to next week. A blank cell must not break the chain: use the
            # written expected balance, else work it out from this week's entries.
            # A write-off is not cash leaving the box: when this week's Expected Balance counts
            # it as an expense, the cash is that balance PLUS the write-offs.
            if cash is not None:
                prev_cash, cash_src = Lin.cells([cash_id]), "last week's cash in hand"
            elif expected_written is not None:
                prev_cash = Lin.cells([exp_id]) + (wo_lin if "write_offs" in variants[0] else Lin())
                cash_src = "last week's expected balance"
            elif prev_cash is not None:
                cash_exp = next((e for v, e in zip(variants, exps) if "write_offs" not in v), exps[0])
                prev_cash, cash_src = prev_cash + inc - cash_exp, "last week's balance (worked out from its entries)"
            if sav is not None:
                prev_sav, sav_src = [Lin.cells([sav_id])], "last week's savings to date"
            elif prev_sav:
                # Blank this week: carry EVERY variant on (gross, and net of this week's refund),
                # the one the group is known to use first.
                carried = [p + s_lin for p in prev_sav] + [p + s_lin - r_lin for p in prev_sav]
                if sav_net:
                    carried = [p + s_lin - r_lin for p in prev_sav] + [p + s_lin for p in prev_sav]
                uniq: dict[float, Lin] = {}
                for c in carried:
                    uniq.setdefault(round(c.value(rec), 2), c)
                prev_sav = list(uniq.values())
                sav_src = "last week's savings to date (worked out)"
            if out is not None:
                prev_out, out_src = Lin.cells([out_id]), "last week's loans outstanding"
            elif prev_out is not None:
                prev_out = prev_out + d_lin - p_lin - wo_lin
                out_src = "last week's loans outstanding (worked out)"

    def _month_end_cash(self, rec: FormRecord, res: ValidationResult) -> None:
        """The workbook needs the cash in hand at the end of the LAST ACTIVE week. An earlier
        week's figure would be stale, so a blank there blocks instead of being filled in."""
        wk = last_active_week(rec, self.t)
        if wk is None:
            res.add(Issue(rule="month_end_cash_missing", severity=Severity.error, category=Category.completeness,
                          message="No week on the form has any entries, so there is no month-end cash in hand "
                                  "for the workbook. Check the photo of page 1.",
                          fields=[self.w("cash_in_hand", c) for c in WEEKS]))
            return
        cash_id = self.w("cash_in_hand", wk)
        if rec.number(cash_id) is None:
            res.add(Issue(rule="month_end_cash_missing", severity=Severity.error, category=Category.completeness,
                          message=f"{wk} is the last week with entries, but its 'Actual Cash in Hand' is blank. "
                                  "The workbook needs the month-end cash: read it from the photo or ask the group.",
                          fields=[cash_id]))

    # ------------------------------------------------------------------ layer 3
    def _checked(self, rec: FormRecord, fid: str) -> bool:
        fv = rec.fields.get(fid)
        return fv is not None and fv.status in CHECKED

    def _opening_consistency(self, rec: FormRecord, res: ValidationResult, prior: Optional[PriorMonth]) -> bool:
        """A new group the officer says started this month: its opening totals are zero, so the
        form's own savings to date and loans outstanding must be just this month's flows. When
        they are clearly MORE (in the first and the last week that has them), the group is
        older: block, and don't run the week-1 checks from zero (they would suggest 'fixing'
        correctly read cells)."""
        if not (prior and prior.started_this_month and self._prior_is_last_month(rec, prior)):
            return True
        ok = True
        checks = [
            ("savings_to_date", {"savings": 1}, "savings_refunded", prior.savings_to_date,
             "The form says total savings to date is {v}, but the group's only savings this month is {c}, "
             "so it did not start this month. Enter its totals from the mother book."),
            ("loans_outstanding", {"loans_distributed": 1, "principal_repaid": -1}, "write_offs", prior.loans_outstanding,
             "The form says total loans outstanding is {v}, but this month's loans less repayments come to only "
             "{c}, so the group did not start this month. Enter its totals from the mother book."),
        ]
        for bal, flows, alt, base, text in checks:
            base = base or 0.0
            run = alt_run = 0.0
            written: list[tuple[str, float, float, float]] = []      # week, figure, gross, net
            for wk in WEEKS:
                run += sum(sign * rec.num(self.w(k, wk)) for k, sign in flows.items())
                alt_run += rec.num(self.w(alt, wk))
                v = rec.number(self.w(bal, wk))
                if v is not None:
                    written.append((wk, v, base + run, base + run - alt_run))
            if not written:
                continue
            above = lambda e: e[1] > max(e[2], e[3]) + self.tol
            first, last = written[0], written[-1]
            if above(first) and above(last):
                ok = False
                res.add(Issue(rule="opening_inconsistent", severity=Severity.error, category=Category.continuity,
                              message=text.format(v=_rs(last[1]), c=_rs(last[2])),
                              fields=[self.w(bal, e[0]) for e in written], expected=last[2], found=last[1]))
        return ok

    def _continuity(self, rec: FormRecord, res: ValidationResult, prior: Optional[PriorMonth]) -> None:
        month = rec.get("header.month_year")
        ym = _valid_ym(month)
        m_checked = self._checked(rec, "header.month_year")
        unexpected = False
        if ym and ym < "2000-01":
            unexpected = True
            res.add(Issue(rule="month_unexpected", severity=Severity.error, category=Category.continuity,
                          message=f"The form says {_month_name(ym)}, which is before 2000. Check the month on the photo.",
                          fields=["header.month_year"], found=month))
        elif prior and month and prior.this_month_recorded:
            res.add(Issue(rule="month_already_recorded", severity=Severity.error, category=Category.continuity,
                          message=f"{_month_name(month)} is already recorded in the workbook for this group. "
                                  "Check the month on the form. If this report corrects that month, "
                                  "an officer has to confirm the correction.",
                          fields=["header.month_year"], found=month))
        elif prior and month and prior.month:
            try:
                nxt = add_months(prior.month, 1)
            except ValueError:
                nxt = None
            if nxt and str(month) < nxt:
                res.add(Issue(rule="month_already_recorded", severity=Severity.error, category=Category.continuity,
                              message=f"The workbook already has figures up to {_month_name(prior.month)}, so "
                                      f"{_month_name(month)} is not a new month. Is this a correction, or the wrong month?",
                              fields=["header.month_year"], expected=nxt, found=month))
            elif nxt and month != nxt:
                # More than one month after the last recorded month: usually a misread month or
                # year (10/2027 for 10/2026), which would put the figures in the wrong column.
                # An officer must look; once she has, it is the usual missing-months warning.
                unexpected = True
                if m_checked:
                    last_missing = add_months(str(month), -1)
                    gap = _month_name(nxt) if last_missing == nxt else f"{_month_name(nxt)} to {_month_name(last_missing)}"
                    res.add(Issue(rule="month_gap", severity=Severity.warning, category=Category.continuity,
                                  message=f"The last month recorded is {_month_name(prior.month)}, so {gap} "
                                          f"{'is' if last_missing == nxt else 'are'} missing. Last month's closing "
                                          "balances were not used for the week 1 checks.",
                                  fields=["header.month_year"], expected=nxt, found=month))
                else:
                    res.add(Issue(rule="month_unexpected", severity=Severity.error, category=Category.continuity,
                                  message=f"The form says {_month_name(month)}, but the last month recorded for this "
                                          f"group is {_month_name(prior.month)}. Check the month on the photo. If months "
                                          "really are missing, confirm it as written.",
                                  fields=["header.month_year"], expected=nxt, found=month))
        today = res._today
        if ym and today and not unexpected and ym > add_months(today, 1):
            text = (f"The form says {_month_name(ym)}, but that is more than a month from now "
                    f"({_month_name(today)}). Check the month on the photo. If it is right, confirm it as written.")
            res.add(Issue(rule="month_unexpected", severity=Severity.warning if m_checked else Severity.error,
                          category=Category.continuity, message=(KEPT + text) if m_checked else text,
                          fields=["header.month_year"], expected=f"<= {add_months(today, 1)}", found=month))

        members = rec.number("header.total_members")
        if prior and members is not None and prior.members is not None and abs(members - prior.members) > 5:
            change = f"Members changed from {prior.members} last month to {members:g}."
            if abs(members - prior.members) > 0.25 * prior.members:
                # A big jump is more often a misread (18 read as 48) than a real change, and the
                # member count is not in her WhatsApp summary: an officer has to look.
                checked = self._checked(rec, "header.total_members")
                res.add(Issue(rule="members_jump", severity=Severity.warning if checked else Severity.error,
                              category=Category.continuity,
                              message=KEPT + change if checked else
                              change + " Check the member count on the photo. If it really changed, confirm it as written.",
                              fields=["header.total_members"], expected=prior.members, found=members))
            else:
                res.add(Issue(rule="members_jump", severity=Severity.warning, category=Category.continuity,
                              message=change, fields=["header.total_members"], expected=prior.members, found=members))

    # ------------------------------------------------------------------ layer 5
    def _findings(self, rec: FormRecord, res: ValidationResult, weeks: list[str]) -> None:
        members = rec.number("header.total_members")
        overdue = rec.number(self.w("members_loans_overdue", "Total"))
        named = [i for i in range(5) if rec.get(f"page2.overdue_members.{i}.name")]
        if overdue and not named:
            res.add(Issue(rule="overdue_names_missing", severity=Severity.warning, category=Category.completeness,
                          message=f"{overdue:g} members have overdue loans, but no names are listed on page 2.",
                          fields=[self.w("members_loans_overdue", "Total")]))
        elif overdue is not None and named and len(named) != overdue and overdue <= 5:
            res.add(Issue(rule="overdue_count_mismatch", severity=Severity.info, category=Category.completeness,
                          message=f"{overdue:g} members have overdue loans; {len(named)} are listed by name.",
                          fields=[self.w("members_loans_overdue", "Total")]))
        if members and overdue and overdue / members >= 0.3:
            res.add(Issue(rule="high_overdue_share", severity=Severity.warning, category=Category.finding,
                          message=f"{overdue:g} of {members:g} members ({overdue / members:.0%}) have overdue loans.",
                          fields=[self.w("members_loans_overdue", "Total")]))

        cap = self.t.validation.get("high_cash_in_hand")
        wk = last_active_week(rec, self.t)
        last_cash = rec.number(self.w("cash_in_hand", wk)) if wk else None
        if cap and last_cash is not None and last_cash > cap and not rec.get("page2.high_cash_reason"):
            res.add(Issue(rule="high_cash_no_reason", severity=Severity.warning, category=Category.finding,
                          message=f"Cash in hand at month end is {_rs(last_cash)}, and no reason is given.",
                          fields=["page2.high_cash_reason"]))

        held = [wk for wk in weeks if rec.get(self.w("meeting_held", wk)) is True]
        if members and held:
            att = [rec.num(self.w("attendance", wk)) for wk in held]
            rate = sum(att) / (members * len(held))
            if rate < 0.5:
                res.add(Issue(rule="low_attendance", severity=Severity.warning, category=Category.finding,
                              message=f"Average attendance was {rate:.0%} of members across {len(held)} meetings.",
                              fields=[self.w("attendance", wk) for wk in held], found=round(rate, 3)))

    # ------------------------------------------------------------------ ranking
    def _substitute(self, rec: FormRecord, fid: str, value: object) -> FormRecord:
        """The record as it would be if an officer set `fid` to `value`."""
        fields = dict(rec.fields)
        old = fields.get(fid) or FieldValue()
        fields[fid] = old.model_copy(update={
            "value": value, "passes": [value],
            "legibility": Legibility.clear if value is not None else Legibility.blank,
            "history": [h for h in old.history if h.get("event") != "capture_check"]})
        return FormRecord.model_construct(template_id=rec.template_id, fields=fields, image_ids=rec.image_ids)

    def _pass_choice(self, rec: FormRecord, fid: str, prior: Optional[PriorMonth],
                     res_today: Optional[str] = None) -> Optional[Number]:
        """Readings disagree: the reading the ledger supports, if exactly one does better."""
        passes = rec.fields[fid].passes
        if any(isinstance(p, bool) or not isinstance(p, (int, float, type(None))) for p in passes):
            return None                      # not a number (yes/no, text): nothing to add up
        cands = list(dict.fromkeys(passes))  # a blank reading competes too, but is never suggested
        scored = []
        for v in cands:
            after = self._check_all(self._substitute(rec, fid, v), prior, res_today)
            wrong = sum(1 for i in after.errors if fid in i.fields and i.rule not in CAPTURE_RULES)
            scored.append((wrong, -after._support.get(fid, 0), v))
        scored.sort(key=lambda x: (x[0], x[1]))
        if not scored:
            return None
        best = scored[0]
        if best[2] is None or best[1] == 0 or (len(scored) > 1 and scored[1][:2] == best[:2]):
            return None                      # no sum backs it, or two readings do equally well
        return best[2]

    def _rank(self, rec: FormRecord, res: ValidationResult, prior: Optional[PriorMonth],
              base: Optional[ValidationResult] = None) -> list[Likely]:
        errors = res.errors
        if not errors:
            return []
        today = res._today or (base._today if base else None)
        base = base or self._check_all(rec, prior, today)   # unchanged record: which issues the validator owns
        base_keys = {_key(i) for i in base.issues}
        # capture issues get their suggestion here (it needs the whole ledger)
        for issue in errors:
            fid = issue.fields[0] if issue.fields else None
            if fid not in rec.fields or issue.suggest:
                continue
            if issue.rule == "passes_disagree":
                v = self._pass_choice(rec, fid, prior, today)
            elif issue.rule in ("unclear_handwriting", "ink_mismatch") and base._support.get(fid):
                v = rec.number(fid)          # unclear, but the sums it is part of balance
                v = int(v) if v is not None and v.is_integer() else v
            else:
                v = None
            if v is not None:
                issue.suggest = {fid: v}

        out = []
        for f in _unique(f for i in errors for f in i.fields):
            its = [i for i in errors if f in i.fields]
            cands = Counter(i.suggest[f] for i in its if f in i.suggest)
            suggest = None
            if cands:
                (val, n), *rest = cands.most_common()
                if (n >= 2 and (not rest or rest[0][1] < n)) or (len(its) == 1 and n == 1):
                    suggest = val
            balances = also = 0
            if suggest is not None:
                after = self._check_all(self._substitute(rec, f, suggest), prior, today)
                after_keys = {_key(i) for i in after.issues if i.severity == Severity.error}
                after_all = {_key(i) for i in after.issues}
                before = {_key(i) for i in res.issues}
                new = [i for i in after.errors if f in i.fields and _key(i) not in base_keys | before]
                balances = sum(1 for i in its if _key(i) in base_keys and _key(i) not in after_keys)
                # Tie-break: a warning that lists this cell (e.g. W1 "cash in hand is Rs 60,000
                # more than expected") and goes away too is evidence this is the misread cell.
                also = sum(1 for i in base.issues if i.severity == Severity.warning and f in i.fields
                           and _key(i) not in after_all)
                if new or balances == 0:
                    suggest, balances, also = None, 0, 0   # it would break another check, or clear nothing
            out.append(Likely(field=f, checks=len(its), suggest=suggest, balances=balances, also_clears=also))

        capture = {f for i in errors if i.rule in CAPTURE_RULES for f in i.fields}
        # Last tie-breaks: a cell other balanced sums already vouch for is less likely the misread
        # one; then form order.
        out.sort(key=lambda l: (-l.checks, l.suggest is None, -l.balances, -l.also_clears, l.field not in capture,
                                base._support.get(l.field, 0), self._order.get(l.field, len(self._order))))
        return out
