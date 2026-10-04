"""Round 2 regression tests for the data-integrity core (validation, workbook writer,
extraction). Each test failed on the round-1 code; the finding it covers is named
(review2/backend/REVIEW.md: P1-x / P2-x, review2/api/REVIEW.md: F10)."""
import json
import random
import shutil
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import openpyxl
import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from seed_demo_workbook import seed as _seed  # noqa: E402

from app import workbook as W
from app.aggregate import to_monthly
from app.extraction import ClaudeReader, ExtractionError
from app.models import FieldStatus, FieldValue, FormRecord, Legibility, PriorMonth, normalise_month
from app.schema import WEEKS, load_template
from app.validation import (OPENING_LABELS, OUTSTANDING_TD, SAVINGS_TD, Validator, implied_opening_cash,
                            opening_suggestion, prior_from_opening)
from app.workbook import GNWorkbook, WorkbookError

T = load_template()
TODAY = date(2026, 10, 4)
V = Validator(T, today=TODAY)
SYN = ROOT / "samples" / "synthetic"
TEMPLATE_XLSX = ROOT / "samples" / "gn_workbook_template.xlsx"
CASH = "Cash in Hand – at end of month (mother book) (Rs.)"
ZERO = {label: 0 for label in OPENING_LABELS}
C_ROWS = range(21, 30)                    # the nine "to date" rows of Palmera's GN template


def seed(path):
    """The demo workbook, whatever the seeding tool's version: its June dict holds the
    column-C values themselves (to_date=), not the totals before June (opening=)."""
    orig = W.GNWorkbook.write_month

    def write_month(self, *a, **kw):
        kw.setdefault("create_tab", True)
        if kw.get("opening") and kw["opening"].get(SAVINGS_TD):
            kw["to_date"] = kw.pop("opening")
        return orig(self, *a, **kw)
    with mock.patch.object(W.GNWorkbook, "write_month", write_month):
        return _seed(path)


@pytest.fixture
def wbpath(tmp_path):
    return seed(tmp_path / "gn.xlsx")


def record(values):
    rec = FormRecord(template_id=T.id)
    for fid, v in values.items():
        if v is None:
            continue
        rec.fields[fid] = FieldValue(value=v, raw=str(v), passes=[v, v], legibility=Legibility.clear)
    return rec


def truth(case):
    return json.loads((SYN / f"{case}.truth.json").read_text())


def form(case, **over):
    """A synthetic form as both readings agree on it (page 2 left out)."""
    tr = dict(truth(case), **over)
    return record({k: v for k, v in tr.items() if not k.startswith("page2.") and k in set(T.all_field_ids())})


def errors(res):
    return [i.rule for i in res.errors]


def palmera_c20(ws):
    """Palmera's 'cash from app' for month 1: =C21+C22+C23+C24-C25-C26-C27."""
    v = [ws.cell(r, 3).value or 0 for r in range(21, 28)]
    return v[0] + v[1] + v[2] + v[3] - v[4] - v[5] - v[6]


def confirm(rec, fid):
    rec.fields[fid].status = FieldStatus.officer_confirmed
    return rec


# a mother book for 'Nilmini' (the Vasantham October form under a new name), consistent with
# the form: savings to date before October 52,600, loans outstanding 42,000, cash Rs 9,340
NILMINI_OPENING = {
    "Total savings to date (Rs.)": 52600, "Total Principal loan repayments to date (Rs.)": 90000,
    "Total Interest repayments to date (Rs.)": 8000, "Total Other income to date (Rs.)": 1500,
    "Total Loans distributed to date (Rs.)": 132000, "Total Savings refunded to date (Rs.)": 10000,
    "Total Other expenses to date (Rs.)": 760, "Total Loan right off to date (Rs.)": 0,
    "Total Loans outstanding to date (Rs.)": 42000,
}


# ====================================================================== P1-1
def test_overwrite_of_first_month_keeps_lifetime_totals(wbpath):
    before = {r: openpyxl.load_workbook(wbpath)["Kalaimagal"].cell(r, 3).value for r in C_ROWS}
    g = GNWorkbook(wbpath, T)
    vals = to_monthly(form("kalaimagal_2026-10", **{"header.month_year": "2026-06"}), T)
    rep = g.write_month("Kalaimagal", "2026-06", vals, overwrite=True)
    g.save()
    ws = openpyxl.load_workbook(wbpath)["Kalaimagal"]
    assert {r: ws.cell(r, 3).value for r in C_ROWS} == before          # round 1: C21 50300 -> 11400
    assert len(rep.writes) == 16 and not rep.created_tab
    assert not any("New SHG tab" in w for w in rep.warnings)
    assert any("lifetime totals" in w and "were not changed" in w for w in rep.warnings)


def test_new_tab_needs_opening_totals_and_nothing_changes_without(tmp_path):
    p = tmp_path / "gn.xlsx"; shutil.copy(TEMPLATE_XLSX, p)
    g = GNWorkbook(p, T)
    tabs = list(g.wb.sheetnames)
    with pytest.raises(WorkbookError, match="opening 'to date' totals are needed"):
        g.write_month("Nilmini", "2026-10", to_monthly(form("vasantham_2026-10"), T), gn_name="X", create_tab=True)
    with pytest.raises(WorkbookError, match="missing, negative or not a number: 'Total Loans outstanding"):
        g.write_month("Nilmini", "2026-10", to_monthly(form("vasantham_2026-10"), T), gn_name="X", create_tab=True,
                      opening={k: v for k, v in ZERO.items() if k != OUTSTANDING_TD})
    assert g.wb.sheetnames == tabs                                     # no half-made tab


# ====================================================================== P1-2
def test_opening_suggestion_from_the_form():
    s = opening_suggestion(form("vasantham_2026-10"))
    assert set(s) == set(OPENING_LABELS)
    assert s[SAVINGS_TD] == 52600 and s[OUTSTANDING_TD] == 42000     # 55,700 − 3,100; 44,900 − 5,000 + 2,100
    assert all(v is None for k, v in s.items() if k not in (SAVINGS_TD, OUTSTANDING_TD))


def test_opening_suggestion_is_none_when_the_form_cannot_say():
    rec = form("vasantham_2026-10", **{"weekly.savings_refunded.W3": 500})
    assert opening_suggestion(rec)[SAVINGS_TD] == 52600                 # W1, W2 come before the refund
    rec = form("vasantham_2026-10", **{f"weekly.savings_refunded.W1": 500,
                                       **{f"weekly.savings_to_date.{w}": None for w in WEEKS[1:]}})
    assert opening_suggestion(rec)[SAVINGS_TD] is None                  # gross or net? can't tell
    rec = form("vasantham_2026-10", **{"weekly.savings_to_date.W3": 71900})   # weeks disagree
    assert opening_suggestion(rec)[SAVINGS_TD] is None
    assert opening_suggestion(record({}))[SAVINGS_TD] is None


def test_implied_opening_cash():
    assert implied_opening_cash(NILMINI_OPENING) == 9340
    assert implied_opening_cash(ZERO) == 0
    assert implied_opening_cash({k: v for k, v in NILMINI_OPENING.items() if k != SAVINGS_TD}) is None
    assert implied_opening_cash(None) is None


def test_new_group_with_mother_book_totals_balances_in_palmeras_formula(tmp_path):
    rec = form("vasantham_2026-10", **{"header.shg_name": "Nilmini"})
    prior = prior_from_opening(rec, NILMINI_OPENING)
    assert (prior.month, prior.cash_in_hand, prior.savings_to_date, prior.loans_outstanding) == \
        ("2026-09", 9340, 52600, 42000)
    assert V.validate(rec, prior).errors == []
    p = tmp_path / "gn.xlsx"; shutil.copy(TEMPLATE_XLSX, p)
    g = GNWorkbook(p, T)
    rep = g.write_month("Nilmini", "2026-10", to_monthly(rec, T), gn_name="X", create_tab=True,
                        opening=NILMINI_OPENING)
    g.save()
    ws = openpyxl.load_workbook(p)["Nilmini"]
    assert rep.created_tab and rep.column == "C" and len(rep.writes) == 25
    assert ws["C21"].value == 65000 and ws["C29"].value == 51700        # = the form's W4 figures
    assert palmera_c20(ws) == ws["C19"].value == 13030                  # round 1: 3,690 vs 13,030


def test_opening_mismatching_the_form_is_caught_by_the_week1_checks():
    rec = form("vasantham_2026-10", **{"header.shg_name": "Nilmini"})
    wrong = dict(NILMINI_OPENING, **{SAVINGS_TD: 50000, "Total Other expenses to date (Rs.)": 0})
    res = V.validate(rec, prior_from_opening(rec, wrong))
    msgs = {i.rule: i.message for i in res.errors}
    assert msgs["savings_to_date"].startswith("W1: opening savings to date (mother book) Rs 50,000")
    assert msgs["expected_balance"].startswith("W1: opening cash (from the mother-book totals) Rs 7,500")


def test_started_this_month_but_the_form_says_otherwise():
    rec = form("vasantham_2026-10", **{"header.shg_name": "Nilmini"})
    res = V.validate(rec, prior_from_opening(rec, None, started_this_month=True))
    msgs = [i.message for i in res.errors if i.rule == "opening_inconsistent"]
    assert msgs == [
        "The form says total savings to date is Rs 65,000, but the group's only savings this month is Rs 12,400, "
        "so it did not start this month. Enter its totals from the mother book.",
        "The form says total loans outstanding is Rs 51,700, but this month's loans less repayments come to only "
        "Rs 9,700, so the group did not start this month. Enter its totals from the mother book."]
    # the week-1 checks don't run from zero, so no "Use 3,100" on a correctly read cell
    assert set(errors(res)) == {"opening_inconsistent"}
    assert all(l.suggest is None for l in res.likely)


def test_started_this_month_clean_new_group():
    cash, sav, out = 0, 0, 0
    cells = {"header.shg_name": "Nilmini", "header.total_members": 12, "header.village_gn": "X",
             "header.month_year": "2026-10"}
    for wk, (s, d, p) in zip(WEEKS, [(1200, 0, 0), (1100, 2000, 0), (1300, 0, 500), (1000, 0, 500)]):
        cash += s + p - d; sav += s; out += d - p
        cells.update({f"weekly.meeting_held.{wk}": True, f"weekly.attendance.{wk}": 10,
                      f"weekly.savings.{wk}": s, f"weekly.loans_distributed.{wk}": d or None,
                      f"weekly.loan_purpose_income.{wk}": d or None, f"weekly.principal_repaid.{wk}": p or None,
                      f"weekly.total_income.{wk}": s + p, f"weekly.total_expenses.{wk}": d,
                      f"weekly.expected_balance.{wk}": cash, f"weekly.cash_in_hand.{wk}": cash,
                      f"weekly.savings_to_date.{wk}": sav, f"weekly.loans_outstanding.{wk}": out})
    rec = record(cells)
    assert V.validate(rec, prior_from_opening(rec, ZERO, started_this_month=True)).errors == []
    # and a misread W1 expected balance is still caught from the zero opening
    rec.fields["weekly.expected_balance.W1"].value = 7200
    rec.fields["weekly.expected_balance.W1"].passes = [7200, 7200]
    res = V.validate(rec, prior_from_opening(rec, ZERO, started_this_month=True))
    assert "expected_balance" in errors(res) and "opening_inconsistent" not in errors(res)
    assert res.likely[0].field == "weekly.expected_balance.W1" and res.likely[0].suggest == 1200


# ====================================================================== P1-3 / month sanity
def test_misread_year_or_month_blocks(wbpath):
    prior = GNWorkbook(wbpath, T).prior_month("Vasantham", "2027-10")
    rec = form("vasantham_2026-10", **{"header.month_year": "2027-10"})
    res = V.validate(rec, prior)
    issue = next(i for i in res.errors if i.rule == "month_unexpected")
    assert issue.message == ("The form says October 2027, but the last month recorded for this group is "
                             "September 2026. Check the month on the photo. If months really are missing, "
                             "confirm it as written.")
    assert issue.fields == ["header.month_year"]
    rec = form("vasantham_2026-10", **{"header.month_year": "2026-12"})
    prior = GNWorkbook(wbpath, T).prior_month("Vasantham", "2026-12")
    assert "month_unexpected" in errors(V.validate(rec, prior))
    # the officer checked the photo: months really are missing -> the round-1 warning
    res = V.validate(confirm(rec, "header.month_year"), prior)
    assert "month_unexpected" not in errors(res)
    assert [i.severity.value for i in res.issues if i.rule == "month_gap"] == ["warning"]


def test_month_far_in_the_future_blocks_even_without_history():
    rec = form("vasantham_2026-10", **{"header.month_year": "2026-12"})
    issue = next(i for i in V.validate(rec, None).errors if i.rule == "month_unexpected")
    assert issue.message == ("The form says December 2026, but that is more than a month from now "
                             "(October 2026). Check the month on the photo. If it is right, confirm it as written.")
    assert "month_unexpected" not in errors(V.validate(form("vasantham_2026-10", **{"header.month_year": "2026-11"}), None))
    res = V.validate(confirm(rec, "header.month_year"), None)
    assert not res.errors and any(i.rule == "month_unexpected" and i.message.startswith("Checked against the photo")
                                  for i in res.issues)
    assert Validator(T, today=date(2027, 3, 1)).validate(rec, None).errors == []


@pytest.mark.parametrize("raw", ["10/1926", "1999-12", "Oct 3026", "10/2101"])
def test_implausible_years_are_not_months(raw):
    with pytest.raises(ValueError):
        normalise_month(raw)


@pytest.mark.parametrize("raw,ym", [("10/26", "2026-10"), ("2000-01", "2000-01"), ("Dec 2100", "2100-12")])
def test_plausible_years_still_parse(raw, ym):
    assert normalise_month(raw) == ym


# ====================================================================== P1-5
@pytest.mark.parametrize("before,now,severity", [
    (18, 48, "error"), (18, 24, "error"), (40, 46, "warning"), (18, 23, None), (20, 12, "error")])
def test_members_jump(before, now, severity):
    rec = form("vasantham_2026-10", **{"header.total_members": now})
    prior = PriorMonth(month="2026-09", cash_in_hand=9340, savings_to_date=52600, loans_outstanding=42000,
                       members=before)
    jumps = [i for i in V.validate(rec, prior).issues if i.rule == "members_jump"]
    assert [i.severity.value for i in jumps] == ([severity] if severity else [])
    if severity == "error":
        assert jumps[0].message == (f"Members changed from {before} last month to {now}. Check the member count "
                                    "on the photo. If it really changed, confirm it as written.")
        kept = [i for i in V.validate(confirm(rec, "header.total_members"), prior).issues if i.rule == "members_jump"]
        assert [(i.severity.value, i.message) for i in kept] == \
            [("warning", f"Checked against the photo, kept as written: Members changed from {before} last month to {now}.")]


# ====================================================================== P2-1
def test_net_savings_to_date_with_a_blank_week():
    prior = PriorMonth(month="2026-09", cash_in_hand=10000, savings_to_date=50000, savings_refunded_to_date=2000,
                       loans_outstanding=0, members=10)
    cells = {"header.shg_name": "X", "header.month_year": "2026-10", "header.total_members": 10,
             "header.village_gn": "G"}
    for wk, cash in (("W1", 11000), ("W2", 12000)):
        cells.update({f"weekly.meeting_held.{wk}": True, f"weekly.attendance.{wk}": 8, f"weekly.savings.{wk}": 1000,
                      f"weekly.total_income.{wk}": 1000, f"weekly.total_expenses.{wk}": 0,
                      f"weekly.expected_balance.{wk}": cash, f"weekly.cash_in_hand.{wk}": cash})
    assert V.validate(record(dict(cells, **{"weekly.savings_to_date.W2": 50000})), prior).errors == []
    # and a refund in the blank week, kept net
    cells["weekly.savings_refunded.W1"] = 500
    cells["weekly.total_expenses.W1"] = 500
    cells["weekly.expected_balance.W1"] = cells["weekly.cash_in_hand.W1"] = 10500
    cells["weekly.expected_balance.W2"] = cells["weekly.cash_in_hand.W2"] = 11500
    assert V.validate(record(dict(cells, **{"weekly.savings_to_date.W2": 49500})), prior).errors == []
    assert V.validate(record(dict(cells, **{"weekly.savings_to_date.W2": 52000})), prior).errors == []   # gross
    assert "savings_to_date" in errors(V.validate(record(dict(cells, **{"weekly.savings_to_date.W2": 49000})), prior))


# ====================================================================== P2-2
@pytest.fixture(scope="module")
def kalaimagal(tmp_path_factory):
    p = seed(tmp_path_factory.mktemp("k") / "gn.xlsx")
    return GNWorkbook(p, T).prior_month("Kalaimagal", "2026-10")


@pytest.mark.parametrize("fid,bad,good", [
    ("weekly.cash_in_hand.W1", 72250, 12250), ("weekly.cash_in_hand.W2", 76830, 16830)])
def test_misread_cash_is_ranked_over_the_next_weeks_expected_balance(kalaimagal, fid, bad, good):
    rec = form("kalaimagal_2026-10", **{fid: bad})
    res = V.validate(rec, kalaimagal)
    top = res.likely[0]
    assert (top.field, top.suggest) == (fid, good)                     # round 1: 'Use 76,830' on W2 expected
    assert top.also_clears >= 1


def test_deposit_misread_ranked_over_the_cash_it_is_compared_with(kalaimagal):
    res = V.validate(form("kalaimagal_2026-10", **{"weekly.cash_deposited_bank.W4": 75000}), kalaimagal)
    assert res.likely[0].field == "weekly.cash_deposited_bank.W4"


def test_demo_ranking_unchanged(kalaimagal):
    tr = truth("kalaimagal_2026-10")
    rec = form("kalaimagal_2026-10", **{"weekly.interest_repaid.W3": 810})      # both readings: 810
    rec.fields["weekly.savings.W2"].passes = [2800, 2300]                       # the readings disagree
    res = V.validate(rec, kalaimagal)
    assert (res.likely[0].field, res.likely[0].suggest) == ("weekly.interest_repaid.W3", tr["weekly.interest_repaid.W3"])
    rec.fields["weekly.interest_repaid.W3"] = FieldValue(value=310, passes=[310], legibility=Legibility.clear,
                                                          status=FieldStatus.officer_corrected)
    res = V.validate(rec, kalaimagal)
    assert (res.likely[0].field, res.likely[0].suggest) == ("weekly.savings.W2", 2800)


# ====================================================================== P2-6 + property test
def test_write_offs_inside_expected_balance_are_accepted():
    prior = PriorMonth(month="2026-09", cash_in_hand=10000, savings_to_date=50000, loans_outstanding=20000, members=10)
    cells = {"header.shg_name": "X", "header.month_year": "2026-10", "header.total_members": 10,
             "header.village_gn": "G"}
    # W1: Rs 1,000 written off and counted in Total Expenses (Palmera's GN definition)
    cells.update({"weekly.meeting_held.W1": True, "weekly.attendance.W1": 8, "weekly.savings.W1": 1000,
                  "weekly.write_offs.W1": 1000, "weekly.total_income.W1": 1000, "weekly.total_expenses.W1": 1000,
                  "weekly.expected_balance.W1": 10000, "weekly.savings_to_date.W1": 51000,
                  "weekly.loans_outstanding.W1": 19000})
    cells.update({"weekly.meeting_held.W2": True, "weekly.attendance.W2": 8, "weekly.savings.W2": 1000,
                  "weekly.total_income.W2": 1000, "weekly.total_expenses.W2": 0,
                  "weekly.expected_balance.W2": 12000, "weekly.cash_in_hand.W2": 12000})
    # W1 cash blank: W2 starts from expected + write-off (11,000), not 10,000
    assert V.validate(record(cells), prior).errors == []
    cells["weekly.cash_in_hand.W1"] = 11000                           # cash = expected + write-off
    res = V.validate(record(cells), prior)
    assert res.errors == [] and not any(i.rule == "cash_mismatch" for i in res.issues)
    cells["weekly.cash_in_hand.W2"] = 13000                           # a real mismatch still blocks
    assert "month_end_cash_mismatch" in errors(V.validate(record(cells), prior))


def _random_form(seed, wo_in_expenses=False, allow_writeoff=True):
    """Internally consistent random month (the reviewer's p07 generator)."""
    rnd = random.Random(seed)
    f = {}
    members = rnd.randint(8, 25)
    prior = PriorMonth(month="2026-09", cash_in_hand=rnd.randrange(2000, 20000, 10),
                       savings_to_date=rnd.randrange(20000, 90000, 100),
                       savings_refunded_to_date=rnd.choice([0, 500, 2000]),
                       loans_outstanding=rnd.randrange(10000, 60000, 100), members=members)
    net = rnd.random() < 0.3
    f.update({"header.shg_name": "X", "header.total_members": members, "header.village_gn": "G",
              "header.month_year": "2026-10"})
    cash = prior.cash_in_hand
    sav = prior.savings_to_date - (prior.savings_refunded_to_date if net else 0)
    out = prior.loans_outstanding
    nweeks = rnd.choice([4, 4, 5])
    skip = rnd.choice([None, None, None, "W2", "W3"])
    tot = Counter()
    for wk in WEEKS[:nweeks]:
        if wk == skip:
            if rnd.random() < 0.5:
                f[f"weekly.meeting_held.{wk}"] = False
            continue
        f[f"weekly.meeting_held.{wk}"] = True
        f[f"weekly.attendance.{wk}"] = rnd.randint(members // 2 + 1, members)
        s, p = rnd.randrange(0, 4000, 100), rnd.randrange(0, 3000, 100)
        i, o = rnd.randrange(0, 400, 10), rnd.choice([0, 0, 50, 150])
        income = s + p + i + o
        d = rnd.choice([0, 0, rnd.randrange(0, max(1, int((cash + income) * 0.8)) // 100 * 100 + 1, 100)])
        pi = rnd.randrange(0, d + 1, 100) if d else 0
        ref, oe = rnd.choice([0, 0, 0, 500]), rnd.choice([0, 0, 100, 250])
        wo = rnd.choice([0, 0, 0, 0, 1000]) if allow_writeoff and out > 2000 else 0
        exp = d + ref + oe
        cash = cash + income - exp
        if cash < 0:
            return None
        sav = sav + s - (ref if net else 0)
        out = out + d - p - wo
        vals = dict(savings=s, principal_repaid=p, interest_repaid=i, other_income=o, loans_distributed=d,
                    loan_purpose_income=pi, loan_purpose_emergency=d - pi, savings_refunded=ref, other_expenses=oe,
                    write_offs=wo, total_income=income, total_expenses=exp + (wo if wo_in_expenses else 0))
        for k, v in vals.items():
            if v or k in ("savings", "total_income", "total_expenses"):
                f[f"weekly.{k}.{wk}"] = v
                tot[k] += v
        if rnd.random() < 0.85:
            f[f"weekly.expected_balance.{wk}"] = cash - (wo if wo_in_expenses else 0)
        if rnd.random() < 0.85 or wk == WEEKS[nweeks - 1]:
            f[f"weekly.cash_in_hand.{wk}"] = cash
        if rnd.random() < 0.85:
            f[f"weekly.savings_to_date.{wk}"] = sav
        if rnd.random() < 0.85:
            f[f"weekly.loans_outstanding.{wk}"] = out
    for k, v in tot.items():
        if rnd.random() < 0.7:
            f[f"weekly.{k}.Total"] = v
    return record(f), prior


@pytest.mark.parametrize("kw", [{}, {"allow_writeoff": False}, {"wo_in_expenses": True}],
                         ids=["write-offs-outside", "no-write-offs", "write-offs-in-expenses"])
def test_consistent_random_forms_never_block(kw):
    blocked = Counter()
    for s in range(400):
        m = _random_form(s, **kw)
        if m is None:
            continue
        res = V.validate(*m)
        blocked.update(errors(res))
    assert not blocked, blocked                                        # round 1: 73 and 242 of 1,500


# ====================================================================== F10
def test_names_are_never_written_as_formulas(tmp_path):
    p = tmp_path / "gn.xlsx"; shutil.copy(TEMPLATE_XLSX, p)
    g = GNWorkbook(p, T)
    name, gn = "=CMD|' /C calc'!A0", "+IMPORTXML(\"http://x\",\"//a\")"
    rep = g.write_month(name, "2026-10", to_monthly(form("vasantham_2026-10"), T), gn_name=gn,
                        create_tab=True, opening=ZERO)
    g.save()
    mon = openpyxl.load_workbook(p)["SHG Monitoring"]
    cells = [(mon.cell(r, 1), mon.cell(r, 2)) for r in range(2, mon.max_row + 1) if mon.cell(r, 2).value == rep.sheet]
    assert len(cells) == 29
    for a, b in cells:
        assert a.value == gn and b.value == rep.sheet
        assert a.data_type == b.data_type == "s" and a.quotePrefix and b.quotePrefix
    # an ordinary name stays an ordinary cell
    g = GNWorkbook(p, T)
    g.write_month("Nilmini", "2026-10", to_monthly(form("vasantham_2026-10"), T), gn_name="PTK East",
                  create_tab=True, opening=ZERO)
    mon = g.wb["SHG Monitoring"]
    row = next(r for r in range(2, mon.max_row + 1) if mon.cell(r, 2).value == "Nilmini")
    assert mon.cell(row, 1).value == "PTK East" and not mon.cell(row, 1).quotePrefix


# ====================================================================== P3: reader timeout
def test_reader_sets_a_per_request_timeout():
    seen = {}

    class Messages:
        def create(self, **kw):
            seen.update(kw)
            return NS(stop_reason="end_turn", content=[NS(type="text", text="{}")])
    ClaudeReader(client=NS(messages=Messages())).read([], "p", {})
    assert seen["timeout"] == 120


def test_reader_timeout_is_a_plain_message():
    class APITimeoutError(Exception):
        pass

    class Messages:
        def create(self, **kw):
            raise APITimeoutError("Request timed out.")
    with pytest.raises(ExtractionError, match="did not answer within 120 seconds"):
        ClaudeReader(client=NS(messages=Messages())).read([], "p", {})
