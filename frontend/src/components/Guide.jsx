const TABS = [
  { id: "officers", label: "Officers" },
  { id: "members", label: "Members" },
  { id: "presenting", label: "Presenting the demo" },
];

/** ← → Home End move between the guide's tabs (each tab is a link, so the URL follows). */
const tabKeys = (cur) => (e) => {
  const i = TABS.findIndex((t) => t.id === cur);
  const n = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1 : null;
  if (n === null) return;
  e.preventDefault();
  const id = TABS[(n + TABS.length) % TABS.length].id;
  window.location.hash = `/guide/${id}`;
  requestAnimationFrame(() => document.getElementById(`guide-tab-${id}`)?.focus());
};

/** The in-app guide: for monitoring officers, for SHG members, and for whoever presents the demo. */
export default function Guide({ tab, offline }) {
  const cur = TABS.find((t) => t.id === tab)?.id || "officers";
  return (
    <div className="guide-view">
      <div className="guide">
        <header className="guide-head">
          <h1 className="pane-title">Guide</h1>
          <p className="pane-sub">How SHG Reports works, for officers, for members and for whoever is presenting it.</p>
          <div className="segmented guide-tabs" role="tablist" aria-label="Guide sections" onKeyDown={tabKeys(cur)}>
            {TABS.map((t) => (
              <a key={t.id} role="tab" id={`guide-tab-${t.id}`} href={`#/guide/${t.id}`} aria-selected={cur === t.id} aria-controls="guide-panel"
                tabIndex={cur === t.id ? 0 : -1} className={cur === t.id ? "is-on" : ""}>
                {t.label}
              </a>
            ))}
          </div>
        </header>
        <div role="tabpanel" id="guide-panel" aria-labelledby={`guide-tab-${cur}`} tabIndex={0}>
          {cur === "officers" && <Officers />}
          {cur === "members" && <Members />}
          {cur === "presenting" && <Presenting offline={offline} />}
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <section className="guide-section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function Officers() {
  return (
    <>
      <p className="guide-lede">
        Members photograph the same paper form they always fill in and send it on WhatsApp. The app reads every figure twice, checks the
        ledger adds up, and only asks you about the figures that don’t. Nothing reaches Palmera’s workbook until you’ve checked every
        doubtful figure and the member has confirmed her summary.
      </p>

      <Section title="What each status means">
        <dl className="guide-dl">
          <div><dt><span className="tag tone-grey">Waiting for photos</span></dt><dd>Page 1 or page 2 hasn’t arrived yet. If only page 1 ever comes, open the report and choose Read page 1 now.</dd></div>
          <div><dt><span className="tag tone-orange">Needs review</span></dt><dd>Some figures don’t add up, the two readings disagree, or something about the group or month needs your decision. Your turn.</dd></div>
          <div><dt><span className="tag tone-teal">Ready to send</span></dt><dd>Every check passes. Press Send to member.</dd></div>
          <div><dt><span className="tag tone-blue">Waiting for member</span></dt><dd>She has the summary on WhatsApp. She replies OK, or the item number and the right figure.</dd></div>
          <div><dt><span className="tag tone-green">Recorded</span></dt><dd>She said OK, and the month is written to the group’s tab. She has a receipt. The report lists exactly which cells were written, with old and new values.</dd></div>
          <div><dt><span className="tag tone-red">Couldn’t read</span></dt><dd>The photos couldn’t be read (no internet connection, or not the form). Press Try again, or ask for a new photo.</dd></div>
          <div><dt><span className="tag tone-grey">Replaced</span></dt><dd>A newer report for the same group and month arrived. Nothing from this one is written.</dd></div>
          <div><dt><span className="tag tone-grey">New photo asked</span></dt><dd>You asked her to send the photos again, or she replied STOP.</dd></div>
        </dl>
      </Section>

      <Section title="How the checks work">
        <p>The paper form already contains its own arithmetic: each row has a Total, each week’s income and spending add up to the totals, last week’s cash plus this week’s income minus this week’s spending gives the expected balance, and savings to date and loans outstanding carry on from week to week. The app checks every one of these sums. It also checks that the month follows on from the one already in the workbook, that the member count hasn’t jumped, and that figures are within Palmera’s limits.</p>
        <p>A weekly figure is part of several sums at once, so a misread digit breaks every one of them that the group filled in. In the demo, “Interest repaid, week 3” read as 810 instead of 310 breaks three: the interest row’s Total, week 3’s Total Income and week 3’s Expected Balance.</p>
      </Section>

      <Section title="Why “Most likely” comes first">
        <p>The figure that appears in the most failing checks is the likeliest misreading. The report opens on it, and the photo glides to its handwriting. When one value would make all of those checks balance, the app says so: “310 would make 3 checks balance”. Fix that one figure and three checks clear at once.</p>
      </Section>

      <Section title="Use, Save or Keep">
        <ul className="guide-list">
          <li><strong>Use 310</strong>: the handwriting shows the suggested figure. One click saves it.</li>
          <li><strong>Save</strong>: type the figure you see on the photo. The box is already selected, so just type. Enter saves and moves to the next flagged value.</li>
          <li><strong>Keep 810</strong>: the photo really says what was read. The figure stays as written and is marked “Checked against the photo, kept as written”. A sum whose cells you have all checked this way no longer holds the report up: the paper itself doesn’t add up, and Palmera sees the sums as the group wrote them. This never applies to Palmera’s limits or to the group-and-month decisions below.</li>
        </ul>
        <p>When the two readings disagree, both are shown. Pick the one that matches the handwriting, then press Enter.</p>
        <p className="guide-keys"><kbd>Enter</kbd> save and go to the next <kbd>Esc</kbd> close <kbd>Alt ↓</kbd> next flagged value <kbd>Alt ↑</kbd> previous</p>
      </Section>

      <Section title="When the member corrects a figure">
        <p>After the summary she may reply “5 12000”: item 5 (Savings) should be 12,000. The bot tells her an officer will check it against her form; nothing changes yet. The report comes back to Needs review, showing her figure next to the form’s.</p>
        <ul className="guide-list">
          <li>If the figure adds up from weekly cells (e.g. Savings), correct those cells against the photo. When they add up to her figure, the question clears by itself.</li>
          <li>If the form is right, choose <strong>Keep the form’s figure</strong>.</li>
          <li><strong>Use her figure</strong> appears only when the figure is a single cell on the form, so the ledger always still balances.</li>
        </ul>
      </Section>

      <Section title="A group that isn’t in the workbook">
        <p>If the name on the form doesn’t match a tab, the report is held. Pick the right group from the list (this corrects the name), or choose <strong>It’s a new group</strong>. A new tab is made when the month is written, and its first month needs the group’s opening “to date” totals, all from before this month:</p>
        <ul className="guide-list">
          <li><strong>The group started this month</strong>: its opening totals are all zero. If the form says otherwise (savings to date of Rs 65,000 when this month’s savings are only Rs 12,400), the app stops and asks for the mother-book totals.</li>
          <li><strong>An existing group, new to the app</strong>: enter all nine totals from the group’s mother book (0 is allowed). Where the form itself shows savings to date or loans outstanding, the app fills those in and checks your figures against it.</li>
        </ul>
        <p>You can change the opening totals until the month is written. Week 1’s checks start from them, as they would from last month.</p>
      </Section>

      <Section title="A month that’s unexpected">
        <ul className="guide-list">
          <li><strong>More than one month after the last recorded month</strong>: usually a misread month or year, which would put the figures in the wrong column. Check the month on the photo and correct it. If months really are missing, confirm it as written: it becomes a “month missing” warning.</li>
          <li><strong>More than a month in the future</strong>: check the photo, and confirm it as written only if it really is right.</li>
          <li><strong>Outside the group’s sheet</strong> (each tab has 24 month columns): check the month. If it’s right, the person who manages the workbook has to add a sheet.</li>
        </ul>
      </Section>

      <Section title="A big change in member count">
        <p>A change of more than 5 members and more than 25% from last month holds the report, because a misread count skews every attendance rate. Check the count on the photo: correct it, or confirm it as written if the group really changed. Smaller changes are only a warning. The member count is item 10 of her summary, so she sees it too.</p>
      </Section>

      <Section title="A month that’s already recorded">
        <p>If the workbook already has this group’s month, the report is held. If the new figures are a genuine correction, use Send anyway and give the reason; the month is replaced once she confirms. Otherwise ask for a new photo.</p>
      </Section>

      <Section title="Send anyway, or ask for a new photo">
        <p><strong>Send anyway…</strong> (in the ••• menu) sends a report that still has a failing check, for example after you phoned the group and the book really says that. Your reason is kept with the report. It can’t skip an unknown group, a new group’s opening totals that don’t match the form, a month outside the sheet, an unexpected month or an already-recorded month: each of those needs its own decision first.</p>
        <p><strong>Ask for a new photo…</strong> closes the report and sends her a simple message in her language saying why: unclear photo, page missing, wrong form, wrong group or month, or parts left empty. You can add a private note; it is not sent to her.</p>
      </Section>

      <Section title="When a WhatsApp message isn’t delivered">
        <p>In live mode every message the bot sends is checked. A send that fails shows <strong>Not delivered</strong> on the report, with the reason. The usual one is WhatsApp’s 24-hour rule: after 24 hours without a message from her, only approved template messages can be sent. Ask her to send any message, then press <strong>Resend</strong>. For an expired access token or a number that isn’t on the test list, fix the setup, then press Resend. Check for Not delivered every day: a member who never gets her summary can’t confirm it. The demo’s phone simulator never shows it.</p>
      </Section>

      <Section title="Where the data goes">
        <p>Each group has its own tab in Palmera’s GN workbook, with one column per month (June 2026 is column C). The app fills the month’s 16 input rows and never touches a formula. Download workbook in the sidebar gives the current file.</p>
      </Section>

      <Section title="Reading the Groups page">
        <p>Groups shows each group month by month, from the workbook: savings growth, repayments, attendance, and cash against the ledger. Early warnings appear when attendance is below 60% or down 15 points, when savings or loan repayments fall three months in a row, when the cash counted doesn’t match the ledger, or when there’s no recent report. Each warning says what it means, and most say what you might do, usually a call to the group leader or a visit. Groups that need attention are listed first.</p>
      </Section>
    </>
  );
}

/** Flat little drawings for members: how to take a photo the app can read. */
function Illustration({ kind }) {
  const page = (x, y, w, h, n) => (
    <g>
      <rect x={x} y={y} width={w} height={h} rx="2" className="il-page" />
      {[0.22, 0.36, 0.5, 0.64, 0.78].map((f) => <line key={f} x1={x + w * 0.14} x2={x + w * 0.86} y1={y + h * f} y2={y + h * f} className="il-line" />)}
      {n && <text x={x + w / 2} y={y + h * 0.15} className="il-num" textAnchor="middle">{n}</text>}
    </g>
  );
  return (
    <svg viewBox="0 0 120 90" className="illustration" aria-hidden>
      {kind === "flat" && (
        <>
          <path d="M14 76h92" className="il-table" />
          <path d="M30 74l6-14h48l6 14z" className="il-page" />
          <rect x="44" y="8" width="32" height="20" rx="4" className="il-phone" />
          <path d="M60 32v18m0 0-4-4m4 4 4-4" className="il-arrow" />
        </>
      )}
      {kind === "whole" && (
        <>
          <rect x="34" y="6" width="52" height="78" rx="8" className="il-phone" />
          {page(42, 16, 36, 58)}
          <path d="M40 14h6M40 14v6M80 14h-6M80 14v6M40 76h6M40 76v-6M80 76h-6M80 76v-6" className="il-arrow" />
        </>
      )}
      {kind === "light" && (
        <>
          <circle cx="40" cy="40" r="11" className="il-sun" />
          {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => (
            <line key={a} x1={40 + 16 * Math.cos((a * Math.PI) / 180)} y1={40 + 16 * Math.sin((a * Math.PI) / 180)} x2={40 + 21 * Math.cos((a * Math.PI) / 180)} y2={40 + 21 * Math.sin((a * Math.PI) / 180)} className="il-ray" />
          ))}
          <path d="M84 24l-10 18h9l-6 18 14-22h-9l6-14z" className="il-flash" />
          <path d="M70 22l28 42" className="il-no" />
        </>
      )}
      {kind === "order" && (
        <>
          {page(14, 14, 38, 56, "1")}
          <path d="M56 42h10m0 0-4-4m4 4-4 4" className="il-arrow" />
          {page(70, 14, 38, 56, "2")}
        </>
      )}
    </svg>
  );
}

function Members() {
  const tips = [
    { kind: "flat", title: "Lay it flat, take it from above", text: "Put the form on a table and hold the phone straight above it, not at an angle." },
    { kind: "whole", title: "Get the whole page in", text: "All four corners should be inside the photo. Step back a little if they aren’t." },
    { kind: "light", title: "Daylight, no flash", text: "Near a window is best. The flash makes a shiny patch that hides numbers." },
    { kind: "order", title: "Page 1, then page 2", text: "Send page 1 first. The bot asks for page 2 when page 1 is clear." },
  ];
  return (
    <>
      <p className="guide-lede">
        Members keep filling in the paper form they know. Once a month, someone in the group sends two photos on WhatsApp. Everything the bot
        says is in Sinhala, Tamil or English, whichever she uses.
      </p>
      <Section title="Taking the photos">
        <ul className="tips">
          {tips.map((t) => (
            <li key={t.kind} className="tip">
              <Illustration kind={t.kind} />
              <h3>{t.title}</h3>
              <p>{t.text}</p>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="If the bot asks for another photo">
        <p>Each photo is checked the moment it arrives, so she can retake it straight away, while the form is still in front of her. The bot says why, in simple words:</p>
        <ul className="guide-list">
          <li><strong>Blurry</strong>: hold the phone still, or rest your elbows on the table.</li>
          <li><strong>Too dark</strong> or <strong>shadow</strong>: move nearer a window, and keep the phone’s shadow off the page.</li>
          <li><strong>Shiny patch</strong>: turn off the flash, or tilt the page away from the light.</li>
          <li><strong>Cut off</strong> or <strong>too far</strong>: get the whole page in, filling the screen.</li>
          <li><strong>From an angle</strong>: hold the phone straight above the page.</li>
        </ul>
      </Section>
      <Section title="Checking the numbers">
        <p>After an officer has looked, she gets a numbered list of ten items for the month, in her language: group, month, meetings held, total attendance, savings, loan repayments, interest, loans given, cash in hand at month end, and members. If they’re all right she replies <strong>OK</strong>. If one is wrong, she replies with its number and the right figure, for example <strong>5 12000</strong> (“5. 12,000” and “5 Rs.12000/=” also work). An officer checks it against her form before anything changes.</p>
        <p>If she writes while the officer is still checking, the bot tells her so. Nothing is lost.</p>
      </Section>
      <Section title="The receipt">
        <p>When she replies OK, the month is recorded. The receipt names her group and the month, repeats the month’s savings, repayments and cash, and gives her group’s total savings so far. That’s her proof the report arrived, and every member can see the group’s savings, not just the treasurer.</p>
      </Section>
      <Section title="Privacy">
        <p>The first message tells her: Palmera uses these photos only to record your group’s monthly report. Reply STOP to opt out. Only Palmera’s monitoring officers see the photos and figures in this app. When it runs live, the photos are also read by an AI service (Claude, by Anthropic), so Palmera needs members’ consent and a data-processing agreement under Sri Lanka’s Personal Data Protection Act before going live. Replying STOP closes her open reports; writing again later opts her back in.</p>
      </Section>
    </>
  );
}

function Presenting({ offline }) {
  const steps = [
    { t: "Member’s phone", d: <>Choose <strong>தமிழ்</strong>. Send <strong>Kalaimagal, Oct, page 1</strong>: the photo is checked instantly, and a few seconds later the bot asks for page 2, with English underneath. Send <strong>page 2</strong>: a few seconds later, “an officer is checking a few numbers”.</> },
    { t: "Needs review, Kalaimagal", d: <>It opens on <strong>Interest repaid, week 3</strong>. The photo glides to the handwriting: it says 310, but it was read as 810. Only the ledger caught it: “<strong>310</strong> would make 3 checks balance”. Click <strong>Use 310</strong>: “3 checks cleared”, and four checks drop to one.</> },
    { t: "The second mistake", d: <>Next is <strong>Savings, week 2</strong>, where the two readings disagree (2,800 vs 2,300). Click <strong>Reading 1</strong> (2,800) and press Enter. A person decides, never the machine. Everything checks out: press <strong>Send to member</strong>.</> },
    { t: "Back to her phone", d: <>After a few seconds the ten-item Tamil summary arrives, with English under it. Tap <strong>OK</strong>: a few seconds later the receipt comes back, with her group’s total savings so far (Rs 95,400).</> },
    { t: "Recorded", d: <>The report shows <strong>Written to Palmera’s workbook</strong>: tab Kalaimagal, column G, 16 cells, each with its old and new value. She confirmed the summary; every other figure passed the ledger checks.</> },
    { t: "Groups, Sisila", d: <>Attendance, savings and repayments are all slipping. Each warning explains itself.</> },
    { t: "Download workbook", d: <>Open the Kalaimagal tab, column G. If Excel shows Protected View, click <strong>Enable Editing</strong> first, or the formula rows stay blank. Row 19 (mother-book cash, Rs 20,160) equals row 20, Palmera’s own formula.</> },
  ];
  return (
    <>
      <p className="guide-lede">About three minutes. The <strong>Demo guide</strong> in the sidebar ticks each step off as it happens, with a Go link to the right screen. Each reply takes a few seconds: wait for it rather than clicking twice.</p>
      <Section title="Before you start">
        <ul className="guide-list">
          <li>Install and start it once the day before: the first run downloads about 70–90 MB.</li>
          <li>Use a window of at least 1440 × 900 (1280 × 720 works).</li>
          <li>Check the sidebar says <strong>Offline demo</strong>{offline ? " (it does now)." : ". It doesn’t right now: close the app, unset ANTHROPIC_API_KEY and start it again for the scripted demo."}</li>
          <li>Press <strong>Restart demo</strong>, then turn on <strong>Show phone beside</strong> so the audience sees the phone and the officer screen together. The sidebar then shows icons only: Needs review is the tray icon at the top, Groups the chart icon, Download workbook the download icon near the bottom.</li>
          <li>The Demo guide folds itself away when a report opens, so it never covers the photo.</li>
        </ul>
      </Section>
      <Section title="The script">
        <ol className="script">
          {steps.map((s, i) => (
            <li key={i}>
              <span className="script-n" aria-hidden>{i + 1}</span>
              <div><h3>{s.t}</h3><p>{s.d}</p></div>
            </li>
          ))}
        </ol>
      </Section>
      <Section title="Also worth showing">
        <ul className="guide-list">
          <li>A problem photo (Blurry, Glare, Steep angle) to show the retake message, in her language.</li>
          <li><strong>Sisila, Oct</strong> (best in සිංහල): a smudged cell, Principal repaid, week 4, that the reader marks unclear, so the officer checks it on the photo.</li>
          <li><strong>Kalaimagal, Nov</strong>: after the October script it follows on cleanly and goes straight to her summary. Sent before October is recorded, the app holds it: “The form says November 2026, but the last month recorded for this group is September 2026”.</li>
          <li>The ••• menu on a report: Send anyway, and Ask for a new photo.</li>
          <li>Palmera’s own workbook bug, rows 28 and 29 of each tab: “Total loan write-off to date” and “Loans outstanding” are wrong even before the app writes anything. It shows we worked from their real sheet.</li>
        </ul>
      </Section>
      <Section title="What not to open">
        <p>The SHG Monitoring tab uses Google Sheets-only formulas, so Excel and LibreOffice show “Can’t find”. It works in Google Sheets.</p>
      </Section>
      <Section title="If something goes wrong">
        <p>Press Restart demo and start again from step 1; it clears the reports and the phone. If the server stopped, the app says “Can’t reach the server” and reconnects by itself once it’s back. To show the same flow without the dashboard, the README has curl commands that send Vasantham’s clean report through the API.</p>
      </Section>
      <Section title="If a judge asks">
        <ul className="guide-list">
          <li><strong>Is the handwriting really read by AI?</strong> Not on stage: offline demo mode reads the sample photos from their answer key, with planted mistakes. With an API key, Claude reads each form twice. That path is built but has not yet been run on real handwritten forms; that’s the next step, with Palmera.</li>
          <li><strong>What does it cost?</strong> Mostly the Claude reading: 4 requests per report. Our estimate with the default model is about US$0.20–0.36 per report, or $20–36 a month for 100 groups, plus a small server; WhatsApp replies inside 24 hours are free. It’s an estimate, not a measurement: docs/GUIDE.md, section 7, has the assumptions and how to measure it in the pilot.</li>
        </ul>
      </Section>
    </>
  );
}
