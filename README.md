# SHG Reports: Palmera, Sri Lanka

APRU hackathon. This project turns Palmera's paper "Monthly Report of the SHG to Cluster" into checked entries in Palmera's own GN monitoring workbook. Women keep filling in the same paper form; once a month someone photographs it and sends it on WhatsApp.

```
photo on WhatsApp ─► quality gate ─► align to the form grid ─► 2 independent Claude readings
   ▲   (retake message in si/ta/en)                                    │
   │                                                                   ▼
receipt ◄─ write to GN workbook ◄─ member confirms ◄─ officer review ◄─ ledger checks
```

**New here?** Start the app (below) and open **Guide** in the sidebar. It explains the app for officers, for members and for whoever presents the demo. The same guide, printable, is in [`docs/GUIDE.md`](docs/GUIDE.md).

## Run it

You need **Python 3.10 or newer** (https://www.python.org/downloads/). On Windows, tick **"Add python.exe to PATH"** in the installer.

**Windows**
1. Right-click the zip → **Extract All**. Extract to a plain folder such as `C:\shg-digitiser`, not OneDrive, Desktop or Documents if those sync to OneDrive; syncing the libraries folder is slow and can lock files. If you end up with `shg-digitiser\shg-digitiser`, use the inner folder.
2. Double-click **`run.bat`**. If Windows says "Windows protected your PC", click **More info → Run anyway**.

**Mac / Linux:** open a terminal in the folder and run `bash run.sh`.

The first run installs the libraries into a `.venv` folder. That's about 70–80 MB to download and a few minutes, so do it the day before, not on venue Wi-Fi. The browser opens **http://localhost:8000** by itself as soon as the app answers.

- Keep the black window open while you use the app. To stop it, close the window or press Ctrl+C.
- If port 8000 is busy, the window says so. SHG Reports is probably already running, so just open http://localhost:8000.
- If something goes wrong, the window says what to do. A half-finished install is cleaned up and redone automatically on the next run.
- The raw API is at http://localhost:8000/docs.

## Demo script (about 3 minutes)

Before you start: use a window of at least 1440 × 900 (1280 × 720 works). Check that the sidebar says **Offline demo**; if it says "Reading with Claude", see *Modes* below. Press **Restart demo**, then turn on **Show phone beside** so the audience sees the member's phone and the officer screen together. The **Demo guide** in the sidebar ticks off each step as it happens.

1. **Member's phone:** choose **தமிழ்**, then send *Kalaimagal, Oct, page 1*. The bot asks for page 2, with an English line under each Tamil message. Send *page 2*: "an officer is checking a few numbers".
2. **Needs review → Kalaimagal:** the report opens on the most likely misreading, *Interest repaid, week 3*. The photo glides to the handwriting: it says **310**, but both readings said **810**. The app says "**310** would make 3 checks balance". Click **Use 310**: "3 checks cleared", and four checks drop to one.
3. Next is *Savings, week 2*, where the two readings disagree (2,800 vs 2,300). Click **Reading 1 (2,800)** and press **Enter**. Everything checks out, so press **Send to member**.
4. On the phone beside, the nine-item Tamil summary arrives. Tap **OK** and the receipt comes back with her group's total savings so far.
5. The report now says **Written to Palmera's workbook: tab Kalaimagal, column G, 16 cells**, listing each cell's old and new value.
6. **Groups → Sisila:** attendance, savings and repayments are all slipping. Each warning says what it means and what an officer would do.
7. **Download workbook:** it opens on the Kalaimagal tab. In column G (October), row 19 (mother-book cash, Rs 20,160) equals row 20, Palmera's own "cash from app" formula.

Also worth showing:
- a **problem photo** (Blurry, Glare, Steep angle…), to show the retake message in her language;
- the **•••** menu on a report: **Send anyway…** and **Ask for a new photo…**;
- **Palmera's own workbook bug**: rows 28–29 of every tab ("Total loan write-off to date", "Loans outstanding") are wrong even before the app writes anything. See `docs/palmera-findings-and-questions.md`. It shows we worked from their real sheet.

Don't open the **SHG Monitoring** tab in Excel or LibreOffice: it uses Google Sheets-only formulas and shows "Can't find". It works in Google Sheets.

If something goes wrong on stage, press **Restart demo**. It clears the reports and the phone.

## Modes

- **No `ANTHROPIC_API_KEY` → Offline demo.** The sample photos in `samples/synthetic/` are "read" from their answer key, with planted reading mistakes (810 for 310, and a 2,800 / 2,300 disagreement) so the review flow has something to catch. No network is needed. A photo that isn't one of the samples is politely refused, never invented.
- **With `ANTHROPIC_API_KEY` → Reading with Claude.** Real forms are read twice by Claude. `SHG_EXTRACTION_MODEL` sets the model (default `claude-opus-5-5`). For the scripted demo, unset the key first (Windows: `set ANTHROPIC_API_KEY=` in the window before `run.bat`).

| Setting | What it does |
|---|---|
| `ANTHROPIC_API_KEY` | Turns on real handwriting reading |
| `SHG_EXTRACTION_MODEL` | Claude model to use (default `claude-opus-5-5`) |
| `SHG_DATA_DIR` | Where reports, photos and chats are stored (default `data/`) |
| `SHG_WORKBOOK` | The GN workbook to write into (default `data/gn_workbook.xlsx`, seeded with three demo groups on first run) |
| `SHG_ALLOW_RESET=1` | Allows **Restart demo** outside offline mode |
| `SHG_DISABLE_SIMULATOR=1` | Turns off the phone simulator endpoints (for a real deployment) |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID` | Meta WhatsApp Cloud API access token and the programme number's id |
| `WHATSAPP_VERIFY_TOKEN` | Secret for Meta's webhook handshake (the handshake is refused without it) |
| `WHATSAPP_APP_SECRET` | Meta app secret. Every webhook POST must then carry a valid `X-Hub-Signature-256` |
| `WHATSAPP_API_VERSION` | Graph API version (default `v21.0`) |

The first run creates `data/gn_workbook.xlsx` from Palmera's template, with June–September recorded for Kalaimagal, Vasantham and Sisila. Delete the `data/` folder to start completely fresh.

## What's built

| Part | File | Status |
|---|---|---|
| Form template config: fields, shaded cells, roll-up rules, workbook rows, thresholds | `backend/app/config/palmera_shg_monthly_v3.yaml` | done |
| Grid layout of the printed form | `…/palmera_shg_monthly_v3.layout.json`, `tools/learn_layout.py` | done |
| Image quality gate: too small, dark, blurry, not found, cut off, too far, glare, shadow, steep angle; retake messages in en/si/ta | `backend/app/imaging/quality.py` | done; thresholds tuned on synthetic photos |
| Photo alignment: deskew, perspective, table grid, per-cell crops, audit boxes | `backend/app/imaging/grid.py`, `layout.py` | done |
| Two-pass Claude reading (structured output), ink cross-check, typed failures (refusal, cut-off answer, network) | `backend/app/extraction.py` | done; **not yet run on real handwritten forms** |
| Validation: capture, ledger arithmetic, continuity, ranges, findings; suggests the value that would balance the checks and ranks the likeliest misreading | `backend/app/validation.py` | done |
| Weekly → monthly roll-up | `backend/app/aggregate.py` | done |
| Workbook writer: per-SHG tab, rows found by label, never touches formulas, refuses silent overwrites, atomic save | `backend/app/workbook.py` | done (.xlsx; Google Sheets API version next) |
| Pipeline: status flow, officer and member actions, superseded reports, audit history, one lock around every change | `backend/app/pipeline.py`, `locking.py` | done |
| Bot messages in en/si/ta (Palmera's own Sinhala/Tamil row labels), privacy note, STOP | `backend/app/messages.py` | done; new si/ta sentences marked `# native check` |
| WhatsApp Cloud API connector: signature check, duplicate delivery ignored | `backend/app/whatsapp.py`, `conversations.py` | done; needs a Meta app to test live |
| REST API and phone simulator | `backend/app/api.py` | done |
| Officer dashboard (React): review queue, photo zoom-to-value with suggestions, keyboard review, recorded-cells card, Groups financial health and early warnings, phone simulator and presenter mode, in-app Guide; light/dark, phone-sized screens | `frontend/` | done |
| Voice receipt (TTS in si/ta/en) | — | next |

## Tests

`cd backend && ../.venv/bin/python -m pytest` (Windows: `..\.venv\Scripts\python -m pytest`). This runs TEST_COUNT tests, including:
- the whole demo through the HTTP API (photo → review → member OK → workbook column G);
- every quality-gate photo;
- every ledger rule;
- concurrency;
- the WhatsApp webhook's signature and duplicate handling.

## Try the flow without the dashboard

From the project folder, with the app running. On Windows PowerShell type `curl.exe` instead of `curl`.
```bash
curl -F sender=demo -F lang=ta -F image=@samples/synthetic/vasantham_2026-10_p1.jpg localhost:8000/api/sim/message
curl -F sender=demo -F image=@samples/synthetic/vasantham_2026-10_p2.jpg localhost:8000/api/sim/message
curl -F sender=demo -F text=OK localhost:8000/api/sim/message
curl -o gn.xlsx localhost:8000/api/workbook
```
Vasantham's report is clean, so it goes straight to the member's summary; "OK" records it.

## Change things

- **Dashboard:**
  - `cd frontend && npm install && npm run dev` gives hot reload on :5173, with the API proxied to :8000 (set `SHG_API` to use another port).
  - `npm run build` updates `frontend/dist`, which the backend serves.
  - Node is only needed to *edit* the dashboard, not to run it.
- **Sample photos:** `.venv/bin/python tools/make_synthetic_forms.py` regenerates 4 groups × 2 pages plus 6 deliberately bad photos. It's deterministic: the same files every time.
- **Demo workbook:** `.venv/bin/python tools/seed_demo_workbook.py --check` shows that every seeded month balances (row 19 = row 20).
- **Library versions:** `backend/requirements.txt` allows versions up to the next major release. `backend/requirements.lock.txt` pins the exact tested versions, for Windows with Python 3.11–3.13.

## Adapting to another form or partner

Copy the YAML config, render the blank form, run `tools/learn_layout.py`, and adjust the `workbook:` section. A new layout that uses the same kind of weekly table needs no code changes.

## Before a real pilot

The prototype runs on one laptop and listens only on `localhost`. Before Palmera uses it with real members:

- **Access:** officer login and roles. Today anyone who can reach the server can use it, which is fine on localhost but not online. Expose only `/webhook/whatsapp` publicly, with `WHATSAPP_APP_SECRET` set and the simulator turned off.
- **Members:**
  - a list linking phone numbers to SHGs;
  - consent wording agreed with Palmera under Sri Lanka's Personal Data Protection Act No. 9 of 2022, since photos go to an AI service in live mode and that needs a data-processing agreement;
  - a retention period and deletion for photos and chats in `data/`.
- **Language and data:**
  - a native-speaker check of the bot's Sinhala and Tamil (lines marked `# native check`);
  - writing to Palmera's live Google Sheet through the Sheets API;
  - running the reader on real filled forms and re-tuning the quality thresholds.

## Docs
- [`docs/GUIDE.md`](docs/GUIDE.md): how to use it, for officers, members and presenters, plus troubleshooting
- [`docs/form-to-workbook.md`](docs/form-to-workbook.md): field mapping and every validation rule
- [`docs/palmera-findings-and-questions.md`](docs/palmera-findings-and-questions.md): formula bugs found in Palmera's workbooks, and open questions
