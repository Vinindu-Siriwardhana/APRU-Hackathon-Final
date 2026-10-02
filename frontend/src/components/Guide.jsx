const TABS = [
  { id: "officers", label: "Officers" },
  { id: "members", label: "Members" },
  { id: "presenting", label: "Presenting the demo" },
];

/** The in-app guide: for monitoring officers, for SHG members, and for whoever presents the demo. */
export default function Guide({ tab, offline }) {
  const cur = TABS.find((t) => t.id === tab)?.id || "officers";
  return (
    <div className="guide-view">
      <div className="guide">
        <header className="guide-head">
          <h1 className="pane-title">Guide</h1>
          <p className="pane-sub">How SHG Reports works, for officers, for members and for whoever is presenting it.</p>
          <div className="segmented guide-tabs" role="tablist" aria-label="Guide sections">
            {TABS.map((t) => (
              <a key={t.id} role="tab" href={`#/guide/${t.id}`} aria-selected={cur === t.id} className={cur === t.id ? "is-on" : ""}>
                {t.label}
              </a>
            ))}
          </div>
        </header>
        <div role="tabpanel" aria-label={TABS.find((t) => t.id === cur).label}>
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
        ledger adds up, and only asks you about the figures that don’t. Nothing reaches Palmera’s workbook until you’ve checked it and the
        member has confirmed it.
      </p>

      <Section title="What each status means">
        <dl className="guide-dl">
          <div><dt><span className="tag tone-grey">Waiting for photos</span></dt><dd>Page 1 or page 2 hasn’t arrived yet. If only page 1 ever comes, open the report and choose Read page 1 now.</dd></div>
          <div><dt><span className="tag tone-orange">Needs review</span></dt><dd>Some figures don’t add up, or the two readings disagree. Your turn.</dd></div>
          <div><dt><span className="tag tone-green">Ready to send</span></dt><dd>Every check passes. Send it to the member to confirm.</dd></div>
          <div><dt><span className="tag tone-blue">Waiting for member</span></dt><dd>She has a short summary on WhatsApp and replies OK, or the item number and the right figure.</dd></div>
          <div><dt><span className="tag tone-green">Recorded</span></dt><dd>She said OK and the month is written to the group’s tab in Palmera’s workbook. She gets a receipt.</dd></div>
          <div><dt><span className="tag tone-red">Couldn’t read</span></dt><dd>The photos couldn’t be read (no connection, or not the form). Try again, or ask for a new photo.</dd></div>
          <div><dt><span className="tag tone-grey">Replaced</span></dt><dd>A newer report for the same group and month arrived, so this one is set aside. Nothing from it is written.</dd></div>
          <div><dt><span className="tag tone-grey">New photo asked</span></dt><dd>You asked her to send the photos again, or she replied STOP.</dd></div>
        </dl>
      </Section>

      <Section title="How the checks work">
        <p>The form already contains its own arithmetic: each row has a total, each week’s income and spending add up, and last week’s cash plus this week’s money gives the expected balance. The app checks every one of these sums, and that the month follows on from the one already in the workbook.</p>
        <p>A reading mistake almost always breaks more than one sum. One wrong digit in “Interest repaid, week 3” upsets the interest row total, week 3’s income and week 3’s balance.</p>
      </Section>

      <Section title="Why “Most likely” comes first">
        <p>The value that appears in the most failing checks is the likeliest misreading, so the report opens there and the photo zooms to that handwriting. When one figure would make all those checks balance, the app says so: “310 would make 3 checks balance”. Fix that one figure and three checks clear at once.</p>
      </Section>

      <Section title="Use, Save or Keep">
        <ul className="guide-list">
          <li><strong>Use 310</strong>: the handwriting shows the suggested figure. One click saves it.</li>
          <li><strong>Save</strong>: type the figure you see on the photo. The box is already selected, so just type. Enter saves and moves to the next flagged value.</li>
          <li><strong>Keep 810</strong>: the photo really says what was read. The figure stays as written and is marked “Checked against the photo, kept as written”, so the same check won’t hold the report up again. It does not hide a real problem: Palmera sees the sums as the group wrote them.</li>
        </ul>
        <p>When the two readings disagree, both are shown. Pick the one that matches the handwriting, then press Enter.</p>
        <p className="guide-keys"><kbd>Enter</kbd> save and go to the next <kbd>Esc</kbd> close <kbd>J</kbd> next flagged value <kbd>K</kbd> previous</p>
      </Section>

      <Section title="When the member corrects a figure">
        <p>After the summary she may reply “5 12000”: item 5 should be 12,000. The bot tells her an officer will check it against her form; nothing changes yet. The report comes back to Needs review showing her figure next to the form’s.</p>
        <ul className="guide-list">
          <li>If the figure adds up from weekly cells, correct those cells against the photo. When they add up to her figure, the question clears by itself.</li>
          <li>If the form is right, choose <strong>Keep the form’s figure</strong>.</li>
          <li><strong>Use her figure</strong> appears only when the figure is a single cell on the form, so the ledger always balances.</li>
        </ul>
      </Section>

      <Section title="A group that isn’t in the workbook">
        <p>If the name on the form doesn’t match a tab, pick the right group from the list (the app corrects the name), or choose It’s a new group and a new tab is made when the month is written.</p>
      </Section>

      <Section title="A month that’s already recorded">
        <p>If the workbook already has this group’s month, the report is held. If the new figures are a genuine correction, use Send anyway and say why; the month is replaced once she confirms. Otherwise ask for a new photo.</p>
      </Section>

      <Section title="Send anyway, or ask for a new photo">
        <p><strong>Send anyway…</strong> (in the ••• menu) sends a report that still has a failing check, for example when you’ve phoned the group and the book really says that. Your reason is kept with the report.</p>
        <p><strong>Ask for a new photo…</strong> closes the report and sends her a simple message in her language saying why: unclear photo, page missing, wrong form, wrong group or month, or parts left empty.</p>
      </Section>

      <Section title="Where the data goes">
        <p>Each group has its own tab in Palmera’s GN workbook, one column per month. The app fills the 16 input rows of that month’s column and never touches a formula. A recorded report shows exactly which cells were written, with the old and new values.</p>
      </Section>

      <Section title="Reading the Groups warnings">
        <p>Groups shows savings, repayments and attendance month by month from the workbook. Warnings appear when attendance drops, when repayments or savings fall three months in a row, or when the cash counted doesn’t match the ledger. Each warning says what it means and what you might do: usually a call to the group leader or a visit.</p>
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
        <p>After an officer has looked, she gets a short list of nine figures for the month, numbered, in her language. If they’re right she replies <strong>OK</strong>. If one is wrong, she replies with its number and the right figure, for example <strong>5 12000</strong>. An officer checks it against her form before anything changes.</p>
        <p>If she writes while the officer is still checking, the bot tells her so. Nothing is lost.</p>
      </Section>
      <Section title="The receipt">
        <p>When she replies OK, the month is recorded and she gets a receipt naming her group and the month. That’s her proof the report arrived.</p>
      </Section>
      <Section title="Privacy">
        <p>The first message tells her: Palmera uses these photos only to record your group’s monthly report. Reply STOP to opt out. Only Palmera’s monitoring officers see the photos and figures in this app. When it runs live, the photos are also read by an AI service (Claude, by Anthropic), so Palmera needs members’ consent and a data-processing agreement under Sri Lanka’s Personal Data Protection Act before going live. Replying STOP closes her open reports; writing again later opts her back in.</p>
      </Section>
    </>
  );
}

function Presenting({ offline }) {
  const steps = [
    { t: "Before you start", d: <>Use a window of at least 1440 × 900 (1280 × 720 works). Check the sidebar says <strong>Offline demo</strong>{offline ? " (it does now)" : " — it doesn’t right now: unset ANTHROPIC_API_KEY and restart for the scripted demo"}. Press <strong>Restart demo</strong>. Turn on <strong>Show phone beside</strong> so the audience sees the phone and the officer screen together.</> },
    { t: "Member’s phone", d: <>Choose <strong>தமிழ்</strong>. Send <strong>Kalaimagal, Oct, page 1</strong>: the bot asks for page 2, with English underneath. Send <strong>page 2</strong>: “an officer is checking a few numbers”.</> },
    { t: "Needs review, Kalaimagal", d: <>The report opens on <strong>Interest repaid, week 3</strong>. The photo glides to the handwriting: it says 310, but it was read as 810. The app says “<strong>310</strong> would make 3 checks balance”. Click <strong>Use 310</strong>: “3 checks cleared”, and four checks drop to one.</> },
    { t: "The second mistake", d: <>Next is <strong>Savings, week 2</strong>, where the two readings disagree (2800 vs 2300). Click <strong>Reading 1, 2800</strong> and press Enter. Everything checks out: press <strong>Send to member</strong>.</> },
    { t: "Back to her phone", d: <>The nine-item Tamil summary arrives, with English under it. Tap <strong>OK</strong>: the receipt comes back.</> },
    { t: "Recorded", d: <>The report shows <strong>Written to Palmera’s workbook: tab Kalaimagal, column G, 16 cells</strong>, with each cell’s old and new value. Download the workbook, open the Kalaimagal tab, column G: row 19 (mother-book cash) equals row 20 (cash from the app).</> },
    { t: "Groups, Sisila", d: <>Attendance, savings and repayments are all slipping; each warning says what it means and what an officer would do.</> },
  ];
  return (
    <>
      <p className="guide-lede">About three minutes. The <strong>Demo guide</strong> in the sidebar ticks each step off as it happens, with a Go link to the right screen.</p>
      <ol className="script">
        {steps.map((s, i) => (
          <li key={i}>
            <span className="script-n" aria-hidden>{i + 1}</span>
            <div><h3>{s.t}</h3><p>{s.d}</p></div>
          </li>
        ))}
      </ol>
      <Section title="Also worth showing">
        <ul className="guide-list">
          <li>A problem photo (Blurry, Glare, Steep angle) to show the retake message, in her language.</li>
          <li>The ••• menu on a report: Send anyway, and Ask for a new photo.</li>
          <li>Palmera’s own workbook bug, rows 28 and 29 of each tab: “Total loan write-off to date” and “Loans outstanding” don’t add up even before the app writes anything. It shows we worked from their real sheet.</li>
        </ul>
      </Section>
      <Section title="What not to open">
        <p>The SHG Monitoring tab uses Google Sheets-only formulas, so Excel and LibreOffice show “Can’t find”. It works in Google Sheets.</p>
      </Section>
      <Section title="If something goes wrong">
        <p>Press Restart demo and start again; it clears the reports and the phone. If the server stopped, the app says “Can’t reach the server” and reconnects by itself once it’s back. The README has the same flow as curl commands.</p>
      </Section>
    </>
  );
}

