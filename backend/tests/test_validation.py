import pytest

from app.models import FieldStatus, Legibility, PriorMonth, normalise, normalise_month
from app.sample_data import make_month
from app.schema import load_template
from app.validation import Validator

T = load_template()
V = Validator(T)
PRIOR = PriorMonth(month="2026-09", cash_in_hand=12500, savings_to_date=84000,
                   loans_outstanding=61000, members=15)


def rules(res):
    return sorted({i.rule for i in res.issues})


def test_template_shape():
    assert T.table_shape == (28, 7)
    assert len(T.weekly) == 23
    assert "weekly.savings.W5" in T.all_field_ids()
    assert "weekly.cash_in_hand.Total" not in T.all_field_ids()     # shaded on the form
    assert "weekly.inactive_members.W1" not in T.all_field_ids()    # shaded on the form


def test_clean_month_is_auto_accepted():
    res = V.validate(make_month(T), PRIOR)
    assert res.auto_accept, [i.message for i in res.errors]
    assert res.notes["total_expenses_definition"] == "loans_distributed+savings_refunded+other_expenses"


def test_write_off_variant_of_total_expenses_accepted():
    weeks = [dict(held=True, att=14, sav=3000, prin=2500, intr=300, oth=0, dist=0, ig=0, em=0, ot=0,
                  ref=0, wo=1000, oexp=0, dep=0)]
    res = V.validate(make_month(T, weeks=weeks, write_off_in_expenses=True, prior_outstanding=61000), PRIOR)
    assert res.auto_accept, [i.message for i in res.errors]
    assert "write_offs" in res.notes["total_expenses_definition"]


def test_passes_disagree_flags_field():
    rec = make_month(T)
    rec.fields["weekly.savings.W2"].passes = [2800, 2300]
    res = V.validate(rec, PRIOR)
    assert "passes_disagree" in rules(res)
    assert "weekly.savings.W2" in res.flagged


def test_unclear_handwriting_flags_field():
    rec = make_month(T)
    rec.fields["weekly.interest_repaid.W3"].legibility = Legibility.unclear
    res = V.validate(rec, PRIOR)
    assert res.flagged["weekly.interest_repaid.W3"] == ["unclear_handwriting"]


def test_misread_digit_is_caught_by_arithmetic():
    """A 3000 read as 8000 — both passes agree, model is confident. The ledger still catches it."""
    rec = make_month(T)
    rec.set("weekly.savings.W3", 8000, passes=[8000, 8000])
    res = V.validate(rec, PRIOR)
    assert {"row_total", "total_income", "savings_to_date", "expected_balance"} <= set(rules(res))
    assert "weekly.savings.W3" in res.flagged
    assert not res.auto_accept


def test_loan_purpose_split():
    rec = make_month(T)
    rec.set("weekly.loan_purpose_emergency.W1", 1500)
    res = V.validate(rec, PRIOR)
    assert "loan_purpose_split" in rules(res)


def test_expected_balance_uses_last_months_cash():
    res = V.validate(make_month(T), PRIOR.model_copy(update={"cash_in_hand": 10000}))
    msgs = [i.message for i in res.issues if i.rule == "expected_balance"]
    assert msgs and "last month's closing cash" in msgs[0]


def test_cash_short_is_a_finding_not_an_error():
    rec = make_month(T)
    rec.set("weekly.cash_in_hand.W2", rec.get("weekly.cash_in_hand.W2") - 700)
    res = V.validate(rec, PRIOR)
    short = [i for i in res.issues if i.rule == "cash_mismatch"]
    assert short and short[0].severity.value == "warning" and "Rs 700 less" in short[0].message


def test_loans_outstanding_running_balance():
    rec = make_month(T)
    rec.set("weekly.loans_outstanding.W3", 70000)
    assert "loans_outstanding" in rules(V.validate(rec, PRIOR))


def test_attendance_checks():
    rec = make_month(T)
    rec.set("weekly.attendance.W1", 18)
    rec.set("weekly.meeting_held.W2", False)
    r = rules(V.validate(rec, PRIOR))
    assert "attendance_above_members" in r and "attendance_without_meeting" in r


def test_duplicate_month_and_gap():
    assert "month_already_recorded" in rules(V.validate(make_month(T, month="2026-09"), PRIOR))
    # round 2: a skipped month blocks (month_unexpected) until an officer confirms the month
    assert "month_unexpected" in rules(V.validate(make_month(T, month="2026-11"), PRIOR))
    rec = make_month(T, month="2026-11")
    rec.fields["header.month_year"].status = FieldStatus.officer_confirmed
    assert "month_gap" in rules(V.validate(rec, PRIOR))


def test_required_header():
    rec = make_month(T)
    rec.set("header.shg_name", None)
    assert "required_missing" in rules(V.validate(rec, PRIOR))


def test_findings():
    rec = make_month(T, members=6)
    rec.set("weekly.attendance.W1", 2); rec.set("weekly.attendance.W2", 2)
    rec.set("weekly.attendance.W3", 2); rec.set("weekly.attendance.W4", 2)
    rec.set("weekly.attendance.Total", 8)
    r = rules(V.validate(rec, PRIOR))
    assert "high_overdue_share" in r and "low_attendance" in r


def test_deposit_above_cash():
    rec = make_month(T)
    rec.set("weekly.cash_deposited_bank.W4", 999999)
    assert "deposit_above_cash" in rules(V.validate(rec, PRIOR))


@pytest.mark.parametrize("raw,ftype,expected", [
    ("1,500", "money", 1500), ("Rs. 2500/-", "money", 2500), ("රු. 300", "money", 300),
    ("-", "money", None), ("ஆம்", "yesno", True), ("නැත", "yesno", False), ("✓", "yesno", True),
    ("12", "int", 12),
])
def test_normalise(raw, ftype, expected):
    assert normalise(raw, ftype) == expected


@pytest.mark.parametrize("raw,expected", [
    ("10/2026", "2026-10"), ("Oct 2026", "2026-10"), ("october-26", "2026-10"), ("2026/10", "2026-10"),
])
def test_normalise_month(raw, expected):
    assert normalise_month(raw) == expected
