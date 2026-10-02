"""Palmera's GN workbook template + three demo SHGs with June–September 2026 recorded.

Each group's history is built backwards from its September month-end position (the
position the synthetic October forms follow on from: opening cash, savings to date and
loans outstanding), so every month balances in Palmera's own formulas: mother-book
cash (row 19) = 'cash from app' (row 20). Each group has its own story for the trends view:
  Kalaimagal  steady, healthy
  Vasantham   a younger group that is growing: new members, savings up every month
  Sisila      attendance and repayments slipping (should raise early warnings)

The workbook opens on the Kalaimagal tab (the demo's first report).

    python tools/seed_demo_workbook.py out.xlsx
    python tools/seed_demo_workbook.py --check      # print each month's cash check
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.schema import load_template  # noqa: E402
from app.workbook import GNWorkbook  # noqa: E402

MONTHS = ["2026-06", "2026-07", "2026-08", "2026-09"]

# per month: meetings, attendance, savings, principal, interest, other income,
#            emergency share of loans, savings refunded, other expenses.
# Loans distributed are whatever keeps month-end cash on the group's `cash` path —
# groups lend out most of what they collect. `members` is one number, or one per month.
# `lifetime` = principal, interest and other income received before June (mother book).
GROUPS = {
    "Kalaimagal": dict(gn="Puthukkudiyiruppu East", members=15, sep_savings=84000, sep_outstanding=61000,
        cash=[11800, 12900, 10400, 12500],
        months=[(4, 55, 10800, 8200, 950, 150, 0.1, 0, 250),
                (4, 54, 11000, 8600, 980, 0, 0.0, 500, 200),
                (5, 68, 11500, 9000, 1010, 200, 0.15, 0, 300),
                (4, 55, 11200, 9400, 1040, 100, 0.0, 0, 250)]),
    # Must match tools/make_synthetic_forms.py (Vasantham October): September ends with
    # cash 9,340, savings to date 52,600, loans outstanding 42,000 and 18 members.
    "Vasantham": dict(gn="Mullaitivu Town", members=[16, 17, 17, 18], sep_savings=52600, sep_outstanding=42000,
        cash=[7400, 8020, 8850, 9340], june_loans=8000, lifetime=(30000, 2400, 900),
        months=[(4, 58, 7200, 4200, 340, 300, 0.0, 0, 150),
                (4, 63, 8100, 5000, 470, 200, 0.1, 0, 150),
                (4, 65, 9300, 6100, 630, 0, 0.0, 0, 200),
                (5, 84, 10600, 7100, 840, 200, 0.15, 0, 250)]),
    "Sisila": dict(gn="Kotmale North", members=12, sep_savings=40000, sep_outstanding=22000,
        cash=[5200, 5900, 6800, 8000],
        months=[(4, 45, 4800, 4200, 420, 100, 0.0, 0, 100),
                (4, 41, 4500, 3600, 380, 0, 0.25, 0, 150),
                (4, 36, 3900, 2900, 330, 0, 0.0, 0, 100),
                (3, 27, 3100, 2100, 260, 0, 1.0, 500, 100)]),
}
OPENING_TAB = "Kalaimagal"

INACTIVE = "Number of people who are inactive – waiting to pay loans off and then leave, or to leave for another reason"
OTHER_INC = "Other income (Membership fees, Other NGO funds, Fines, Social fund, Other) (Rs.)"
OTHER_EXP = "Other expenses (Interest refunded, Community / members support, CLA fee, Admin expenses & other) (Rs.)"
CASH = "Cash in Hand – at end of month (mother book) (Rs.)"


def monthly_rows(m, members, cash, dist):
    meet, att, sav, prin, intr, oth, em_share, ref, oexp = m
    em = int(round(dist * em_share, -2))
    ig = dist - em
    return {
        "Total number of meetings held": meet, "Number of SHG members": members,
        "Total attendance for the month": att, INACTIVE: 1,
        "Savings (Rs.)": sav, "Principal loan repayments (Rs.)": prin, "Interest repayment (Rs.)": intr,
        OTHER_INC: oth, "Loans distributed (Rs.)": ig + em, "Loan Purpose – Income generation (Rs.)": ig,
        "Loan Purpose – Emergency (Rs.)": em, "Loan Purpose – Other (Rs.)": 0, "Savings refunded (Rs.)": ref,
        OTHER_EXP: oexp, "Loan right off (Rs.)": 0, CASH: cash,
    }


def history(name: str, g: dict) -> tuple[list[dict], dict]:
    """The four months to write (June first) and June's opening 'to date' totals."""
    ms, cash = g["months"], g["cash"]
    members = g["members"] if isinstance(g["members"], list) else [g["members"]] * 4
    # loans distributed each month = what keeps cash on its path (month 1 has no prior)
    dist = [0] * 4
    for i in range(1, 4):
        meet, att, sv, p, it, o, em_share, r, e = ms[i]
        dist[i] = cash[i - 1] + (sv + p + it + o) - (r + e) - cash[i]
        assert dist[i] >= 0, (name, i, dist[i])
    dist[0] = g.get("june_loans", 9000)
    sav = [0] * 4; outst = [0] * 4
    sav[3], outst[3] = g["sep_savings"], g["sep_outstanding"]
    for i in range(3, 0, -1):
        sav[i - 1] = sav[i] - ms[i][2]
        outst[i - 1] = outst[i] - dist[i] + ms[i][3]
    # June is month 1: lifetime totals chosen so Palmera's cash formula balances
    P, I, O = g.get("lifetime", (90000, 8000, 1500))
    L = outst[0] + P
    R = 10000
    E = I + O - R - (cash[0] - sav[0] + outst[0])
    while E < 500:
        R -= 1000
        E = I + O - R - (cash[0] - sav[0] + outst[0])
    opening = {
        "Total savings to date (Rs.)": sav[0], "Total Principal loan repayments to date (Rs.)": P,
        "Total Interest repayments to date (Rs.)": I, "Total Other income to date (Rs.)": O,
        "Total Loans distributed to date (Rs.)": L, "Total Savings refunded to date (Rs.)": R,
        "Total Other expenses to date (Rs.)": E, "Total Loan right off to date (Rs.)": 0,
        "Total Loans outstanding to date (Rs.)": outst[0],
    }
    assert sav[0] + P + I + O - L - R - E == cash[0], name
    rows = [monthly_rows(ms[i], members[i], cash[i], dist[i]) for i in range(4)]
    return rows, opening


def seed(out: Path) -> Path:
    t = load_template()
    shutil.copy(ROOT / "samples" / "gn_workbook_template.xlsx", out)
    wb = GNWorkbook(out, t)
    plans = {name: history(name, g) for name, g in GROUPS.items()}
    # June first for every group (creates the tabs in this order), then the other months.
    # The opening tab is written last, so the saved workbook opens on it.
    order = [n for n in GROUPS if n != OPENING_TAB] + [OPENING_TAB]
    for name, g in GROUPS.items():
        rows, opening = plans[name]
        wb.write_month(name, MONTHS[0], rows[0], gn_name=g["gn"], opening=opening, create_tab=True)
    for i, month in enumerate(MONTHS[1:], start=1):
        for name in order:
            wb.write_month(name, month, plans[name][0][i], gn_name=GROUPS[name]["gn"], create_tab=True)
    wb.save()
    return out


def cash_check(path: Path) -> list[tuple[str, str, float, float]]:
    """Palmera's row 20 'cash from app', recomputed in Python from the inputs, next to
    row 19 (mother-book cash), for every seeded month. LibreOffice gives the same
    numbers (`soffice --headless --convert-to xlsx`); this needs no office suite."""
    import openpyxl
    wb = openpyxl.load_workbook(path)
    out = []
    for name in GROUPS:
        ws = wb[name]
        v = lambda r, c: ws.cell(r, c).value or 0
        app = v(21, 3) + v(22, 3) + v(23, 3) + v(24, 3) - v(25, 3) - v(26, 3) - v(27, 3)   # C20
        for i, month in enumerate(MONTHS):
            c = 3 + i
            if i:                                                   # D20 = C20 + D17 - D18
                app += (v(6, c) + v(7, c) + v(8, c) + v(9, c)) - (v(10, c) + v(14, c) + v(15, c) + v(16, c))
            out.append((name, month, v(19, c), app))
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        import tempfile
        p = seed(Path(tempfile.mkdtemp()) / "gn.xlsx")
        for name, month, book, app in cash_check(p):
            print(f"{name:11s} {month}  row19 {book:>8,.0f}  row20 {app:>8,.0f}  {'ok' if book == app else 'MISMATCH'}")
    else:
        print(seed(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "samples" / "gn_workbook_demo.xlsx")))
