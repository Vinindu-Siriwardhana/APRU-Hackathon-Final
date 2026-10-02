"""Short English names for every field id, for chips, issue lists and the audit trail
("Interest repaid, W3" instead of "Interest repayment (Rs.) — W3")."""
from __future__ import annotations

from .schema import Template

HEADER = {
    "shg_name": "SHG name", "total_members": "Members", "village_gn": "Village / GN",
    "month_year": "Month", "last_audit_date": "Last audit", "graded_last_3_months": "Graded (last 3 months)",
    "monthly_interest": "Monthly interest", "constitution_updated": "Constitution updated",
}
WEEKLY = {
    "meeting_held": "Meeting held", "attendance": "Attendance", "inactive_members": "Inactive members",
    "members_loans_overdue": "Members overdue", "savings": "Savings", "savings_to_date": "Savings to date",
    "principal_repaid": "Principal repaid", "interest_repaid": "Interest repaid", "other_income": "Other income",
    "loans_distributed": "Loans given", "loan_purpose_income": "Loans: income generation",
    "loan_purpose_emergency": "Loans: emergency", "loan_purpose_other": "Loans: other",
    "savings_refunded": "Savings refunded", "loans_outstanding": "Loans outstanding", "write_offs": "Write-offs",
    "other_expenses": "Other expenses", "total_income": "Total income", "total_loan": "Total loan",
    "total_expenses": "Total expenses", "expected_balance": "Expected balance", "cash_in_hand": "Cash in hand",
    "cash_deposited_bank": "Deposited in bank",
}
PAGE2 = {
    "high_cash_reason": "Reason for high cash", "social_work": "Social work", "members_with_goals": "Members with goals",
    "group_goal": "Group goal", "govt_ngo_support": "Government / NGO support",
    "signed_by_completer": "Completed by", "signed_by_cluster_rep": "Cluster representative",
}
TABLE_COLS = {"name": "name", "amount_left": "amount left", "months_overdue": "months overdue",
              "last_meeting_attended": "last meeting", "issue": "issue", "support_from_cluster": "support asked"}
TABLES = {"overdue_members": "Overdue member", "issues": "Issue"}


def short_label(t: Template, fid: str) -> str:
    parts = fid.split(".")
    try:
        if parts[0] == "header":
            return HEADER.get(parts[1]) or t.field_label(fid)
        if parts[0] == "weekly":
            return f"{WEEKLY.get(parts[1]) or t.weekly_row(parts[1]).label}, {parts[2]}"
        if parts[0] == "page2" and len(parts) == 4:
            return f"{TABLES.get(parts[1], parts[1])} {int(parts[2]) + 1}: {TABLE_COLS.get(parts[3], parts[3])}"
        if parts[0] == "page2":
            return PAGE2.get(parts[1]) or t.field_label(fid)
    except (KeyError, StopIteration, IndexError, ValueError):
        pass
    return fid
