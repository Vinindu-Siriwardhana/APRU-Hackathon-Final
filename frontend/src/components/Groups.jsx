import { useEffect, useState } from "react";
import { api } from "../api.js";
import { monthName, money, moneyShort, officerError, pct } from "../format.js";
import Icon from "./Icon.jsx";
import LineChart from "./LineChart.jsx";

/** Plain words for each early warning: what it means and what an officer might do. */
function explain(text) {
  if (/^Attendance \d+% of members/.test(text)) return "Fewer than six in ten members came to meetings. Members who stop coming often stop saving and repaying next. Call the group leader.";
  if (/^Attendance down/.test(text)) return "Fewer members are coming to meetings than a few months ago. It’s often the first sign of trouble. Worth a call to the group leader.";
  if (/Loan repayments fell/.test(text)) return "Members are paying back less each month. Page 2 of the latest report lists who is overdue; plan a visit.";
  if (/Savings fell/.test(text)) return "The group is saving less each month. It can be a sign of money stress in the village. Ask the group leader at the next meeting, and watch next month’s figure.";
  if (/Mother-book cash differs/.test(text)) return "The cash the group counted doesn’t match what its own ledger says it should have. Usually a missed entry; check the mother book on the next visit.";
  if (/^No report since/.test(text)) return "This group hasn’t sent a report recently. Send a reminder on WhatsApp.";
  if (/No months recorded/.test(text)) return "Nothing is in the workbook for this group yet.";
  return null;
}

/**
 * A compact financial-health read-out from the monthly series the workbook already holds.
 * Each tile's colour follows the early warnings below it (the same rules), so a tile is never
 * green above a warning about the same measure. "Saved to date" is a running total: neutral.
 */
function health(series, flags = []) {
  const first = series[0], last = series[series.length - 1];
  const flagFor = (re) => flags.find((f) => re.test(f.text));
  const toneFor = (re, fallback) => {
    const f = flagFor(re);
    return f ? (f.level === "critical" ? "red" : "orange") : fallback;
  };
  const out = [];
  if (last?.savings_to_date != null) {
    const d = first && series.length > 1 && first.savings_to_date != null ? last.savings_to_date - first.savings_to_date : null;
    out.push({ k: "Saved to date", v: money(last.savings_to_date), wide: true,
      note: d === null ? `by ${monthName(last.month, true)}` : `${d >= 0 ? "+" : "−"}${money(Math.abs(d))} since ${monthName(first.month, true)}`, tone: "neutral" });
  }
  const vsBefore = (key) => {
    const earlier = series.slice(0, -1).map((m) => m[key]).filter((v) => v != null);
    if (!earlier.length || last?.[key] == null) return null;
    const avg = earlier.reduce((a, b) => a + b, 0) / earlier.length;
    return avg ? (last[key] - avg) / avg : 0;
  };
  const trend = (c) => (c === null ? "first month" : Math.abs(c) < 0.05 ? "steady on the months before" : `${c > 0 ? "up" : "down"} ${Math.round(Math.abs(c) * 100)}% on the months before`);
  if (last?.savings != null) {
    const c = vsBefore("savings");
    out.push({ k: `Savings, ${monthName(last.month, true)}`, v: money(last.savings), note: trend(c), tone: toneFor(/^Savings/, c !== null && c <= -0.1 ? "orange" : "green") });
  }
  if (last?.principal != null) {
    const c = vsBefore("principal");
    out.push({ k: "Loan repayments", v: money(last.principal), note: trend(c), tone: toneFor(/repayments/i, c !== null && c <= -0.1 ? "orange" : "green") });
  }
  const rates = series.map((m) => m.attendance_rate).filter((r) => r != null);
  if (rates.length) {
    const avg = rates.reduce((a, b) => a + b, 0) / rates.length;
    const now = rates[rates.length - 1];
    out.push({ k: "Attendance", v: pct(now), note: `${pct(avg)} on average`, tone: toneFor(/^Attendance/, now < 0.6 ? "red" : "green") });
  }
  if (last?.cash != null && last?.ledger_cash != null) {
    const gap = last.cash - last.ledger_cash;
    out.push({ k: "Cash vs ledger", v: Math.abs(gap) <= 1 ? "Matches" : `${gap > 0 ? "+" : "−"}${money(Math.abs(gap))}`, note: `${money(last.cash)} counted, ${monthName(last.month, true)}`,
      tone: toneFor(/cash/i, Math.abs(gap) <= 1 ? "green" : "red") });
  }
  return out;
}

export default function Groups({ selected, subs }) {
  const [groups, setGroups] = useState(null);
  const [err, setErr] = useState(null);
  const [tries, setTries] = useState(0);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .groups()
        .then((g) => {
          if (!alive) return;
          setGroups(g);
          setErr(null);
        })
        .catch((e) => alive && setErr(officerError(e.message)));
    load();
    const t = setInterval(() => !document.hidden && load(), 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [subs.length, tries]);

  if (!groups) {
    if (err) {
      return (
        <div className="empty empty-detail" role="alert">
          <Icon name="warn" size={36} stroke={1.3} />
          <h2>Couldn’t read the workbook</h2>
          <p>{err}</p>
          <button className="btn btn-quiet" onClick={() => setTries((n) => n + 1)}>Try again</button>
        </div>
      );
    }
    return (
      <div className="split">
        <section className="list-pane" aria-busy="true"><header className="pane-head"><h1 className="pane-title">Groups</h1></header>
          <ul className="rows">{[0, 1, 2].map((i) => <li key={i} className="row-skeleton"><span className="sk sk-dot" /><span className="sk sk-row" /></li>)}</ul>
        </section>
        <section className="detail-pane" />
      </div>
    );
  }

  const sorted = [...groups].sort((a, b) => rank(b) - rank(a) || a.name.localeCompare(b.name));
  const current = groups.find((g) => g.name === selected);

  return (
    <div className={`split is-groups ${current ? "has-detail" : ""}`}>
      <section className="list-pane" aria-labelledby="groups-h">
        <header className="pane-head">
          <h1 className="pane-title" id="groups-h">Groups</h1>
          <p className="pane-sub">How each group is doing, month by month, from Palmera’s workbook. Groups that need attention come first.</p>
        </header>
        <ul className="rows">
          {sorted.map((g) => {
            const worst = g.flags.find((f) => f.level === "critical") || g.flags[0];
            const tone = worst ? (worst.level === "critical" ? "red" : "orange") : "green";
            const sel = g.name === selected;
            return (
              <li key={g.name}>
                <a href={`#/groups/${encodeURIComponent(g.name)}`} className={`row ${sel ? "is-selected" : ""}`} aria-current={sel ? "page" : undefined}>
                  <span className={`dot tone-${tone}`} aria-hidden />
                  <span className="row-main">
                    <span className="row-title">{g.name}</span>
                    <span className="row-sub">{g.gn}</span>
                    <span className="row-meta">
                      <span className={`tag tone-${tone}`}>
                        {worst ? (g.flags.length > 1 ? `${g.flags.length} warnings` : worst.text) : "On track"}
                      </span>
                    </span>
                  </span>
                  <Spark values={g.series.map((m) => m.savings)} />
                </a>
              </li>
            );
          })}
        </ul>
      </section>
      <section className="detail-pane">
        {current ? <GroupDetail g={current} /> : (
          <div className="empty empty-detail">
            <Icon name="chart" size={40} stroke={1.2} />
            <h2>Select a group</h2>
            <p>Savings, repayments and attendance each month, with early warnings explained.</p>
          </div>
        )}
      </section>
    </div>
  );
}

const rank = (g) => g.flags.reduce((n, f) => n + (f.level === "critical" ? 10 : 3), 0);

function Spark({ values }) {
  if (values.length < 2) return null;
  const w = 64, h = 24, max = Math.max(...values) || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * (w - 4) + 2, h - 3 - (v / max) * (h - 6)]);
  return (
    <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden>
      <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="2.4" fill="currentColor" />
    </svg>
  );
}

function GroupDetail({ g }) {
  const s = g.series;
  if (!s.length) {
    return (
      <article className="detail">
        <header className="detail-head"><a className="back" href="#/groups" aria-label="Back to groups"><Icon name="back" size={22} /></a>
          <div className="detail-titles"><h1 className="detail-title">{g.name}</h1><p className="detail-sub">{g.gn}</p></div></header>
        <p className="statusline tone-grey">Nothing is recorded for this group yet.</p>
      </article>
    );
  }
  const last = s[s.length - 1];
  const months = s.map((m) => monthName(m.month, true));
  const hl = health(s, g.flags);
  return (
    <article className="detail">
      <header className="detail-head">
        <a className="back" href="#/groups" aria-label="Back to groups"><Icon name="back" size={22} /></a>
        <div className="detail-titles">
          <h1 className="detail-title">{g.name}</h1>
          <p className="detail-sub">{g.gn}, {last.members} members, {s.length} months recorded</p>
        </div>
      </header>

      {g.open_submissions.length > 0 && (
        <p className="statusline tone-blue">
          <span>A report for this group is open.</span> <a href={`#/inbox/all/${g.open_submissions[0].id}`}>Open it</a>
        </p>
      )}

      <section className="group" aria-labelledby="health-h">
        <h2 className="group-title" id="health-h">Financial health</h2>
        <dl className="health">
          {hl.map((h) => (
            <div key={h.k} className={`health-item tone-${h.tone} ${h.wide ? "is-wide" : ""}`}>
              <dt>{h.k}</dt>
              <dd><span className="health-v">{h.v}</span><span className="health-note">{h.note}</span></dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="group" aria-labelledby="flags-h">
        <h2 className="group-title" id="flags-h">Early warnings</h2>
        {g.flags.length > 0 ? (
          <ul className="flags">
            {g.flags.map((f, i) => (
              <li key={i} className={`flag tone-${f.level === "critical" ? "red" : "orange"}`}>
                <Icon name="flag" size={16} />
                <div>
                  <p className="flag-title">{f.text}</p>
                  {explain(f.text) && <p className="flag-why">{explain(f.text)}</p>}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="statusline tone-green">None. Attendance, savings and repayments are steady, and the cash matches the ledger.</p>
        )}
      </section>

      <div className="charts">
        <LineChart title="Savings each month" labels={months} values={s.map((m) => m.savings)} format={money} axisFormat={moneyShort} min={0} />
        <LineChart title="Loan repayments each month" labels={months} values={s.map((m) => m.principal)} format={money} axisFormat={moneyShort} min={0} />
        <LineChart title="Attendance, share of members" labels={months} values={s.map((m) => m.attendance_rate ?? 0)} format={pct} min={0} max={1} />
      </div>

      <section className="group" aria-labelledby="bymonth-h">
        <h2 className="group-title" id="bymonth-h">By month</h2>
        <div className="table-wrap">
          <table className="monthly">
            <thead>
              <tr><th scope="col">Month</th><th scope="col">Meetings</th><th scope="col">Attendance</th><th scope="col">Savings</th><th scope="col">Repaid</th><th scope="col">Lent</th><th scope="col">Cash</th></tr>
            </thead>
            <tbody>
              {s.map((m) => (
                <tr key={m.month}>
                  <th scope="row">{monthName(m.month)}</th>
                  <td>{m.meetings}</td>
                  <td>{pct(m.attendance_rate)}</td>
                  <td>{m.savings?.toLocaleString("en-US")}</td>
                  <td>{m.principal?.toLocaleString("en-US")}</td>
                  <td>{m.loans?.toLocaleString("en-US")}</td>
                  <td className={m.cash != null && Math.abs(m.cash - m.ledger_cash) > 1 ? "is-flagged" : ""}>{m.cash?.toLocaleString("en-US") ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </article>
  );
}
