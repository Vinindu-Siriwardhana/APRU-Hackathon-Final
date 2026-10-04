# SHG Reports: how to use it

For monitoring officers, SHG members, and whoever presents the demo. The same guide is in the app under **Guide** in the sidebar.

- [1. The idea in one minute](#1-the-idea-in-one-minute)
- [2. For monitoring officers](#2-for-monitoring-officers)
- [3. For SHG members](#3-for-shg-members)
- [4. Presenting the demo](#4-presenting-the-demo)
- [5. Troubleshooting](#5-troubleshooting)
- [6. Questions judges and partners ask](#6-questions-judges-and-partners-ask)
- [7. Running costs and operations](#7-running-costs-and-operations)

---

## 1. The idea in one minute

1. **The member** fills in Palmera's paper form exactly as today, takes two photos (page 1, page 2) and sends them to the programme's WhatsApp number.
2. **The app**:
   - checks each photo straight away, and asks for a retake in her language if it can't be read;
   - straightens the photo onto the printed grid;
   - reads every figure twice;
   - checks that the form's own arithmetic adds up, and that the month follows on from the workbook.
3. **The officer** only looks at the figures that don't add up, with the handwriting zoomed in next to each one.
4. **The member** gets a ten-item summary on WhatsApp and replies **OK**, or corrects one figure.
5. **Palmera's workbook** gets the month's 16 figures on the group's tab, and the member gets a receipt.

Nothing reaches the workbook until an officer has checked every doubtful figure and the member has confirmed the summary. She confirms the ten summary items; the other figures written to the workbook are the ones that passed the ledger checks or that an officer checked against the photo.

The handwriting reader has **not yet been run on real filled forms**. The demo uses synthetic sample photos (see [section 6](#6-questions-judges-and-partners-ask)).

---

## 2. For monitoring officers

### Quick-start card

| You see | Do this |
|---|---|
| A report in **Needs review** | Open it. It opens on the most likely mistake, with the photo zoomed to that handwriting. |
| "**310** would make 3 checks balance" | If the handwriting says 310, click **Use 310**. |
| A figure that's wrong, with no suggestion | Type what the photo says (the box is already selected) and press **Enter**. |
| A figure that's right as written | Click **Keep 810**. |
| Two readings that disagree | Click the one that matches the handwriting (**Reading 1** or **Reading 2**), then press **Enter**. |
| "Everything checks out" | Press **Send to member**. |
| The member corrected a figure | Fix the cells against the photo, or keep the form's figure. |
| "No tab for SHG …" | Pick the right group, or choose **It's a new group** and give its opening totals. |
| "The form says … but the last month recorded for this group is …" | Check the month on the photo. Correct it, or confirm it as written if months really are missing. |
| "Members changed from 18 last month to 48" | Check the member count on the photo. Correct it, or confirm it as written. |
| "… only has columns for … to …" | The month is outside the group's sheet. Check the month; if it's right, the workbook needs a new sheet. |
| **Not delivered** on a message | Read the reason, fix it, then press **Resend**. |
| A photo you can't use | **•••** → **Ask for a new photo…** |

Keys: **Enter** saves and moves to the next flagged value · **Esc** closes the panel · **Alt + ↓ / ↑** (⌥ on a Mac) next / previous flagged value.

### What each status means

| Status | Meaning |
|---|---|
| **Waiting for photos** | Page 1 or page 2 hasn't arrived. If only page 1 ever comes, open the report and choose **Read page 1 now**. |
| **Needs review** | Some figures don't add up, the two readings disagree, or something about the group or month needs your decision. Your turn. |
| **Ready to send** | Every check passes. Press **Send to member**. |
| **Waiting for member** | She has the summary on WhatsApp. She replies OK, or the item number and the right figure. |
| **Recorded** | She said OK, and the month is written to the group's tab. She has a receipt. The report lists exactly which cells were written, with old and new values. |
| **Couldn't read** | The photos couldn't be read (no internet connection, or not the form). Press **Try again**, or ask for a new photo. |
| **Replaced** | A newer report for the same group and month arrived. Nothing from this one is written. |
| **New photo asked** | You asked her to send the photos again, or she replied STOP. |

### How the checks work

The paper form already contains its own arithmetic:
- each row has a Total;
- each week's income and spending add up to the totals;
- last week's cash plus this week's income, minus this week's spending, gives the expected balance;
- savings to date and loans outstanding carry on from week to week.

The app checks every one of these sums. It also checks that the month follows on from the one already in the workbook, that the member count hasn't jumped, and that figures are within Palmera's limits. [`form-to-workbook.md`](form-to-workbook.md) lists every rule.

A weekly figure is part of several sums at once, so a misread digit breaks every one of them that the group filled in. In the demo, *Interest repaid, week 3* read as 810 instead of 310 breaks three: the interest row's Total, week 3's Total Income, and week 3's Expected Balance. (The tests `test_round1_core.py` and `test_round1_api.py` check exactly this case; `test_pipeline.py::test_confident_misread_is_caught_by_the_ledger` checks that savings misread as 8000 for 3000, by both readings, breaks the row Total and Total Income.) A figure the group didn't add up anywhere, for example a week with no Total Income written, has fewer sums to catch it, which is why the member also confirms the summary.

### Why "Most likely" comes first

The figure that appears in the most failing checks is the likeliest misreading. The report opens on it, and the photo glides to its handwriting. When one value would make all of those checks balance, the app says so, e.g. "**310** would make 3 checks balance". Fix that one figure and three checks clear at once.

### Use, Save or Keep

- **Use 310:** the handwriting shows the suggested figure. One click saves it.
- **Save:** type the figure you see on the photo. The box is already selected, so just type. **Enter** saves and moves to the next figure.
- **Keep 810:** the photo really says what was read. The figure stays as written and is marked *checked against the photo, kept as written*. A sum whose cells you have **all** checked this way no longer holds the report up: the paper itself doesn't add up, and Palmera sees the sums as the group wrote them. This never applies to Palmera's limits (a figure above the maximum, attendance above members × meetings) or to the group-and-month decisions below: those need their own decision.

When the two readings disagree, both are shown. Pick the one that matches the handwriting, then press **Enter**.

### When the member corrects a figure

After the summary she may reply `5 12000`, meaning item 5 (Savings) should be 12,000. The bot tells her an officer will check it against her form; **nothing changes yet**. The report comes back to Needs review, showing her figure next to the form's.

- **The figure is a sum of weekly cells** (e.g. Savings): correct the weekly cells against the photo. When they add up to her figure, the question clears by itself.
- **The form is right:** choose **Keep the form's figure**.
- **Use her figure** only appears when the figure is a single cell on the form, so the ledger always still balances.

### A group that isn't in the workbook

If the name on the form doesn't match any tab, the report is held ("No tab for SHG …"). Either pick the right group from the list (this corrects the name), or choose **It's a new group**. A new tab is made when the month is written, and its first month needs the group's opening "to date" totals (savings, repayments, interest, other income, loans, refunds, other expenses, write-offs and loans outstanding, all **before** this month):

- **The group started this month:** its opening totals are all zero. If the form says otherwise (for example savings to date of Rs 65,000 when this month's savings are only Rs 12,400), the app stops: "… so it did not start this month. Enter its totals from the mother book."
- **An existing group, new to the app:** enter all nine totals from the group's mother book (0 is allowed). Where the form itself shows savings to date or loans outstanding, the app fills those in for you and checks your figures against it. If they disagree, it stops: "The opening totals don't match the form …". Check the mother book and enter them again.

You can change the opening totals until the month is written. Week 1's checks start from them, as they would from last month.

### A month that's unexpected

- **More than one month after the last recorded month** ("The form says November 2026, but the last month recorded for this group is September 2026"): usually a misread month or year, which would put the figures in the wrong column. Check the month on the photo. If it was misread, correct it. If months really are missing, confirm it as written: it becomes a *month missing* warning, and last month's closing balances aren't used for week 1.
- **More than a month in the future**: check the photo; confirm it as written only if it really is right.
- **Outside the group's sheet** ("… only has columns for June 2026 to May 2028"): each tab has 24 month columns. Check the month; if it's right, the person who manages the workbook has to add a sheet. This can't be confirmed as written or sent anyway.

### A big change in member count

A change of more than 5 members **and** more than 25% from last month holds the report: "Members changed from 18 last month to 48. Check the member count on the photo." A misread count skews every attendance rate. If it's misread, correct it; if the group really changed, confirm it as written. Smaller changes (more than 5 members, up to 25%) are only a warning. The member count is item 10 of her summary, so she sees it too.

### A month that's already recorded

If the workbook already has this group's month, the report is held. If the new figures are a genuine correction, use **••• → Send anyway…** and give the reason (the sheet warns that it replaces the recorded month); the month is replaced once she confirms. Otherwise ask for a new photo.

### Send anyway, or ask for a new photo

- **Send anyway…** sends a report that still has a failing check, for example after you phoned the group and the book really says that. Your reason is kept with the report. It can't skip an unknown group, a new group's opening totals that don't match the form, a month outside the sheet, an unexpected month or an already-recorded month: each of those needs its own decision first.
- **Ask for a new photo…** closes the report and sends her a simple message in her language saying why. The reasons are: unclear photo, page missing, wrong form, wrong group or month, or parts left empty. You can add a private note; it is not sent to her.

### When a WhatsApp message isn't delivered

In live mode every message the bot sends is checked. A send that fails shows **Not delivered** on the report, with the reason, for example:
- *more than 24 hours have passed since her last message*: WhatsApp only allows approved template messages after 24 hours. Ask her (by phone, or at the meeting) to send any message, then press **Resend**;
- an expired access token, or a number that isn't on the test list: fix the setup, then press **Resend**.

**Resend** sends the undelivered messages again, in order. Check for *Not delivered* every day: a member who never gets her summary can't confirm it. (In the demo's phone simulator nothing is sent over WhatsApp, so this never appears.)

### Where the data goes

Each group has its own tab in Palmera's GN workbook, with one column per month (June 2026 is column C). The app fills the month's **16 input rows** and never touches a formula. **Download workbook** in the sidebar gives the current file.

### Reading the Groups page

Groups shows each group month by month, from the workbook:
- **Financial health:** savings growth, repayments, attendance, and cash against the ledger.
- **Early warnings:**
  - attendance below 60%, or down 15 points;
  - savings or loan repayments falling three months in a row;
  - cash counted not matching the ledger;
  - no recent report.

Each warning says what it means, and most say what you might do, usually a call to the group leader or a visit. Groups that need attention are listed first.

---

## 3. For SHG members

*(For officers to explain at a group meeting. Everything the bot says is in Sinhala, Tamil or English, whichever she uses.)*

### Taking the photos

1. **Lay the form flat and take it from above.** Put it on a table and hold the phone straight above it, not at an angle.
2. **Get the whole page in.** All four corners should be inside the photo.
3. **Use daylight, not the flash.** Near a window is best; the flash makes a shiny patch that hides numbers.
4. **Send page 1, then page 2.** The bot asks for page 2 once page 1 is clear.

### If the bot asks for another photo

Each photo is checked the moment it arrives, so she can retake it while the form is still in front of her.

| The bot says | What to do |
|---|---|
| "The photo is blurry…" | Hold the phone still, tap the form on the screen to focus. |
| "The photo is too dark…" | Move near a window or into daylight. |
| "A shadow is covering part of the page…" | Keep your hand and the phone's shadow off the page. |
| "There is a bright reflection…" | Turn off the flash, or tilt the page away from the light. |
| "Part of the page is cut off…" | Step back so all four corners are in. |
| "The page is too far away…" | Move closer so the page fills the screen. |
| "The photo is taken from an angle…" | Hold the phone straight above the page. |
| "I couldn't find the report form…" | Lay the page flat and take it from above, with the whole page showing. |
| "The photo is too small…" | Send the photo itself, not a screenshot. |

### Checking the numbers

After an officer has looked, she gets a numbered list of ten items for the month:
1. Group
2. Month
3. Meetings held
4. Total attendance
5. Savings
6. Loan repayments
7. Interest
8. Loans given
9. Cash in hand at month end
10. Members

- If they're all right, she replies **OK**.
- If one is wrong, she replies with its number and the right figure, e.g. **5 12000**. "5. 12,000" and "5 Rs.12000/=" also work. An officer checks it against her form before anything changes.
- If she writes while an officer is still checking, the bot tells her so. Nothing is lost.

### The receipt

When she replies OK, the month is recorded. The receipt names her group and the month, repeats the month's savings, repayments and cash, and gives her group's **total savings so far**.

### Privacy

The first message tells her: *"Palmera uses these photos only to record your group's monthly report. Reply STOP to opt out."*
- Replying **STOP** closes her open reports. Writing again later opts her back in.
- In this app, only Palmera's monitoring officers see the photos and figures.
- In live mode the photos are also read by an AI service (Claude, by Anthropic). Before a real pilot, Palmera needs consent wording and a data-processing agreement under Sri Lanka's Personal Data Protection Act No. 9 of 2022.

---

## 4. Presenting the demo

### Before you go on stage

- [ ] Installed and started once the day before (the first run downloads about 70–90 MB).
- [ ] The browser window is at least 1440 × 900; 1280 × 720 works.
- [ ] The sidebar says **Offline demo**. If it says *Reading with Claude*, close the window, unset `ANTHROPIC_API_KEY`, and start again.
- [ ] Press **Restart demo**.
- [ ] Turn on **Show phone beside**, so the audience sees the phone and the officer screen together. The sidebar then shows icons only: **Needs review** is the tray icon at the top, **Groups** the chart icon, **Download workbook** the download icon near the bottom (hover for the name).
- [ ] The **Demo guide** (sidebar) ticks off each step with a *Go* link. It folds itself away when a report opens, so it never covers the photo.

Each reply takes a few seconds in offline mode. Wait for it rather than clicking twice.

### The script (about 3 minutes)

| # | Do | Say / point at |
|---|---|---|
| 1 | **Member's phone** → choose **தமிழ்** → send **Kalaimagal, Oct, page 1** | The photo is checked instantly; a few seconds later the bot asks for page 2, with English underneath for us. |
| 2 | Send **page 2** | A few seconds later: "an officer is checking a few numbers". |
| 3 | **Needs review** → **Kalaimagal** | It opens on *Interest repaid, week 3*. The photo glides to the handwriting: it says 310, but it was read as 810. Only the ledger caught it: "**310** would make 3 checks balance". |
| 4 | Click **Use 310** | "3 checks cleared"; four checks drop to one. |
| 5 | *Savings, week 2*: click **Reading 1** (2,800), press **Enter** | The two readings disagreed (2,800 vs 2,300). A person decides, never the machine. |
| 6 | **Send to member** | After a few seconds the ten-item Tamil summary arrives on the phone. |
| 7 | Tap **OK** on the phone | A few seconds later the receipt comes back, with her group's total savings so far (Rs 95,400). |
| 8 | The report: **Written to Palmera's workbook** | Tab Kalaimagal, column G, 16 cells, each with its old and new value. She confirmed the summary; every other figure passed the ledger checks. |
| 9 | **Groups → Sisila** | Attendance, savings and repayments all slipping. Each warning explains itself. |
| 10 | **Download workbook** → Kalaimagal tab, column G | If Excel shows *Protected View*, click **Enable Editing** first, or the formula rows stay blank. Row 19 (mother-book cash, Rs 20,160) equals row 20, Palmera's own formula. |

**If you have time:**
- a problem photo (*Blurry*, *Glare*, *Steep angle*), to show the retake message;
- *Sisila, Oct* (best in **සිංහල**): a smudged cell, *Principal repaid, week 4*, that the reader marks unclear, so the officer checks it on the photo;
- *Kalaimagal, Nov*: after the October script it follows on cleanly and goes straight to her summary. Sent before October is recorded, the app holds it ("The form says November 2026, but the last month recorded for this group is September 2026");
- the **•••** menu (*Send anyway*, *Ask for a new photo*);
- Palmera's own bug in rows 28–29 of every tab (see `docs/palmera-findings-and-questions.md`).

**Don't open:** the *SHG Monitoring* tab in Excel or LibreOffice. It uses Google Sheets-only formulas and shows "Can't find".

**If something goes wrong:** press **Restart demo** (it clears the reports and the phone) and start from step 1. If the server stopped, the app shows "Can't reach the server" and reconnects by itself when it's back.

---

## 5. Troubleshooting

| Problem | Fix |
|---|---|
| `run.bat` says Python 3.10 to 3.14 was not found | Install Python 3.13 from https://www.python.org/downloads/release/python-31316/ (Windows installer (64-bit)) and tick **Add python.exe to PATH**, then run it again. |
| "The only Python on this computer is too new" | Python 3.15 is too new for some libraries. Install 3.13 as well (keep the other one); `run.bat` / `run.sh` finds it by itself. |
| "Windows protected your PC" | Click **More info → Run anyway**. |
| It won't start from the zip | Extract the zip first (right-click → Extract All), and run `run.bat` from the extracted folder. |
| Installing the libraries failed | Check the internet connection and run it again; a half-finished install is cleaned up automatically. |
| "SHG Reports is probably already running" | It's already open in another window. Go to http://localhost:8000, or close the other window. |
| The browser didn't open | Open http://localhost:8000 yourself. |
| Ctrl+C on Windows asks "Terminate batch job (Y/N)?" | Type **Y** and press Enter. Closing the window stops the app too. |
| A member's OK gives "Close gn_workbook.xlsx in Excel" | Excel has the workbook open, so Windows locks it. Close it, then press **Write to workbook** on the report. |
| The downloaded workbook shows blank month names or a blank row 20 | Excel opened it in *Protected View*. Click **Enable Editing**. |
| A photo is refused as not one of the demo samples | Offline demo mode reads only the sample photos. Set `ANTHROPIC_API_KEY` to read real forms. |
| A report says **Couldn't read** | The AI service couldn't be reached, refused, or didn't answer in time. Press **Try again**. |
| A message shows **Not delivered** | See *When a WhatsApp message isn't delivered* above. |
| Start completely fresh | Close the app and delete the `data/` folder. |
| Mac/Linux: "python3-venv is missing" | Run `sudo apt install python3-venv`, then `bash run.sh` again. |

---

## 6. Questions judges and partners ask

**Is the handwriting really read by AI in the demo?**
Not on stage. Offline demo mode reads the sample photos from their answer key, with planted mistakes, so the demo doesn't depend on venue Wi-Fi. With `ANTHROPIC_API_KEY` set, Claude reads each form twice, independently, from two views of the photo. That code path is built and tested against the API's request format, but **has not yet been run on real handwritten forms**: that's the next step, with forms from Palmera.

**What stops a wrong number getting into Palmera's workbook?**
Several layers:
- the two readings must agree;
- an ink check catches blank-versus-written mismatches;
- the form's own ledger must balance, and a misread digit breaks every sum it is part of;
- the month must follow on from the workbook, and the member count can't jump without an officer looking;
- an officer must look at anything doubtful;
- the member confirms the ten-item summary herself.

The writer never touches a formula, finds rows by their label, and refuses to overwrite a month silently.

**What does it do for the members' financial health?**
The groups' savings and loans get recorded every month without hand-typing, mistakes are caught before they reach Palmera's records, groups that are slipping show up as early warnings, and every member's receipt shows her group's total savings, not just the treasurer's book.

**How does Palmera's officer learn it?**
Through the **Guide** in the app (and this document), and the quick-start card above. The review screen is designed so an officer only ever handles the few figures that don't add up.

**What does it cost to run, and who runs it?**
See [section 7](#7-running-costs-and-operations).

**What about privacy?**
- On first contact, members are told what the photos are used for and how to opt out (STOP).
- For a real pilot Palmera needs:
  - consent wording and a data-processing agreement under the PDPA (photos go to an AI service in live mode);
  - a retention period;
  - officer login;
  - a list linking phone numbers to groups.
- See *Before a real pilot* in the README.

**Can it work for other forms or partners?**
Yes. The form, the field mapping, the checks and the thresholds are all in one YAML file, plus a grid layout learned from the blank form.

---

## 7. Running costs and operations

These are estimates. **Nothing here has been measured on real forms yet**; the pilot should measure the real figures (see *How to measure it* below). Prices are in US dollars, as published on 4 October 2026.

### What drives the cost per report

1. **Claude reading (the main cost).** Each report is read in **4 requests**: page 1 twice and page 2 twice, from different views of the photo. A photo the quality gate refuses never reaches Claude (that check runs on the server), so retakes cost nothing. **Try again** on a failed report reads it again (4 more requests).
   - *Image tokens:* the app sends each view at most 1,800 pixels on its long side. For Claude Opus 5.5, an image costs about ⌈width / 28⌉ × ⌈height / 28⌉ tokens (Anthropic's vision docs). Worked out for the sample photos (1600 × 2095 phone pictures), the six images of one report come to **about 12,600 input tokens**.
   - *Text:* each request also carries the instructions and the answer format, about 6,000 characters, roughly 1,500 tokens; about 6,000 tokens for the 4 requests.
   - *Answer:* the structured reading of page 1 is about 7,400 characters of JSON per pass in our samples; page 2 is about 1,600. We assume 2,500–6,000 output tokens per page-1 pass and 600–1,000 per page-2 pass, so **6,000–14,000 output tokens** per report.
   - *Model choice:* `SHG_EXTRACTION_MODEL`, default `claude-opus-5-5`. Opus 5.5 costs **$4 per million input tokens and $20 per million output tokens**. Claude Sonnet 5.5 costs $2 / $10 and Claude Haiku 4.5 $1 / $5, but **we have not tested whether they read this handwriting as well**. The Batch API halves the price, but answers can take hours, so it only suits reports nobody is waiting for.
2. **WhatsApp messages.** Since July 2025 Meta charges per *template* message delivered; replies inside the 24-hour customer-service window (the 24 hours after the member's last message) are free, and so are utility templates sent inside it. In this app most messages to the member are replies to her photos or her OK. The exceptions are messages an officer triggers more than 24 hours after her last message (usually the summary, sometimes a request for new photos): those need an approved *utility* template (not built yet). From 1 October 2026 Sri Lanka is its own pricing market, with a utility rate of **$0.0023 per message** (before that it was billed as "Rest of Asia Pacific", $0.0130). So WhatsApp costs **$0 to about $0.002 per report**.
3. **Hosting.** One small always-on server with a public HTTPS address for the WhatsApp webhook. The prototype runs comfortably on a 2-core laptop; we have not measured the cheapest server that works. Writing to Google Sheets through the Sheets API has no charge.

### Worked estimate

Assumptions: Claude Opus 5.5, one report per group per month, the sample photos' size, no **Try again**, every summary sent late enough to need a template.

| Per report | Tokens | Cost |
|---|---|---|
| Claude input (images + text) | about 18,600 | about $0.07 |
| Claude output | 6,000–14,000 | $0.12–$0.28 |
| WhatsApp (one utility template) | | about $0.002 |
| **Total** | | **about $0.20–$0.36** |

For **100 groups**, that is about **$20–$36 a month** for reading and messages, plus the server. With Claude Sonnet 5.5 the reading cost roughly halves, if a pilot shows it reads as accurately.

### How to measure it in the pilot

- **Claude:** every API response reports the tokens it used (`usage.input_tokens`, `usage.output_tokens`). Log them per report (a small addition to `ClaudeReader.read`), or read the totals in the Claude Console's usage page, and divide by the number of reports read.
- **WhatsApp:** Meta's WhatsApp Manager shows message counts and charges by category. Compare the charged templates with the number of reports.
- **Accuracy per model:** read the same 50 real forms with Opus 5.5 and Sonnet 5.5, and count how many figures the officer had to change. Choose the cheaper model only if it doesn't add work for officers.

### Who runs it, and what they do

- **Monitoring officers:** review **Needs review** reports (usually a few figures each) and check **Not delivered** messages every day.
- **One technical person at Palmera, or a partner:** keeps the server running, renews the WhatsApp access token, gets the summary and receipt templates approved by Meta, backs up `data/` and the workbook, and watches the Claude and WhatsApp bills.
- **Palmera's programme lead:** agrees the consent wording, the retention period and the list linking phone numbers to groups (see *Before a real pilot* in the README).

### Sources

- Claude API prices: Anthropic, *Pricing* — https://platform.claude.com/docs/en/about-claude/pricing (Opus 5.5 $4 / $20, Sonnet 5.5 $2 / $10, Haiku 4.5 $1 / $5 per million tokens; Batch API 50% off).
- Image tokens: Anthropic, *Vision* — https://platform.claude.com/docs/en/build-with-claude/vision (28 × 28-pixel patches; up to 2,576 px on the long side for Claude 4.7 and later models).
- WhatsApp pricing model: Meta, *Pricing on the WhatsApp Business Platform* — https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing (per-message pricing from 1 July 2025; free service replies and utility templates inside the customer-service window; Sri Lanka becomes a standalone market on 1 October 2026, with lower utility rates).
- Sri Lanka rate from 1 October 2026: Gallabox's copy of Meta's USD rate card — https://docs.gallabox.com/pricing-and-billing/whatsapp-pricing/rate-card.md (Sri Lanka utility $0.0023; Rest of Asia Pacific $0.0130). Check Meta's own rate card (linked from the page above) before budgeting.
