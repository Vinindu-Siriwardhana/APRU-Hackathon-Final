# From the paper form to Palmera's workbook

Source of truth: `backend/app/config/palmera_shg_monthly_v3.yaml` (fields, workbook rows, limits) and the code in `backend/app/validation.py` (the form's checks) and `backend/app/pipeline.py` (the checks about the workbook, the member and the officer's decisions). This page explains them. Rule names in `code` are what the API returns in `validation.issues[].rule`.

## What gets written

Only the **16 input rows** of one month column on the SHG's tab. Rows are found by their label in column B, the same lookup Palmera's own sheets use, so inserting rows can't make us write to the wrong place. Formula cells are never overwritten. An existing value is only replaced when an officer confirms the report corrects a month that's already recorded (Send anyway, with a reason). A blank value is never written. A required row that can't be found stops the write and shows the officer why. The file is saved atomically (temp file, then swapped in), so a crash or two members confirming at the same moment can't corrupt it. Text written to the workbook (SHG and GN names) that starts with `=`, `+`, `-` or `@` is stored as plain text, never as a formula.

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

**Captured but not written** (no row in the current template): weekly detail, savings to date, loans outstanding, members with overdue loans, expected balance, bank deposit, audit/grading/interest/constitution dates, and all of page 2. These are stored with each submission for the dashboard. Two of them, attendance at the last meeting and the goals count, are written automatically if Palmera adds those rows (see findings, issue 4).

## A new group: its opening totals

Column C of a tab is the group's first month, and Palmera's rows 21–29 there ("Total savings to date" … "Total Loans outstanding to date") hold its **lifetime** totals, including that month. Every later month's "to date" formula builds on them, and Palmera's cash check (row 20) is computed from them. So a new group can't be written until those totals are known.

1. The SHG name matches no tab: `unknown_shg` blocks ("No tab for SHG “…” in the GN workbook. Did you mean …? Fix the name, or confirm this is a new group."). The officer either picks the right group (this corrects the name) or chooses **It's a new group**.
2. While the group has no tab, `GET /api/submissions/{id}` returns `opening_suggestion`: the opening savings to date and loans outstanding **before this month**, worked out from the form where it can say (a week's written balance minus the month's flows up to that week; not when a refund or write-off makes it ambiguous, or the weeks disagree). The other seven totals are `null`: they must come from the mother book.
3. `POST /api/submissions/{id}/new-group` with either:
   - `started_this_month: true`: the nine opening totals are all zero; or
   - `opening: {label: amount}`: all nine totals **before this month**, from the mother book (0 allowed; labels as in `GET /api/template` → `opening_rows`). A missing or non-numeric total is refused with a sentence (HTTP 400).
4. The totals become the group's "last month" for the week-1 checks: opening savings to date, loans outstanding and refunds, and the opening cash Palmera's formulas imply (savings + principal + interest + other income − loans − refunds − other expenses, all to date). `unknown_shg` becomes a warning: "“…” is a new group (confirmed by an officer; …). A new tab will be created in the GN workbook when this report is written."
5. `opening_inconsistent` blocks when the totals contradict the form:
   - *started this month*, but the form's savings to date (or loans outstanding) is more than this month's flows can explain, in both the first and the last week that shows it: "The form says total savings to date is Rs 65,000, but the group's only savings this month is Rs 12,400, so it did not start this month. Enter its totals from the mother book." (The loans version: "…but this month's loans less repayments come to only Rs …, so the group did not start this month…".) The week-1 checks are then skipped, so they don't suggest "fixing" correctly read cells.
   - *mother-book totals* that differ from what the form says savings to date or loans outstanding were before the month: "The opening totals don't match the form: the form's own figures put total savings to date at Rs … before October 2026, but Rs … was entered. Check the mother book, then enter the totals again."
6. Calling `new-group` again replaces the totals, until the month is written. Changing the SHG name forgets the decision.
7. On write, the tab is created with this month as column C, and C21:C29 get **opening total + this month's flow** (loans outstanding = opening + distributed − principal − write-offs), so Palmera's row 19 = row 20 check holds. Existing opening totals are never changed by a later correction: correcting column C leaves C21:C29 alone and the write report tells the officer to update them from the mother book if needed.

## Every check

**Blocking** checks (*errors*) hold the report in **Needs review** until an officer resolves them. **Warnings** are shown but don't hold it up.

### 1. Capture: did we read the handwriting right?

| Rule | Severity | When |
|---|---|---|
| `passes_disagree` | error | The two independent readings differ ("The two readings disagree (Rs 2,800 vs Rs 2,300)."). |
| `ink_mismatch` | error | A cell has ink but both readings are blank, or the reverse. |
| `unclear_handwriting` | error | The reader marks the handwriting unclear or illegible ("The handwriting is unclear (read as '1200')."). |
| `not_a_number` | error | A number cell was read as text the app can't turn into a number (e.g. "15 members"). The raw text is kept for the officer. "Rs.3,000/=", "12,000/-" and lakh grouping are understood. |
| `member_correction` | error | The member replied to her summary with a different figure (see *Member* below). |

### 2. Completeness

| Rule | Severity | When |
|---|---|---|
| `required_missing` | error | A required header field (SHG name, total members, village/GN, month) is empty. |
| `meeting_flag_missing` | error / warning | "Was the meeting held?" is blank in a week that has attendance or money entries (error), or only balances (warning). |
| `month_end_cash_missing` | error | No week has any entries, or the last week with entries has no "Actual Cash in Hand". |
| `overdue_names_missing` | warning | Members with overdue loans are counted, but no names are listed on page 2. |
| `overdue_count_mismatch` | info | The overdue count differs from the number of names listed (when 5 or fewer). |

### 3. Range: Palmera's limits

| Rule | Severity | When |
|---|---|---|
| `above_max` | error | A cell is above Palmera's maximum (Mapping sheet: interest Rs 100,000, other expenses Rs 100,000, any other money flow Rs 1,000,000), **or** the month's sum written to the workbook is, **or** a header figure is (total members: 50). |
| `negative_value` | error | A figure is negative (expected balance excepted), or a header figure is below its minimum. |
| `attendance_above_members` | error | A week's attendance is more than the members. |
| `attendance_above_capacity` | error | The month's attendance is more than members × meetings, which Palmera's sheet would reject. |
| `count_above_members` | error | Inactive members, members with overdue loans or members with written goals is more than the members. |

### 4. Arithmetic: does the form's own ledger balance?

Checked for every week with entries and for the Total column. A blank Total cell falls back to the sum of its weeks, never a silent 0. Each check lists **every** cell it depends on, and for each the value that would make it balance on its own (`suggest`).

| Rule | Severity | When |
|---|---|---|
| `row_total` | error | A row's handwritten Total ≠ the sum of W1–W5. |
| `balance_total` | warning | A balance row's Total isn't the last week's figure. |
| `loan_purpose_split` | error | Income generation + emergency + other ≠ loans distributed. |
| `total_income` | error | Total Income ≠ savings + principal + interest + other income. |
| `total_expenses` | error | Total Expenses matches neither definition: loans + savings refunded + other expenses, with or without write-offs (Palmera question 2). Which one the group uses is recorded. |
| `attendance_without_meeting` | error | A week is marked "no meeting" but has attendance. |
| `expected_balance` | error | Expected Balance ≠ last week's cash + income − expenses (either expense definition). Week 1 starts from last month's closing cash in the workbook, only when that really is the previous month; for a new group, from its opening cash. A blank cash cell carries the running balance forward, so later weeks are still checked. |
| `month_end_cash_mismatch` | error | In the last week with entries, Actual Cash in Hand ≠ Expected Balance. When that week's Total Expenses includes write-offs, cash = expected balance + write-offs is accepted, because a write-off doesn't take cash out of the box (findings, issue 3). This figure goes into the workbook, so an officer must look. |
| `cash_mismatch` | warning | The same difference in an earlier week: usually a real shortfall or surplus for the group, not a reading problem. |
| `savings_to_date` | error | Total savings to date ≠ the previous week's (or last month's / the opening) + this week's savings. Gross or net of refunds are both accepted, including earlier refunds, and both are carried through blank weeks. |
| `loans_outstanding` | error | Total loans outstanding ≠ the previous + distributed − principal repaid, with or without write-offs. |
| `deposit_above_cash` | error | The amount deposited in the bank is more than the cash in hand. |

### 5. Continuity: does the month follow on from the workbook?

| Rule | Severity | When |
|---|---|---|
| `unknown_shg` | error, then warning | No tab matches the SHG name. A warning once an officer confirms a new group with its opening totals (above). |
| `opening_inconsistent` | error | A new group's opening totals contradict the form (above). |
| `month_already_recorded` | error | The workbook already has figures in this month's column for this group, or the month is before the next one due ("The workbook already has figures up to September 2026, so August 2026 is not a new month."). |
| `month_unexpected` | error | The month is more than one month after the last recorded month ("The form says November 2026, but the last month recorded for this group is September 2026. Check the month on the photo. If months really are missing, confirm it as written."), or more than a month after today ("…but that is more than a month from now (October 2026)…"), or before 2000. |
| `month_gap` | warning | After the officer confirms (or corrects) the month on the photo, a gap becomes this warning: "The last month recorded is September 2026, so October 2026 is missing. Last month's closing balances were not used for the week 1 checks." A future month confirmed as written stays a `month_unexpected` **warning** ("Checked against the photo, kept as written: …"). A year before 2000 or after 2100 is never accepted as a month: read from the photo, the cell is marked illegible (`unclear_handwriting`, with the raw text) and the officer types the right month; typed by an officer, it is refused. |
| `month_out_of_range` | error | The month falls outside the tab's 24 month columns (C–Z): "The form says …, but the Kalaimagal tab in the workbook only has columns for June 2026 to May 2028. Check the month on the photo. If it is right, this group needs a new sheet in the workbook: ask the person who manages it." |
| `members_jump` | error / warning | The member count changed from last month by more than 5 **and** more than 25%: error, "Members changed from 18 last month to 48. Check the member count on the photo. If it really changed, confirm it as written." Once the officer confirms or corrects the count, a warning ("Checked against the photo, kept as written: …"). A change of more than 5 but at most 25% is only a warning. |
| `prior_lookup_failed` | warning | Last month couldn't be read from the workbook; the opening-balance checks were skipped. |
| `write_failed` | error | The workbook refused the write, for example because Excel has the file open. The message is shown as is, and approving again retries. |

### 6. Findings for the group (warnings)

| Rule | When |
|---|---|
| `cash_mismatch` | Cash in hand differs from the expected balance in a week before the last (above). |
| `high_overdue_share` | 30% or more of members have overdue loans. |
| `low_attendance` | Average attendance at the month's meetings is below 50% of members. |
| `high_cash_no_reason` | Month-end cash is above Rs 25,000 (to confirm with Palmera, question 5) and page 2 gives no reason. |

### Member

| Rule | When |
|---|---|
| `member_correction` | She replied to the summary with a different figure (e.g. `5 12000`). It clears itself once the cells add up to her figure. Otherwise the officer keeps the form's figure, or, when the figure is a single cell on the form (a header figure, a Total-only row or the month-end cash), uses hers. |

## What the officer's decisions do

- **Checked against the photo, kept as written.** When an officer has confirmed or corrected **every** cell a capture, arithmetic or range check lists, the check becomes a warning prefixed "Checked against the photo, kept as written: ": the paper itself doesn't add up, and Palmera sees the sums as the group wrote them. This never applies to `above_max`, `attendance_above_capacity`, `member_correction`, `write_failed`, `unknown_shg`, `month_out_of_range`, `opening_inconsistent`, `month_already_recorded` or `prior_lookup_failed`, nor to completeness checks. The two continuity checks that an officer can settle on the photo, `month_unexpected` and `members_jump`, are downgraded inside the validation itself (above).
- **Send anyway** (`approve` with `force` and a reason) sends a report despite failing checks; the flagged cells are marked as accepted by the officer. It is refused for `unknown_shg`, `opening_inconsistent`, `month_out_of_range` and `month_unexpected`, and for `month_already_recorded` unless the officer also confirms the report replaces the recorded month (`overwrite`). Each needs its own decision first.
- **Ask for a new photo** closes the report and tells her why, in her language.

## Suggestions and ranking

For each failing sum, the app works out the value each cell would need for that sum to balance on its own. It then ranks cells by how many failing checks they appear in, then by how many of those checks one suggested value would clear, then by how many warnings (such as `cash_mismatch`) that value would clear too. The report opens on the top cell: "310 would make 3 checks balance". When the two readings disagree, the reading the ledger supports is offered first.

## What the member confirms

Her WhatsApp summary has **ten** numbered items (`summary_items` in the API): 1 Group, 2 Month, 3 Meetings held, 4 Total attendance, 5 Savings, 6 Loan repayments, 7 Interest, 8 Loans given, 9 Cash in hand (month end), 10 Members. The other workbook rows (inactive members, other income, the three loan purposes, savings refunded, other expenses, write-offs) are not in the summary: they reach the workbook because they passed the ledger checks above, or because an officer checked them against the photo.
