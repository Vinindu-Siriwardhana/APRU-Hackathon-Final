# From the paper form to Palmera's workbook

Source of truth: `backend/app/config/palmera_shg_monthly_v3.yaml`. This page explains it.

## What gets written

Only the **16 input rows** of one month column on the SHG's tab. Rows are found by their label in column B, the same lookup Palmera's own sheets use, so inserting rows can't make us write to the wrong place. Formula cells are never overwritten. An existing value is only replaced when an officer confirms the report corrects a month that's already recorded (Send anyway, with a reason). A blank value is never written. A required row that can't be found stops the write and shows the officer why. The file is saved atomically (temp file, then swapped in), so a crash or two members confirming at the same moment can't corrupt it.

| Workbook row (per-SHG tab) | From the form | Rule |
|---|---|---|
| Total number of meetings held | "Was the SHG meeting held this week?" | number of weeks marked yes |
| Number of SHG members | header "Total Members" | as written |
| Total attendance for the month | "Number of people who attended" W1–W5 | sum of weeks |
| Number of people who are inactive… | "…inactive – waiting to pay loans off…" | Total cell (weeks are shaded) |
| Savings | Savings W1–W5 | sum of weeks |
| Principal loan repayments | Principal loan repayment | sum |
| Interest repayment | Interest repayment | sum |
| Other income | Other income | sum |
| Loans distributed | Loans distributed | sum |
| Loan Purpose – Income generation / Emergency / Other | same rows | sum |
| Savings refunded | Savings refunded | sum |
| Other expenses | Other expenses | sum |
| Loan right off | Total write offs | sum |
| Cash in Hand – end of month (mother book) | Actual Cash in Hand – end of week | the last week with any entries; if that week's cash is blank, the report is held (`month_end_cash_missing`) rather than an older week's cash being used |

A **new SHG tab** is only created after an officer confirms *It's a new group* (an unrecognised name otherwise blocks the report). In **month 1 of a new SHG tab**, column C also needs the nine "to date" opening totals. They must come from the mother book. If they're missing, the system assumes the group started this month and warns the officer.

**Captured but not written** (no row in the current template): weekly detail, savings to date, loans outstanding, members with overdue loans, expected balance, bank deposit, audit/grading/interest/constitution dates, and all of page 2. These are stored with each submission for the dashboard. Two of them, attendance at the last meeting and the goals count, are written automatically if Palmera adds those rows (see findings, issue 4).

## Validation layers

A value goes to an officer (an *error*) when:

| Layer | Rule | Example |
|---|---|---|
| Capture | the two independent readings disagree | W2 savings read as 2800 and 2300 |
| Capture | the model marks the handwriting unclear or illegible | |
| Capture | a cell has ink but both readings are blank, or the reverse | guards against missed or invented values |
| Arithmetic | the handwritten Total ≠ sum of W1–W5 | |
| Arithmetic | income-generation + emergency + other ≠ loans distributed | |
| Arithmetic | Total Income ≠ savings + principal + interest + other income | |
| Arithmetic | Total Expenses matches neither definition (with or without write-offs) | |
| Arithmetic | Expected Balance ≠ last week's cash + income − expenses (week 1 uses last month's closing cash from the workbook) | |
| Arithmetic | savings to date / loans outstanding don't follow on from the previous week | |
| Arithmetic | bank deposit is more than cash in hand | |
| Range | above Palmera's maximums (Mapping sheet), negative, attendance > members | |
| Continuity | this month is already recorded | |
| Member | the member corrected a figure on WhatsApp | officer compares it with the photo |

Shown to the officer but **not** blocking (*warnings*):
- cash in hand differs from the expected balance (a real shortfall or surplus for the group, not a reading problem)
- a month is missing
- the member count jumped
- overdue loans are counted but no names are listed
- more than 30% of members are overdue
- average attendance is below 50%
- high cash with no reason given

Why the ledger checks matter: in the test where both readings confidently agree on 8000 instead of 3000, the arithmetic still catches it in four different places.

## Added in round 1 (Oct 2026)

**Blocking** (goes to an officer):

| Rule | When |
|---|---|
| `not_a_number` | A number cell was read as text the app can't turn into a number (e.g. "15 members"). The raw text is kept for the officer. "Rs.3,000/=", "12,000/-" and lakh grouping are understood. |
| `meeting_flag_missing` | "Was the meeting held?" is blank in a week that has attendance or money entries. If the week has only balances, it's a warning. |
| `attendance_above_capacity` | Monthly attendance is more than members × meetings, which Palmera's sheet would reject. |
| `above_max` (monthly) | A month's total is above Palmera's maximum, as well as any single cell. |
| `month_end_cash_missing` | The last active week has no "Actual Cash in Hand". |
| `month_end_cash_mismatch` | Month-end cash differs from that week's expected balance. Earlier weeks' differences stay warnings, but this figure goes into the workbook. |
| `month_already_recorded` | The workbook already has figures in this month's column for this group. |
| `unknown_shg` | No tab matches the SHG name. The officer picks the right group, or confirms a new one. |
| `member_correction` | The member replied with a different figure. It clears itself once the cells add up to her figure; otherwise the officer keeps the form's figure, or, for a single-cell figure, uses hers. |
| `write_failed` | The workbook refused the write, for example because Excel has the file open. The message is shown as is and approving again retries. |

**Changed:**
- **Total Expenses:** either definition (with or without write-offs) is accepted week by week.
- **Running balances:**
  - A blank cash cell carries the running balance forward, so later weeks are still checked.
  - Last month's closing balances are used for week 1 only when they are exactly the previous month. A gap is a `month_gap` warning.
- **Savings to date:** may be gross or net of refunds, including earlier refunds.
- **Total column:** a blank Total cell falls back to the sum of its weeks.
- **Every ledger check lists every cell it depends on.** "Checked against the photo, kept as written" applies only when the officer has checked *all* of them.

**Suggestions and ranking.** For each failing sum, the app works out the value each cell would need for that sum to balance on its own. It then ranks cells by how many failing checks they appear in, and by whether one suggested value would clear several checks. The report opens on the top cell: "310 would make 3 checks balance".
