"""Round 1 regression tests for the data-integrity core: validation, roll-up, workbook
writer and extraction. Many come from the backend review (review/backend/
test_review_regressions.py); each one failed on the reviewed snapshot."""
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import numpy as np
import openpyxl
import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from seed_demo_workbook import seed as _seed  # noqa: E402

from app import workbook as W
from app.aggregate import last_active_week, to_monthly
from app.extraction import ClaudeReader, ExtractionError, PageReadings, extract, merge, page1_schema
from app.models import FieldValue, FormRecord, Legibility, PriorMonth, normalise
from app.sample_data import make_month
from app.schema import load_template
from app.validation import Validator
from app.workbook import GNWorkbook, WorkbookError

T = load_template()
V = Validator(T)
SYN = ROOT / "samples" / "synthetic"
CASH = "Cash in Hand – at end of month (mother book) (Rs.)"
TEMPLATE_XLSX = ROOT / "samples" / "gn_workbook_template.xlsx"


def seed(path):
    """The demo workbook. Tab creation is explicit now (create_tab=True); default it here so
    these tests don't depend on the seeding tool's version."""
    orig = W.GNWorkbook.write_month

    def write_month(self, *a, **kw):
        kw.setdefault("create_tab", True)
        return orig(self, *a, **kw)
    with mock.patch.object(W.GNWorkbook, "write_month", write_month):
        return _seed(path)


def record(values):
    rec = FormRecord(template_id=T.id)
    for fid, v in values.items():
        rec.fields[fid] = FieldValue(value=v, raw=None if v is None else str(v), passes=[v, v],
                                     legibility=Legibility.blank if v is None else Legibility.clear)
    return rec


def month(**over):
    """A clean, balanced 4-week month following September cash Rs 12,500."""
    d = {"header.shg_name": "Kalaimagal", "header.total_members": 15,
         "header.village_gn": "Puthukkudiyiruppu East", "header.month_year": "2026-10"}
    cash = 12500
    for wk, (sav, prin, intr, loans) in zip(["W1", "W2", "W3", "W4"],
                                            [(3000, 2000, 300, 4000), (2800, 2000, 250, 0),
                                             (3000, 2400, 310, 5000), (2600, 2000, 200, 0)]):
        cash += sav + prin + intr - loans
        d.update({f"weekly.meeting_held.{wk}": True, f"weekly.attendance.{wk}": 13,
                  f"weekly.savings.{wk}": sav, f"weekly.principal_repaid.{wk}": prin,
                  f"weekly.interest_repaid.{wk}": intr, f"weekly.loans_distributed.{wk}": loans or None,
                  f"weekly.loan_purpose_income.{wk}": loans or None,
                  f"weekly.total_income.{wk}": sav + prin + intr, f"weekly.total_expenses.{wk}": loans,
                  f"weekly.expected_balance.{wk}": cash, f"weekly.cash_in_hand.{wk}": cash})
    d.update(over)
    return d


PRIOR = PriorMonth(month="2026-09", cash_in_hand=12500, members=15)


def rules(res, sev="error"):
    return {i.rule for i in res.issues if i.severity.value == sev}


def truth(case):
    return json.loads((SYN / f"{case}.truth.json").read_text(encoding="utf-8"))


def read_as(case, errors=None):
    """A record as the two readings would produce it from a synthetic form (every fillable
    cell present), with planted misreads like api.DEMO_ERRORS."""
    tr, errors = truth(case), errors or {}
    rec = FormRecord(template_id=T.id)
    for fid in T.all_field_ids():
        v = tr.get(fid)
        passes, leg = [v, v], ("clear" if v is not None else "blank")
        if fid in errors:
            e = errors[fid]
            nv = normalise(e["raw"], T.field_type(fid))
            passes = [nv, nv] if e["pass"] == "both" else [v, nv] if e["pass"] == 1 else [nv, v]
            leg = e.get("legibility", "clear")
        rec.fields[fid] = FieldValue(value=passes[0], raw=None if passes[0] is None else str(passes[0]),
                                     passes=passes, legibility=Legibility(leg))
    return rec


def officer_sets(rec, fid, value):
    """What officer_set does to a field (value confirmed against the photo)."""
    fv = rec.fields[fid]
    fv.value, fv.passes, fv.legibility = value, [value], Legibility.clear


DEMO = {"weekly.savings.W2": {"pass": 1, "raw": "2300"},
        "weekly.interest_repaid.W3": {"pass": "both", "raw": "810"}}


@pytest.fixture(scope="module")
def demo_wb(tmp_path_factory):
    return seed(tmp_path_factory.mktemp("wb") / "gn.xlsx")


@pytest.fixture
def wbpath(tmp_path):
    return seed(tmp_path / "gn.xlsx")


# ====================================================================== parsing
@pytest.mark.parametrize("raw,ftype,expected", [
    ("Rs.3,000/=", "money", 3000), ("3000/=", "money", 3000), ("2500=", "money", 2500),
    ("Rs. 2,500/-", "money", 2500), ("1,00,000", "money", 100000), ("1250.50", "money", 1250.5),
    ("௧௨௦௦", "money", 1200), ("-", "money", None), ("12.0", "int", 12),
])
def test_number_parsing(raw, ftype, expected):
    assert normalise(raw, ftype) == expected


@pytest.mark.parametrize("raw,ftype", [
    ("1.2", "int"), ("300 310", "money"), ("12.000", "money"), ("1,50", "money"),
    ("15 members", "int"), (True, "money"), ("2?00", "money"), ("1", "yesno"), ("4", "yesno"),
])
def test_ambiguous_numbers_are_refused_not_guessed(raw, ftype):
    with pytest.raises(ValueError):
        normalise(raw, ftype)


def test_meeting_row_total_is_not_a_field():
    assert "weekly.meeting_held.Total" not in T.all_field_ids()
    assert "weekly.meeting_held.W5" in T.all_field_ids()


# ====================================================================== validation rules
def test_unparseable_cell_is_flagged_not_crash():
    rec = record(month())
    rec.fields["weekly.savings.W2"] = FieldValue(value="2?00", raw="2?00", passes=["2?00", "2?00"],
                                                 legibility=Legibility.illegible)
    res = V.validate(rec, PRIOR)
    assert "weekly.savings.W2" in res.flagged


def test_unreadable_cell_gets_its_value_from_the_ledger():
    """Illegible -> no value; the sums say what it must be."""
    rec = record(month())
    rec.fields["weekly.savings.W2"] = FieldValue(value=None, raw="2?00", passes=[None, None],
                                                 legibility=Legibility.illegible)
    res = V.validate(rec, PRIOR)
    top = res.likely[0]
    assert top.field == "weekly.savings.W2" and top.suggest == 2800 and top.balances >= 2


def test_blank_cash_week_does_not_break_expected_balance_chain():
    res = V.validate(record(month(**{"weekly.cash_in_hand.W2": None})), PRIOR)
    assert "expected_balance" not in rules(res)


def test_blank_cash_and_expected_week_is_worked_out():
    """W2 cash AND expected blank: W3 is checked against W1 cash + W2's flows, not W1 cash alone."""
    res = V.validate(record(month(**{"weekly.cash_in_hand.W2": None, "weekly.expected_balance.W2": None})), PRIOR)
    assert "expected_balance" not in rules(res)
    rec = record(month(**{"weekly.cash_in_hand.W2": None, "weekly.expected_balance.W2": None,
                          "weekly.savings.W2": 2300, "weekly.total_income.W2": None}))
    res = V.validate(rec, PRIOR)
    eb = [i for i in res.errors if i.rule == "expected_balance"]
    assert eb and "weekly.savings.W2" in eb[0].fields


def test_expense_definition_per_week():
    d = month(**{"weekly.write_offs.W3": 1000, "weekly.total_expenses.W3": 6000})
    for wk in ("W3", "W4"):
        d[f"weekly.expected_balance.{wk}"] -= 1000
        d[f"weekly.cash_in_hand.{wk}"] -= 1000
    assert "expected_balance" not in rules(V.validate(record(d), PRIOR))


def test_month_gap_does_not_use_older_cash_as_last_month():
    res = V.validate(record(month()), PriorMonth(month="2026-08", cash_in_hand=10400, members=15))
    assert "expected_balance" not in rules(res)
    gap = [i for i in res.issues if i.rule == "month_gap"]
    assert gap and gap[0].severity.value == "warning"
    assert gap[0].message.startswith("The last month recorded is August 2026, so September 2026 is missing.")


def test_month_already_recorded_from_workbook_flag():
    res = V.validate(record(month()), PRIOR.model_copy(update={"this_month_recorded": True}))
    assert "month_already_recorded" in rules(res)
    res = V.validate(record(month()), PriorMonth(this_month_recorded=True))     # month 1 of a tab
    assert "month_already_recorded" in rules(res)


def test_total_column_uses_week_sums_when_part_totals_blank():
    res = V.validate(record(month(**{"weekly.loans_distributed.Total": 9000})), PRIOR)
    assert "loan_purpose_split" not in rules(res)
    res = V.validate(record(month(**{"weekly.total_income.Total": 20860})), PRIOR)
    assert "total_income" not in rules(res)


def test_stale_month_end_cash_is_blocking_and_never_written():
    rec = record(month(**{"weekly.cash_in_hand.W4": None}))
    res = V.validate(rec, PRIOR)
    miss = [i for i in res.errors if i.rule == "month_end_cash_missing"]
    assert miss and miss[0].fields == ["weekly.cash_in_hand.W4"]
    assert to_monthly(rec, T)[CASH] is None


def test_last_active_week_ignores_a_lone_no():
    d = month(**{"weekly.meeting_held.W5": False})
    assert last_active_week(record(d)) == "W4"
    assert "month_end_cash_missing" not in rules(V.validate(record(d), PRIOR))


def test_month_end_cash_mismatch_blocks_but_midmonth_is_a_finding():
    res = V.validate(record(month(**{"weekly.cash_in_hand.W4": 26160 + 1000})), PRIOR)
    assert "month_end_cash_mismatch" in rules(res)
    rec = record(month())
    rec.fields["weekly.cash_in_hand.W2"].value -= 700
    res = V.validate(rec, PRIOR)
    assert "cash_mismatch" in rules(res, "warning") and "month_end_cash_mismatch" not in rules(res)


def test_attendance_without_meeting_flag_blocks():
    res = V.validate(record(month(**{"weekly.meeting_held.W1": None})), PRIOR)
    assert "meeting_flag_missing" in rules(res)


def test_attendance_above_capacity():
    d = month(**{f"weekly.attendance.{wk}": 15 for wk in ("W1", "W2", "W3", "W4")})
    d["weekly.meeting_held.W4"] = False
    d["weekly.attendance.W4"] = 0
    assert "attendance_above_capacity" not in rules(V.validate(record(d), PRIOR))
    d["header.total_members"] = 14
    res = V.validate(record(d), PRIOR)
    cap = [i for i in res.errors if i.rule == "attendance_above_capacity"]
    assert cap and "allows at most 42" in cap[0].message


def test_monthly_value_above_palmera_max_is_flagged():
    d = month()
    shift = 0
    for wk in ("W1", "W2", "W3", "W4"):
        delta = 30000 - d[f"weekly.interest_repaid.{wk}"]; shift += delta
        d[f"weekly.interest_repaid.{wk}"] = 30000; d[f"weekly.total_income.{wk}"] += delta
        d[f"weekly.expected_balance.{wk}"] += shift; d[f"weekly.cash_in_hand.{wk}"] += shift
    res = V.validate(record(d), PRIOR)
    msgs = [i.message for i in res.errors if i.rule == "above_max"]
    assert msgs == ["Interest repayment for the month adds up to Rs 120,000, above Palmera's maximum of Rs 100,000."]


def test_savings_to_date_kept_net_of_earlier_refunds_is_accepted():
    prior = PRIOR.model_copy(update={"savings_to_date": 84000, "savings_refunded_to_date": 500})
    net = 83500
    d = month()
    for wk, s in zip(["W1", "W2", "W3", "W4"], [3000, 2800, 3000, 2600]):
        net += s
        d[f"weekly.savings_to_date.{wk}"] = net
    assert "savings_to_date" not in rules(V.validate(record(d), prior))
    d["weekly.savings_to_date.W2"] += 100
    assert "savings_to_date" in rules(V.validate(record(d), prior))


# ====================================================================== complete fields
def test_expected_balance_lists_every_contributing_cell():
    """'Checked as written' only clears a check once EVERY cell it depends on was checked."""
    rec = record(month(**{"weekly.interest_repaid.W3": 810, "weekly.total_income.W3": None}))
    res = V.validate(rec, PRIOR)
    eb = next(i for i in res.errors if i.rule == "expected_balance")
    expected = {"weekly.expected_balance.W3", "weekly.cash_in_hand.W2"} | {
        f"weekly.{k}.W3" for k in ("savings", "principal_repaid", "interest_repaid", "other_income",
                                   "loans_distributed", "savings_refunded", "other_expenses", "write_offs")}
    assert expected <= set(eb.fields)
    assert eb.fields[0] == "weekly.expected_balance.W3"
    assert eb.suggest["weekly.interest_repaid.W3"] == 310


def test_checked_as_written_cannot_skip_the_culprit():
    """The officer confirms the two cells the old check listed: the check still lists
    interest W3, which nobody looked at, so it can't be downgraded."""
    rec = record(month(**{"weekly.interest_repaid.W3": 810, "weekly.total_income.W3": None}))
    res = V.validate(rec, PRIOR)
    checked = {"weekly.expected_balance.W3", "weekly.cash_in_hand.W2"}
    eb = next(i for i in res.errors if i.rule == "expected_balance")
    assert not set(eb.fields) <= checked


def test_running_balance_checks_list_refunds_and_write_offs():
    prior = PRIOR.model_copy(update={"savings_to_date": 84000, "loans_outstanding": 61000})
    d = month(**{"weekly.savings_to_date.W1": 99999, "weekly.loans_outstanding.W1": 99999})
    res = V.validate(record(d), prior)
    sav = next(i for i in res.errors if i.rule == "savings_to_date")
    out = next(i for i in res.errors if i.rule == "loans_outstanding")
    assert "weekly.savings_refunded.W1" in sav.fields
    assert "weekly.write_offs.W1" in out.fields


def test_suggestions_are_never_negative():
    res = V.validate(record(month(**{"weekly.interest_repaid.W3": 810})), PRIOR)
    assert all(v >= 0 for i in res.issues for v in i.suggest.values())


# ====================================================================== likely ranking
def test_demo_misread_ranks_first_with_its_true_value(demo_wb):
    """Kalaimagal demo: interest W3 read as 810 by BOTH passes (paper: 310), savings W2 read
    as 2800 / 2300. The officer view must open on interest W3 with 'Use 310'."""
    rec = read_as("kalaimagal_2026-10", DEMO)
    wb = GNWorkbook(demo_wb, T)
    res = V.validate(rec, wb.prior_month("Kalaimagal", "2026-10"))
    top = res.likely[0]
    assert top.field == "weekly.interest_repaid.W3"
    assert top.suggest == 310 and top.balances >= 3 and top.checks >= 3
    order = [l.field for l in res.likely]
    sav = res.likely[order.index("weekly.savings.W2")]
    assert order.index("weekly.savings.W2") > 0
    assert sav.suggest == 2800 and sav.balances == 1          # the reading the ledger supports
    # the officer uses 310: savings W2 is now the first (and only) thing left
    officer_sets(rec, "weekly.interest_repaid.W3", 310)
    res = V.validate(rec, wb.prior_month("Kalaimagal", "2026-10"))
    assert [l.field for l in res.likely] == ["weekly.savings.W2"] and res.likely[0].suggest == 2800
    officer_sets(rec, "weekly.savings.W2", 2800)
    assert V.validate(rec, wb.prior_month("Kalaimagal", "2026-10")).auto_accept


def test_disagreement_the_ledger_cannot_settle_gets_no_suggestion():
    rec = record(month())
    rec.fields["header.total_members"].passes = [15, 16]          # nothing adds members up
    res = V.validate(rec, PRIOR)
    assert res.likely[0].field == "header.total_members" and res.likely[0].suggest is None


def test_unclear_cell_backed_by_the_ledger_suggests_itself(demo_wb):
    rec = read_as("sisila_2026-10", {"weekly.principal_repaid.W4": {"pass": "both", "raw": "1200",
                                                                     "legibility": "unclear"}})
    res = V.validate(rec, GNWorkbook(demo_wb, T).prior_month("Sisila", "2026-10"))
    assert res.likely[0].field == "weekly.principal_repaid.W4" and res.likely[0].suggest == 1200


def test_finish_reranks_after_the_pipeline_downgrades():
    rec = record(month(**{"weekly.interest_repaid.W3": 810}))
    res = V.validate(rec, PRIOR)
    for i in res.errors:
        i.severity = i.severity.warning
    V.finish(rec, res, PRIOR)
    assert res.likely == [] and res.flagged == {}


# ====================================================================== clean samples
@pytest.mark.parametrize("case", ["kalaimagal_2026-10", "sisila_2026-10", "vasantham_2026-10"])
def test_clean_synthetic_samples_have_no_blocking_issue(case, demo_wb):
    rec = read_as(case)
    wb = GNWorkbook(demo_wb, T)
    tab, _ = wb.find_shg(rec.get("header.shg_name"))
    prior = wb.prior_month(tab, rec.get("header.month_year"))
    assert prior.month == "2026-09" and not prior.this_month_recorded
    res = V.validate(rec, prior)
    assert res.auto_accept, [i.message for i in res.errors]


def test_november_follows_october_written_to_the_workbook(wbpath):
    wb = GNWorkbook(wbpath, T)
    wb.write_month("Kalaimagal", "2026-10", to_monthly(read_as("kalaimagal_2026-10"), T))
    wb.save()
    wb = GNWorkbook(wbpath, T)
    assert wb.month_recorded("Kalaimagal", "2026-10")
    prior = wb.prior_month("Kalaimagal", "2026-11")
    assert prior.month == "2026-10" and prior.cash_in_hand == 20160
    res = V.validate(read_as("kalaimagal_2026-11"), prior)
    assert res.auto_accept, [i.message for i in res.errors]
    again = wb.prior_month("Kalaimagal", "2026-10")
    assert again.this_month_recorded
    assert "month_already_recorded" in rules(V.validate(read_as("kalaimagal_2026-10"), again))


def test_five_week_month():
    weeks = [dict(held=True, att=12, sav=2000, prin=1000, intr=100, oth=0, dist=0, ig=0, em=0, ot=0,
                  ref=0, wo=0, oexp=0, dep=0) for _ in range(5)]
    rec = make_month(T, weeks=weeks)
    prior = PriorMonth(month="2026-09", cash_in_hand=12500, savings_to_date=84000,
                       loans_outstanding=61000, members=15)
    res = V.validate(rec, prior)
    assert res.auto_accept, [i.message for i in res.errors]
    m = to_monthly(rec, T)
    assert m["Total number of meetings held"] == 5 and m["Savings (Rs.)"] == 10000
    assert m[CASH] == rec.get("weekly.cash_in_hand.W5") == 12500 + 5 * 3100


# ====================================================================== workbook
def test_unknown_group_needs_explicit_new_group(tmp_path):
    p = tmp_path / "gn.xlsx"; shutil.copy(TEMPLATE_XLSX, p)
    wb = GNWorkbook(p, T)
    with pytest.raises(WorkbookError, match="confirm it as a new group first"):
        wb.write_month("கலைமகள்", "2026-10", to_monthly(make_month(T), T), gn_name="X")
    assert wb.write_month("கலைமகள்", "2026-10", to_monthly(make_month(T), T), gn_name="X",
                          create_tab=True).created_tab


def test_month_recorded_and_prior_in_first_column(wbpath):
    wb = GNWorkbook(wbpath, T)
    assert wb.month_recorded("Kalaimagal", "2026-06") and not wb.month_recorded("Kalaimagal", "2026-10")
    p = wb.prior_month("Kalaimagal", "2026-06")                 # June is column C: nothing before
    assert p.month is None and p.this_month_recorded


def test_prior_walks_back_over_a_missing_month(wbpath):
    wb = GNWorkbook(wbpath, T)
    p = wb.prior_month("Kalaimagal", "2026-11")                 # October not entered
    assert p.month == "2026-09" and p.cash_in_hand == 12500 and not p.this_month_recorded
    assert p.savings_refunded_to_date is not None


def test_missing_required_row_fails_the_write(wbpath):
    wb = openpyxl.load_workbook(wbpath); wb["Mapping"]["C16"] = "Loan write off (Rs.)"; wb.save(wbpath)
    g = GNWorkbook(wbpath, T)
    with pytest.raises(WorkbookError, match="Loan right off"):
        g.write_month("Kalaimagal", "2026-10", to_monthly(make_month(T), T))
    assert not GNWorkbook(wbpath, T).month_recorded("Kalaimagal", "2026-10")


def test_optional_row_is_skipped_and_none_is_never_written(wbpath):
    g = GNWorkbook(wbpath, T)
    vals = to_monthly(make_month(T), T)
    vals[CASH] = None
    rep = g.write_month("Kalaimagal", "2026-10", vals)
    assert "Number of members who attended the last meeting" in rep.skipped
    assert any(CASH in w for w in rep.warnings)
    assert all(w.label != CASH for w in rep.writes)


def test_save_is_atomic_and_opens_on_the_written_tab(wbpath):
    g = GNWorkbook(wbpath, T)
    g.write_month("Sisila", "2026-10", to_monthly(make_month(T, shg="Sisila"), T))
    g.save()
    assert [p.name for p in wbpath.parent.iterdir() if p.name.startswith(".")] == []
    wb = openpyxl.load_workbook(wbpath)
    assert wb.active.title == "Sisila"
    assert [ws.title for ws in wb.worksheets if ws.sheet_view.tabSelected] == ["Sisila"]


def test_excel_lock_becomes_a_plain_message(wbpath, monkeypatch):
    g = GNWorkbook(wbpath, T)
    monkeypatch.setattr(W.os, "replace", mock.Mock(side_effect=PermissionError("locked")))
    with pytest.raises(WorkbookError, match=r"Close gn.xlsx in Excel and try again"):
        g.save()
    assert [p.name for p in wbpath.parent.iterdir() if p.name.startswith(".")] == []


def test_new_tab_monitoring_array_formulas_are_translated(wbpath):
    mon = openpyxl.load_workbook(wbpath)["SHG Monitoring"]
    v = mon["C32"].value
    assert getattr(v, "ref", None) == "C32" and 'C31="Not started"' in v.text


def test_new_tab_keeps_conditional_formatting(wbpath):
    wb = openpyxl.load_workbook(wbpath)
    assert len(list(wb["Kalaimagal"].conditional_formatting)) == \
        len(list(wb["<name of SHG>"].conditional_formatting)) == 2


def test_stray_text_in_an_input_cell(wbpath):
    wb = openpyxl.load_workbook(wbpath); wb["Kalaimagal"]["E7"] = "-"; wb["Vasantham"]["E7"] = "N/A?"
    wb.save(wbpath)
    g = GNWorkbook(wbpath, T)
    assert g.prior_month("Kalaimagal", "2026-10").month == "2026-09"     # a dash is a blank
    g.series("Kalaimagal")
    with pytest.raises(WorkbookError, match=r"Vasantham!E7 holds 'N/A\?'"):
        g.prior_month("Vasantham", "2026-10")


def test_long_and_odd_group_names(tmp_path):
    p = tmp_path / "gn.xlsx"; shutil.copy(TEMPLATE_XLSX, p)
    g = GNWorkbook(p, T)
    vals = to_monthly(make_month(T), T)
    long = "Kalaimagal Women's Development Society"
    g.write_month(long, "2026-10", vals, gn_name="X", create_tab=True)
    rep = g.write_month(long, "2026-11", vals)                  # found again despite the 31-char cut
    assert rep.column == "D" and not rep.created_tab and len(rep.sheet) <= 31 and "'" not in rep.sheet
    rep = g.write_month("Ruhunu/Pola 2", "2026-10", vals, gn_name="X", create_tab=True)
    assert rep.sheet == "Ruhunu-Pola 2"
    g.save()


def test_year_rollover_column(tmp_path):
    p = tmp_path / "gn.xlsx"; shutil.copy(TEMPLATE_XLSX, p)
    g = GNWorkbook(p, T)
    vals = to_monthly(make_month(T), T)
    assert g.write_month("Kalaimagal", "2026-11", vals, gn_name="X", create_tab=True).column == "C"
    g.write_month("Kalaimagal", "2026-12", vals)
    rep = g.write_month("Kalaimagal", "2027-01", vals)
    assert rep.column == "E"
    assert g.prior_month("Kalaimagal", "2027-02").month == "2027-01"


# ====================================================================== extraction
def _resp(stop, text):
    return NS(stop_reason=stop, content=[] if text is None else [NS(type="text", text=text)])


@pytest.mark.parametrize("resp,match", [
    (_resp("refusal", None), "declined"),
    (_resp("max_tokens", '{"header": [{"key": "shg_na'), "cut off"),
    (_resp("end_turn", "not json"), "not valid JSON"),
    (_resp("end_turn", None), "no answer"),
])
def test_reader_failures_are_typed(resp, match):
    r = ClaudeReader(client=NS(messages=NS(create=lambda **kw: resp)))
    with pytest.raises(ExtractionError, match=match):
        r.read([np.full((50, 50, 3), 255, np.uint8)], "p", page1_schema(T))


def test_api_error_is_typed():
    def boom(**kw):
        raise ConnectionError("network down")
    r = ClaudeReader(client=NS(messages=NS(create=boom)))
    with pytest.raises(ExtractionError, match="could not be reached"):
        r.read([np.full((50, 50, 3), 255, np.uint8)], "p", page1_schema(T))


FAKE_LOC = NS(weekly_ink=lambda al: {}, field_box=lambda al, fid: None)


def test_merge_keeps_unparseable_raw_and_creates_every_editable_cell():
    reading = {"header": [{"key": "shg_name", "raw": "Kalaimagal", "legibility": "clear"}],
               "table": [{"key": "savings", **{c: {"raw": "", "legibility": "blank"} for c in
                                               ["W1", "W2", "W3", "W4", "W5", "Total"]},
                          "W2": {"raw": "2?00", "legibility": "clear"}}]}
    rec = merge(T, FAKE_LOC, [PageReadings(page=1, passes=[reading, reading], alignment=None)])
    fv = rec.fields["weekly.savings.W2"]
    assert fv.value is None and fv.raw == "2?00" and fv.legibility == Legibility.illegible
    assert "header.month_year" in rec.fields                     # omitted by both readings, still editable
    assert "weekly.interest_repaid.W4" in rec.fields
    assert "weekly.cash_in_hand.Total" not in rec.fields         # shaded on the form
    assert "weekly.meeting_held.Total" not in rec.fields
    V.validate(rec)                                              # no crash


def test_extract_wraps_reader_errors():
    class Broken:
        def read(self, *a):
            raise RuntimeError("Offline demo mode only knows the sample photos.")
    with pytest.raises(ExtractionError, match="page 1"):
        extract(T, NS(), {}, Broken())                           # no page 1 at all
    al = NS(image=np.full((10, 10, 3), 255, np.uint8))
    with mock.patch("app.extraction.page_view", lambda al: al.image), \
            mock.patch("app.extraction.table_views", lambda loc, al: [al.image]):
        with pytest.raises(ExtractionError, match="only knows the sample photos"):
            extract(T, NS(), {1: al}, Broken())
