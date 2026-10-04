# SHG Reports — Digitising Palmera's Self-Help Group Monitoring

**APRU Hackathon — Final Submission**

An end-to-end prototype that turns Palmera's paper *Monthly Report of the SHG to Cluster* into verified entries in Palmera's own Grama Niladhari (GN) monitoring workbook, using a photograph sent over WhatsApp. Members keep filling in the same paper form; the app handles the reading, checking and recording.

## The problem

Palmera supports self-help groups (SHGs) through which rural women save and borrow. Today, a staff member adds up each weekly paper form by hand and types **16 figures per group per month** into Palmera's workbook. This is slow, error-prone, and the mistakes land directly in the financial records that Palmera uses to monitor group health and lending risk.

## The solution

SHG Reports reads a photographed form, checks every figure against the form's own ledger arithmetic, asks the member to confirm her summary, and only then writes the month's figures into the workbook — leaving officers to review just the numbers that don't add up.

Concretely, the prototype:

- **removes manual re-keying** — officers no longer type 16 numbers per group; they review only the figures the ledger cannot reconcile;
- **catches errors before they reach the records** — the form's ledger must balance, the member confirms her summary, and an officer settles anything doubtful;
- **surfaces early-warning signals** — declining attendance, savings or repayments, and cash that doesn't match the ledger, so an officer can call or visit a group before a small problem compounds;
- **gives each member visibility** — every receipt shows her group's total savings to date, so every member can see the group's money, not just the treasurer.

It is a working prototype: the AI reader has **not yet been run on real handwritten forms** (see [Modes](#modes) and [Before a real pilot](#before-a-real-pilot)).

## How it works

```
photo on WhatsApp ─► quality gate ─► align to the form grid ─► 2 independent Claude readings
   ▲   (retake message in si/ta/en)                                    │
   │                                                                   ▼
receipt ◄─ write to GN workbook ◄─ member confirms ◄─ officer review ◄─ ledger checks
```

1. A member photographs a filled monthly form and sends it over WhatsApp.
2. A **quality gate** rejects unusable photos (blurry, dark, glare, steep angle, cut off) and asks for a retake in the member's language (Sinhala, Tamil or English).
3. The photo is deskewed, aligned to the printed form grid, and cropped into individual cells.
4. Each cell is read **twice by Claude** (independent passes). Disagreements and low-confidence reads are flagged for review.
5. **Validation** checks the form's own ledger arithmetic, month continuity, and plausible ranges, and proposes the value that would make the checks balance.
6. An officer reviews only the flagged cells, then the member confirms a short summary on her phone.
7. The verified figures are written to Palmera's GN workbook (per-group tab, located by row label, without touching formulas).

## Quick start

**Requirements:** Python 3.13 recommended (3.10–3.14 supported; 3.15 is not yet, as some dependencies lack ready-made wheels). Install from [python.org](https://www.python.org/downloads/release/python-31316/) and tick **"Add python.exe to PATH"** on Windows.

**Windows**
1. Right-click the zip → **Extract All**, into a plain folder such as `C:\shg-digitiser` (avoid OneDrive-synced locations).
2. Double-click **`run.bat`**. If Windows shows "Windows protected your PC", choose **More info → Run anyway**.

**macOS / Linux:** open a terminal in the project folder and run `bash run.sh`.

The first run installs dependencies into a local `.venv` (≈70–90 MB, a few minutes). The browser opens **http://localhost:8000** automatically once the app is ready. The raw API (OpenAPI) is at **http://localhost:8000/docs**.

> Keep the launcher window open while using the app; close it to stop the server. If port 8000 is already in use, the app is likely already running — just open http://localhost:8000.

## Demo script (~3 minutes)

Use a window of at least 1440 × 900. Confirm the sidebar shows **Offline demo** (see [Modes](#modes)). Press **Restart demo**, then enable **Show phone beside** so the member's phone and the officer dashboard are visible together.

1. **Member's phone:** choose **தமிழ்**, then send *Kalaimagal, Oct, page 1*. The bot asks for page 2 (with an English line under each Tamil message). Send *page 2*.
2. **Needs review → Kalaimagal:** the report opens on the most likely misreading, *Interest repaid, week 3* — read as **810**, but the handwriting says **310**. Click **Use 310** to clear the checks.
3. *Savings, week 2* shows two disagreeing readings (2,800 vs 2,300). Choose **Reading 1** (2,800) and press **Enter**, then **Send to member**.
4. The ten-item Tamil summary arrives on the phone; tap **OK** and the receipt returns with her group's total savings to date (Rs 95,400).
5. The report shows **Written to Palmera's workbook** — tab Kalaimagal, column G, 16 cells for October 2026.
6. **Groups → Sisila** shows early-warning flags for attendance, savings and repayments, each with a suggested officer action.
7. **Download workbook** and open it (click **Enable Editing** if Excel shows Protected View). Kalaimagal's row 19 (mother-book cash) now equals row 20, Palmera's own "cash from app" formula.

Also worth demonstrating: a deliberately bad photo (to show the retake message), the **•••** menu on a report (*Send anyway…*, *Ask for a new photo…*), and Palmera's own workbook formula bug (rows 28–29) documented in [`docs/palmera-findings-and-questions.md`](docs/palmera-findings-and-questions.md).

> Note: do not open the **SHG Monitoring** tab in Excel or LibreOffice — it uses Google Sheets-only formulas. It works correctly in Google Sheets.

## Modes

- **Offline demo** (no `ANTHROPIC_API_KEY`): the sample photos in `samples/synthetic/` are read from their answer key, with planted misreadings (e.g. 810 for 310, a 2,800/2,300 disagreement, a smudged cell) so the review flow has something to catch. No network required; unrecognised photos are politely refused, never invented.
- **Reading with Claude** (`ANTHROPIC_API_KEY` set): real forms are read twice by Claude. `SHG_EXTRACTION_MODEL` selects the model (default `claude-opus-5-5`).

| Setting | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Enables real handwriting reading with Claude |
| `SHG_EXTRACTION_MODEL` | Claude model to use (default `claude-opus-5-5`) |
| `SHG_READ_TIMEOUT` | Seconds to wait per Claude request (default 120) |
| `SHG_DATA_DIR` | Where reports, photos and chats are stored (default `data/`) |
| `SHG_WORKBOOK` | GN workbook to write into (default `data/gn_workbook.xlsx`) |
| `SHG_ALLOW_RESET=1` | Allows **Restart demo** outside offline mode |
| `SHG_DISABLE_SIMULATOR=1` | Disables the phone-simulator endpoints (production) |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID` | Meta WhatsApp Cloud API credentials |
| `WHATSAPP_VERIFY_TOKEN` | Secret for Meta's webhook handshake |
| `WHATSAPP_APP_SECRET` | Enforces `X-Hub-Signature-256` on every webhook POST |
| `WHATSAPP_ALLOW_UNSIGNED=1` | Local testing only: accept unsigned webhook POSTs |
| `WHATSAPP_API_VERSION` | Graph API version (default `v21.0`) |

The first run creates `data/gn_workbook.xlsx` from Palmera's template, seeded with three demo groups (June–September). Delete the `data/` folder to start completely fresh.

## What's built

| Component | Location | Status |
|---|---|---|
| Form template config (fields, shaded cells, roll-up rules, workbook rows, thresholds) | `backend/app/config/palmera_shg_monthly_v3.yaml` | done |
| Grid layout of the printed form | `…/palmera_shg_monthly_v3.layout.json`, `tools/learn_layout.py` | done |
| Image quality gate (dark, blurry, glare, shadow, steep angle, cut off…) with retake messages in en/si/ta | `backend/app/imaging/quality.py` | done; thresholds tuned on synthetic photos |
| Photo alignment: deskew, perspective correction, table grid, per-cell crops | `backend/app/imaging/grid.py`, `layout.py` | done |
| Two-pass Claude reading (structured output), ink cross-check, typed failures | `backend/app/extraction.py` | done; **not yet run on real handwritten forms** |
| Validation: capture, ledger arithmetic, continuity, ranges, findings; proposes the balancing value and ranks the likeliest misreading | `backend/app/validation.py` | done |
| Weekly → monthly roll-up | `backend/app/aggregate.py` | done |
| Workbook writer: per-group tab, rows located by label, formulas untouched, atomic save | `backend/app/workbook.py` | done (`.xlsx`; Google Sheets API next) |
| Pipeline: status flow, officer/member actions, superseded reports, audit history, single lock around each change | `backend/app/pipeline.py`, `locking.py` | done |
| Bot messages in en/si/ta (Palmera's own Sinhala/Tamil row labels), privacy note, STOP | `backend/app/messages.py` | done; new si/ta sentences marked `# native check` |
| WhatsApp Cloud API connector: signature check, duplicate-delivery handling, failed sends shown with **Resend** | `backend/app/whatsapp.py`, `conversations.py` | done; needs a Meta app to test live |
| REST API and phone simulator | `backend/app/api.py` | done |
| Officer dashboard (React): review queue, zoom-to-value with suggestions, keyboard review, group financial health and early warnings, phone simulator, presenter mode, in-app guide; light/dark, phone-sized screens | `frontend/` | done |
| Voice receipt (TTS in si/ta/en) | — | next |

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest      # Windows: ..\.venv\Scripts\python -m pytest
```

The suite contains **284 tests** covering the full demo through the HTTP API (photo → review → member OK → workbook column G), every quality-gate photo, every ledger rule, concurrency, the WhatsApp webhook's signature and duplicate handling, and edge cases such as opening totals, unexpected months and large changes in member count.

## Using the flow without the dashboard

With the app running (on Windows PowerShell use `curl.exe`):

```bash
curl -F sender=demo -F lang=ta -F image=@samples/synthetic/vasantham_2026-10_p1.jpg localhost:8000/api/sim/message
curl -F sender=demo -F image=@samples/synthetic/vasantham_2026-10_p2.jpg localhost:8000/api/sim/message
curl -F sender=demo -F text=OK localhost:8000/api/sim/message
curl -o gn.xlsx localhost:8000/api/workbook
```

Vasantham's report is clean, so it proceeds straight to the member's summary; "OK" records it.

## Development

- **Dashboard:** `cd frontend && npm install && npm run dev` gives hot reload on `:5173` (API proxied to `:8000`). `npm run build` refreshes `frontend/dist`, which the backend serves. Node is only required to *edit* the dashboard, not to run it.
- **Sample photos:** `.venv/bin/python tools/make_synthetic_forms.py` regenerates the sample reports deterministically (four reports × two pages, plus six deliberately bad photos).
- **Demo workbook:** `.venv/bin/python tools/seed_demo_workbook.py --check` verifies every seeded month balances.
- **Dependencies:** `backend/requirements.txt` allows up to the next major release; `backend/requirements.lock.txt` pins the exact tested versions.

## Adapting to another form or partner

Copy the YAML config, render the blank form, run `tools/learn_layout.py`, and adjust the `workbook:` section. A new layout that uses the same weekly-table structure requires no code changes.

## Before a real pilot

The prototype runs on a single laptop and listens only on `localhost`. Before Palmera uses it with real members:

- **Access & security:** officer login and roles. Today anyone who can reach the server can use it — acceptable on `localhost`, but not online. Expose only `/webhook/whatsapp` publicly, disable the simulator (`SHG_DISABLE_SIMULATOR=1`) and set `WHATSAPP_APP_SECRET`. In live mode the webhook refuses unsigned posts unless the app secret is set, so a missing secret stops messages rather than allowing anyone to post as a member.
- **WhatsApp:** the 24-hour messaging rule means late summaries/receipts need approved *template* messages (not yet implemented). Failed sends (expired token, number not on the allow-list, 24-hour rule) are shown on the report as **Not delivered** with a **Resend** button.
- **Members & data:** a list linking phone numbers to SHGs; consent wording agreed with Palmera under Sri Lanka's Personal Data Protection Act No. 9 of 2022 (photos reach an AI service in live mode, requiring a data-processing agreement); a retention and deletion policy for photos and chats in `data/`.
- **Language & data quality:** a native-speaker check of the Sinhala and Tamil messages (lines marked `# native check`); writing to Palmera's live Google Sheet via the Sheets API; running the reader on real filled forms and re-tuning quality thresholds. **This has not been done yet** — every figure in the demo comes from synthetic sample photos.
- **Running costs:** see *Running costs and operations* in [`docs/GUIDE.md`](docs/GUIDE.md#7-running-costs-and-operations) for the cost drivers, a worked estimate and how to measure them in the pilot.

## Documentation

- [`docs/GUIDE.md`](docs/GUIDE.md) — how to use the app, for officers, members and presenters, plus troubleshooting
- [`docs/form-to-workbook.md`](docs/form-to-workbook.md) — field mapping and every validation rule
- [`docs/palmera-findings-and-questions.md`](docs/palmera-findings-and-questions.md) — formula bugs found in Palmera's workbooks, and open questions
