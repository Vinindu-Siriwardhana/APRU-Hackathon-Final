# Palmera SHG monitoring — findings and questions

*From analysing the files Palmera shared: "Monthly Report of the SHG to Cluster" (English V3, April 2026), the GN-level "SHG summary monitoring" workbook, and the district "SHG Summary Monitoring" workbook. Every issue below was reproduced by entering test figures into Palmera's template and recalculating.*

## How the system works today

- **Monthly data is typed in only on each SHG's own tab in the GN Google Sheet.** Months run across columns C to Z, and column C is month 1, which also holds the opening "to date" totals.
- Everything else is calculated from those tabs: the GN "SHG Monitoring" sheet (by row label) and the whole district workbook (via `IMPORTRANGE`).
- The paper form is **weekly** (W1–W5 plus Total), but the workbook is **monthly**. Someone currently adds up each form by hand and types in 16 numbers per group per month.

## Formula issues in the current workbooks

### 1. "Total Loans outstanding to date" is wrong (GN template, per-SHG tab, rows 28–29)

| Row | Label | Current formula (col D) | What it actually computes | Suggested formula |
|---|---|---|---|---|
| 28 | Total Loan right off to date | `=C28+D10-D7` | loans distributed − principal repaid, which is the *outstanding* balance | `=C28+D16` |
| 29 | Total Loans outstanding to date | `=C29+D11-D8` | + income-generation loans − interest repaid (not meaningful) | `=C29+D10-D7-D16` |

**Test:** opening outstanding Rs 40,000, then Rs 8,000 distributed (5,000 of it for income generation), Rs 5,000 principal repaid, Rs 600 interest and Rs 1,000 written off.
- The sheet shows **Rs 44,400** outstanding. The correct figure is **Rs 42,000**.
- "Write-off to date" shows Rs 3,000 instead of Rs 1,000.

This looks like a row was inserted ("Loan right off", row 16) and these two formulas weren't updated. The district "Total Loans outstanding" and "loan repayment rate" figures inherit the error.

### 2. The district "complete & balanced month" check compares the wrong rows

`SHG Level_Data Monitoring!AC` stacks rows 3–18 plus rows 21 and 22 of each SHG block, and requires row 21 = row 22.

After the same row insertion, the rows have shifted:
- Row 21 is now *Cash in hand (from app)*.
- Row 22 is now *Total savings to date*.

So the check asks whether cash in hand equals total savings to date, which is almost never true. As a result, SHGs will show "Never completed correctly" even when the mother book balances. It should compare row 20 (mother book) with row 21 (from app), and the "all filled in" test should include rows 19–20.

### 3. Write-offs are counted as a cash expense (GN template row 18)

- "Total Expenses" is `loans distributed + savings refunded + other expenses + loan write-off`.
- A write-off doesn't take cash out of the box. So in any month with a write-off, "cash from app" comes out lower than the mother book, and the group is flagged "cash in hand not matching" when nothing is wrong.
- The district report's own "Total Expenses" (row 59) leaves write-offs out, so the two levels also disagree.

### 4. District indicators with no source row

The district workbook reports these, but the GN template has no rows for them, so they are always empty or N/A:
- "Number of members who attended the last meeting" (the attendance-rate bands)
- "How many women have current goals…"
- Members starting or closing a business

The paper form already captures weekly attendance and the goals count. Our system records both and can fill these rows as soon as they're added to the template.

### 5. Sinhala labels to double-check (Mapping sheet)

- Row 16, "Loan right off": `ණය වහාම`. This looks like it means "loan immediately" rather than a write-off.
- Row 28, "Total Loan right off to date": `මේ දක්වා මුළු ණය මුදල` ("total loan amount to date").

Worth a native speaker's check, because our WhatsApp summaries reuse these labels.

## Questions for Palmera

**About the form**
1. What does **"Total Loan (Rs.)"** in the Totals section mean? Total loans given that week, or something else?
2. Should **Total Expenses** on the paper form include write-offs? (See issue 3.) The system accepts either for now and records which one each group uses.
3. Does **"Actual Cash in Hand"** include the money in the SHG's bank account, with "Amount deposited in SHG bank" being the part held in the bank? That's how we read it, because the workbook's cash check has no separate bank line.
4. Is **"Total savings to date"** before or after savings refunds? The workbook treats refunds separately, so we accept both.
5. What amount counts as **"high cash in hand"** (question 1 on page 2)? We've assumed Rs 25,000.
6. Could we have the **Sinhala and Tamil printed versions** of the form? The system aligns to the grid, which should be identical across languages, but we need to confirm.

**About the workflow**
7. Should the system write straight into the **live GN Google Sheets** (through a service account) or into a staging copy that an officer copies across?
8. **New SHGs:** month 1 needs lifetime totals from the mother book (savings, repayments, loans and so on to date). The app asks the officer for them (or zero, for a group that started this month) and checks them against the form's own savings to date and loans outstanding. Who should provide these when a group is first set up, and is the mother book the right source?
9. **Who sends the photo and confirms the summary?** The person completing the form, or the cluster representative? We need a list linking phone numbers to SHGs.
10. Is there a fixed **meeting day** per group? The WhatsApp receipt could then include the next meeting date.
11. **Data protection** (PDPA No. 9 of 2022): where can photos be stored, for how long, and what consent wording should members see on first use?
