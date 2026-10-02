import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { WORKBOOK_URL, api, store } from "./api.js";
import { useHashRoute, go } from "./route.js";
import { usePhone } from "./usePhone.js";
import DemoChecklist, { demoSteps } from "./components/DemoChecklist.jsx";
import Groups from "./components/Groups.jsx";
import Guide from "./components/Guide.jsx";
import Icon from "./components/Icon.jsx";
import Inbox from "./components/Inbox.jsx";
import PhonePage, { PhoneDevice } from "./components/Phone.jsx";
import Sheet from "./components/Sheet.jsx";
import Toast from "./components/Toast.jsx";

const NAV = [
  { id: "needs_review", label: "Needs review", short: "Review", icon: "tray" },
  { id: "awaiting_member", label: "Waiting for member", short: "Waiting", icon: "clock" },
  { id: "written", label: "Recorded", short: "Recorded", icon: "check" },
  { id: "all", label: "All reports", short: "All", icon: "stack" },
];
const MODE_TIP = "Readings come from each sample photo’s answer key, with planted mistakes, so the demo runs without internet.";

function useMedia(query) {
  const get = () => typeof window !== "undefined" && !!window.matchMedia?.(query).matches;
  const [on, setOn] = useState(get);
  useEffect(() => {
    const m = window.matchMedia(query);
    const fn = () => setOn(m.matches);
    m.addEventListener("change", fn);
    return () => m.removeEventListener("change", fn);
  }, [query]);
  return on;
}

export default function App() {
  const route = useHashRoute();
  const [view, a, b] = route;
  const [subs, setSubs] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [failures, setFailures] = useState(0);
  const [status, setStatus] = useState(null);
  const [template, setTemplate] = useState(null);
  const [toast, setToast] = useState(null);
  const [tick, setTick] = useState(0);
  const [sheet, setSheet] = useState(null); // "reset" | "more"
  const [checklist, setChecklist] = useState(false);
  const [presenter, setPresenterState] = useState(() => store.get("presenter", false));
  const wide = useMedia("(min-width: 1280px)");

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const notify = useCallback((text, tone = "neutral") => setToast({ text, tone, at: Date.now() }), []);
  const phone = usePhone({ onActivity: refresh, notify });

  const setPresenter = (v) => {
    setPresenterState(v);
    store.set("presenter", v);
  };

  // status + template: retried until the server answers
  useEffect(() => {
    let alive = true;
    const boot = async () => {
      try {
        const [s, t] = await Promise.all([api.status(), api.template()]);
        if (!alive) return;
        setStatus(s);
        setTemplate(t);
      } catch {
        if (alive) setTimeout(boot, 2500);
      }
    };
    boot();
    return () => {
      alive = false;
    };
  }, []);

  // the live inbox: new WhatsApp reports appear without reloading
  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .list()
        .then((s) => {
          if (!alive) return;
          setSubs(s);
          setLoaded(true);
          setFailures(0);
        })
        .catch(() => alive && setFailures((n) => n + 1));
    load();
    const t = setInterval(() => !document.hidden && load(), 3000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [tick]);

  const counts = useMemo(() => {
    const c = { all: subs.length };
    for (const s of subs) c[s.status] = (c[s.status] || 0) + 1;
    return c;
  }, [subs]);

  const closeChecklist = useCallback(() => setChecklist(false), []);
  const steps = demoSteps(subs, phone);
  const stepsDone = steps.filter((s) => s.done).length;

  // first visit with an empty inbox: open the demo guide once
  const opened = useRef(false);
  useEffect(() => {
    if (opened.current || !loaded) return;
    opened.current = true;
    if (subs.length === 0 && !store.get("demoGuideSeen", false)) {
      setChecklist(true);
      store.set("demoGuideSeen", true);
    }
  }, [loaded, subs.length]);

  const docked = presenter && wide && view !== "phone";
  useEffect(() => {
    if (view === "phone" || docked) phone.markSeen();
  }, [view, docked, phone.unread]); // eslint-disable-line react-hooks/exhaustive-deps

  const reset = async () => {
    try {
      await api.reset();
      phone.reset();
      setSheet(null);
      refresh();
      go("inbox/needs_review");
      notify("Demo restarted", "green");
    } catch (e) {
      notify(e.message, "red");
    }
  };

  const offline = status?.mode !== "claude";
  const isInbox = view === "inbox" || view === "report" || !view;
  const navCurrent = (id) => isInbox && (a || "needs_review") === id;
  const title = (t) => (t ? `${t} · SHG Reports · Palmera` : "SHG Reports · Palmera");
  useEffect(() => {
    document.title = title(
      view === "groups" ? "Groups" : view === "phone" ? "Member’s phone" : view === "guide" ? "Guide" : NAV.find((n) => navCurrent(n.id))?.label,
    );
  });

  const modePill = (where) => (
    <span className="mode" tabIndex={0} aria-describedby={`mode-tip-${where}`}>
      <span className={`mode-dot ${offline ? "" : "is-live"}`} aria-hidden />
      {status ? (offline ? "Offline demo" : "Reading with Claude") : "Connecting…"}
      <span className="mode-tip" role="tooltip" id={`mode-tip-${where}`}>
        {offline ? MODE_TIP : "Photos are read by Claude, twice, then checked against the ledger."}
      </span>
    </span>
  );

  return (
    <div className={`app ${docked ? "has-dock" : ""}`}>
      <aside className="sidebar" aria-label="Navigation">
        <div className="brand">
          <div className="brand-mark" aria-hidden><Icon name="checkmark" size={16} stroke={2.4} /></div>
          <div className="brand-text">
            <div className="brand-name">SHG Reports</div>
            <div className="brand-org">Palmera, Sri Lanka</div>
          </div>
        </div>

        <nav className="nav" aria-label="Main">
          <div className="nav-heading">Reports</div>
          {NAV.map((f) => (
            <a key={f.id} href={`#/inbox/${f.id}`} className={`nav-item ${navCurrent(f.id) ? "is-active" : ""}`}
              aria-current={navCurrent(f.id) ? "page" : undefined} title={f.label}>
              <Icon name={f.icon} />
              <span className="nav-label">{f.label}</span>
              {counts[f.id] ? (
                <span className={`nav-count ${f.id === "needs_review" ? "is-attention" : ""}`}>
                  {counts[f.id]}<span className="sr-only"> reports</span>
                </span>
              ) : null}
            </a>
          ))}
          <div className="nav-heading">Monitoring</div>
          <a href="#/groups" className={`nav-item ${view === "groups" ? "is-active" : ""}`} aria-current={view === "groups" ? "page" : undefined} title="Groups">
            <Icon name="chart" />
            <span className="nav-label">Groups</span>
          </a>
          <div className="nav-heading">Demo</div>
          <a href="#/phone" className={`nav-item ${view === "phone" ? "is-active" : ""}`} aria-current={view === "phone" ? "page" : undefined} title="Member’s phone">
            <Icon name="phone" />
            <span className="nav-label">Member’s phone</span>
            {phone.unread > 0 && view !== "phone" && !docked && <span className="nav-count is-new">{phone.unread}<span className="sr-only"> new messages</span></span>}
          </a>
          <a href="#/guide" className={`nav-item ${view === "guide" ? "is-active" : ""}`} aria-current={view === "guide" ? "page" : undefined} title="Guide">
            <Icon name="book" />
            <span className="nav-label">Guide</span>
          </a>
        </nav>

        <div className="sidebar-foot">
          <button className={`guide-pill ${checklist ? "is-on" : ""}`} onClick={() => setChecklist((o) => !o)} aria-expanded={checklist} title="Demo guide">
            <Icon name="list" size={16} />
            <span className="nav-label">Demo guide</span>
            <span className="guide-count">{stepsDone}/{steps.length}</span>
          </button>
          <label className="switch foot-switch" title="Show the member’s phone beside the officer screens">
            <input type="checkbox" checked={presenter} onChange={(e) => setPresenter(e.target.checked)} />
            <span className="switch-track" aria-hidden />
            <span className="nav-label">Show phone beside</span>
          </label>
          <a className="foot-link" href={WORKBOOK_URL} download title="Download workbook">
            <Icon name="download" size={16} />
            <span className="nav-label">Download workbook</span>
          </a>
          {offline && status && (
            <button className="foot-link" onClick={() => setSheet("reset")} title="Restart demo">
              <Icon name="reset" size={16} />
              <span className="nav-label">Restart demo</span>
            </button>
          )}
          {modePill("side")}
        </div>
      </aside>

      <header className="topbar">
        <div className="brand-mark" aria-hidden><Icon name="checkmark" size={14} stroke={2.4} /></div>
        <span className="topbar-name">SHG Reports · Palmera</span>
        {modePill("top")}
      </header>

      <main className="main" id="main">
        {failures >= 2 && (
          <div className="conn-banner" role="alert">
            <Icon name="wifi" size={16} />
            <span>Can’t reach the server. Retrying…</span>
            <button className="btn btn-small btn-quiet" onClick={refresh}>Retry now</button>
          </div>
        )}
        <div className="main-body">
          {view === "groups" && <Groups selected={a ? decodeURIComponent(a) : null} subs={subs} />}
          {view === "phone" && <PhonePage phone={phone} />}
          {view === "guide" && <Guide tab={a} offline={offline} />}
          {isInbox && (
            <Inbox
              filter={view === "report" ? "all" : a || "needs_review"}
              selectedId={view === "report" ? a : b}
              subs={subs}
              loaded={loaded}
              template={template}
              notify={notify}
              refresh={refresh}
            />
          )}
        </div>
      </main>

      {docked && (
        <aside className="dock" aria-label="Member’s phone, live">
          <div className="dock-head">
            <span className="dock-title">Member’s phone</span>
            <label className="switch switch-small">
              <input type="checkbox" checked={phone.showEnglish} onChange={(e) => phone.setShowEnglish(e.target.checked)} />
              <span className="switch-track" aria-hidden />
              English
            </label>
            <button className="icon-btn" onClick={() => setPresenter(false)} aria-label="Hide the phone" title="Hide the phone"><Icon name="close" size={13} stroke={2.2} /></button>
          </div>
          <PhoneDevice phone={phone} docked />
        </aside>
      )}

      <nav className="tabbar" aria-label="Main">
        {NAV.slice(0, 3).map((f) => (
          <a key={f.id} href={`#/inbox/${f.id}`} className={navCurrent(f.id) ? "is-active" : ""} aria-current={navCurrent(f.id) ? "page" : undefined}>
            <span className="tab-icon"><Icon name={f.icon} size={22} />{f.id === "needs_review" && counts.needs_review ? <span className="tab-badge">{counts.needs_review}</span> : null}</span>
            {f.short}
          </a>
        ))}
        <a href="#/groups" className={view === "groups" ? "is-active" : ""} aria-current={view === "groups" ? "page" : undefined}>
          <span className="tab-icon"><Icon name="chart" size={22} /></span>Groups
        </a>
        <a href="#/phone" className={view === "phone" ? "is-active" : ""} aria-current={view === "phone" ? "page" : undefined}>
          <span className="tab-icon"><Icon name="phone" size={22} />{phone.unread > 0 && view !== "phone" ? <span className="tab-badge is-new">{phone.unread}</span> : null}</span>Phone
        </a>
        <button onClick={() => setSheet("more")} aria-haspopup="dialog" className={view === "guide" || (isInbox && a === "all") ? "is-active" : ""}>
          <span className="tab-icon"><Icon name="more" size={22} /></span>More
        </button>
      </nav>

      <Sheet open={sheet === "reset"} onClose={() => setSheet(null)} title="Restart the demo?" labelledBy="reset-title"
        actions={<><button className="btn btn-quiet" onClick={() => setSheet(null)}>Cancel</button><button className="btn btn-danger" onClick={reset}>Restart demo</button></>}>
        <p className="sheet-text">This clears every report and the phone conversation, and puts the demo workbook back as it was, with September recorded.</p>
      </Sheet>

      <Sheet open={sheet === "more"} onClose={() => setSheet(null)} title="SHG Reports · Palmera" labelledBy="more-title">
        <ul className="more-list">
          <li><a href="#/inbox/all" onClick={() => setSheet(null)}><Icon name="stack" />All reports</a></li>
          <li><a href="#/guide" onClick={() => setSheet(null)}><Icon name="book" />Guide</a></li>
          <li><button onClick={() => { setSheet(null); setChecklist(true); }}><Icon name="list" />Demo guide<span className="more-meta">{stepsDone}/{steps.length}</span></button></li>
          <li><a href={WORKBOOK_URL} download onClick={() => setSheet(null)}><Icon name="download" />Download workbook</a></li>
          {offline && status && <li><button onClick={() => setSheet("reset")}><Icon name="reset" />Restart demo</button></li>}
        </ul>
        <p className="sheet-text small">{offline ? `Offline demo. ${MODE_TIP}` : "Reading with Claude."}</p>
        <div className="sheet-actions"><button className="btn btn-quiet" onClick={() => setSheet(null)}>Done</button></div>
      </Sheet>

      {checklist && <DemoChecklist steps={steps} onClose={closeChecklist} />}
      <Toast toast={toast} />
    </div>
  );
}
