"""A realistic, internally consistent SHG month used by tests, the demo and the
synthetic-form generator. `make_month` builds the whole ledger week by week, so
every total, expected balance and running balance on the form is correct."""
from __future__ import annotations

from typing import Any, Optional

from .models import FieldValue, FormRecord, Legibility
from .schema import WEEKS, Template


def make_month(t: Template, *, shg: str = "Kalaimagal", gn: str = "Puthukkudiyiruppu East",
               month: str = "2026-10", members: int = 15, prior_cash: float = 12500,
               prior_savings: float = 84000, prior_outstanding: float = 61000,
               weeks: Optional[list[dict[str, Any]]] = None,
               write_off_in_expenses: bool = False, inactive: int = 1, overdue: int = 2,
               header: Optional[dict[str, Any]] = None,
               page2: Optional[dict[str, Any]] = None) -> FormRecord:
    """`header` / `page2` replace individual answers (keys without the 'header.' /
    'page2.' prefix; None leaves that answer blank), so each sample group can tell its
    own story without changing the default (Kalaimagal) month the tests rely on."""
    weeks = weeks or [
        dict(held=True, att=14, sav=3000, prin=2500, intr=300, oth=150, dist=6000, ig=5000, em=1000, ot=0, ref=0, wo=0, oexp=200, dep=0),
        dict(held=True, att=13, sav=2800, prin=2000, intr=280, oth=0, dist=0, ig=0, em=0, ot=0, ref=500, wo=0, oexp=0, dep=0),
        dict(held=True, att=15, sav=3000, prin=3000, intr=310, oth=100, dist=8000, ig=8000, em=0, ot=0, ref=0, wo=0, oexp=150, dep=0),
        dict(held=True, att=12, sav=2600, prin=2200, intr=270, oth=0, dist=0, ig=0, em=0, ot=0, ref=0, wo=0, oexp=0, dep=15000),
    ]
    rec = FormRecord(template_id=t.id)

    def put(fid: str, v: Any) -> None:
        rec.fields[fid] = FieldValue(value=v, raw=None if v is None else str(v),
                                     legibility=Legibility.blank if v is None else Legibility.clear)

    put("header.shg_name", shg)
    put("header.total_members", members)
    put("header.village_gn", gn)
    put("header.month_year", month)
    put("header.last_audit_date", "15/08/2026")
    put("header.graded_last_3_months", "Yes 02/09/2026")
    put("header.monthly_interest", "2%")
    put("header.constitution_updated", "01/2026")

    cash, sav_td, out = prior_cash, prior_savings, prior_outstanding
    totals: dict[str, float] = {}
    for i, wk in enumerate(WEEKS):
        w = weeks[i] if i < len(weeks) else None
        if w is None:
            continue
        inc = w["sav"] + w["prin"] + w["intr"] + w["oth"]
        exp = w["dist"] + w["ref"] + w["oexp"] + (w["wo"] if write_off_in_expenses else 0)
        expected = cash + inc - exp
        cash = expected                                # 'cash in hand' = box + SHG bank account
        sav_td += w["sav"]
        out += w["dist"] - w["prin"] - w["wo"]
        cells = {
            "meeting_held": bool(w["held"]), "attendance": w["att"],
            "savings": w["sav"], "savings_to_date": sav_td, "principal_repaid": w["prin"],
            "interest_repaid": w["intr"], "other_income": w["oth"], "loans_distributed": w["dist"],
            "loan_purpose_income": w["ig"], "loan_purpose_emergency": w["em"], "loan_purpose_other": w["ot"],
            "savings_refunded": w["ref"], "loans_outstanding": out, "write_offs": w["wo"],
            "other_expenses": w["oexp"], "total_income": inc, "total_loan": w["dist"],
            "total_expenses": exp, "expected_balance": expected, "cash_in_hand": cash,
            "cash_deposited_bank": w["dep"],
        }
        for k, v in cells.items():
            put(f"weekly.{k}.{wk}", None if (v == 0 and k not in ("attendance",)) and k in _ZERO_BLANK else v)
            if k in _FLOWS:
                totals[k] = totals.get(k, 0) + (v or 0)
    for k, v in totals.items():
        put(f"weekly.{k}.Total", v)
    put("weekly.loans_outstanding.Total", out)
    put("weekly.expected_balance.Total", cash)
    put("weekly.inactive_members.Total", inactive)
    put("weekly.members_loans_overdue.Total", overdue)

    put("page2.high_cash_reason", None)
    put("page2.overdue_members.0.name", "S. Tharshini")
    put("page2.overdue_members.0.amount_left", 4000)
    put("page2.overdue_members.0.months_overdue", 2)
    put("page2.overdue_members.0.last_meeting_attended", "W3")
    put("page2.overdue_members.1.name", "K. Vasuki")
    put("page2.overdue_members.1.amount_left", 2500)
    put("page2.overdue_members.1.months_overdue", 1)
    put("page2.overdue_members.1.last_meeting_attended", "W4")
    put("page2.social_work", "Helped clean the village well; visited a sick member")
    put("page2.members_with_goals", 11)
    put("page2.group_goal", "Save Rs 12,000 this month")
    put("page2.govt_ngo_support", "Palmera bookkeeping training on 14/10")
    put("page2.issues.0.issue", "Two members late with repayments")
    put("page2.issues.0.support_from_cluster", "Cluster rep to visit and agree a plan")
    for k, v in (header or {}).items():
        put(f"header.{k}", v)
    for k, v in (page2 or {}).items():
        put(f"page2.{k}", v)
    return rec


# cells people typically leave empty when the amount is zero
_ZERO_BLANK = {"other_income", "loans_distributed", "loan_purpose_income", "loan_purpose_emergency",
               "loan_purpose_other", "savings_refunded", "write_offs", "other_expenses",
               "cash_deposited_bank", "total_loan"}
_FLOWS = {"attendance", "savings", "principal_repaid", "interest_repaid", "other_income",
          "loans_distributed", "loan_purpose_income", "loan_purpose_emergency", "loan_purpose_other",
          "savings_refunded", "write_offs", "other_expenses", "total_income", "total_loan",
          "total_expenses"}
