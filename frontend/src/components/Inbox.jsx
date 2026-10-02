import { monthName, relTime, statusOf } from "../format.js";
import Icon from "./Icon.jsx";
import ReportDetail from "./report/ReportDetail.jsx";

export const FILTERS = {
  needs_review: { title: "Needs review", sub: "Reports where a figure doesn’t add up. Check each one against the photo." },
  awaiting_member: { title: "Waiting for member", sub: "Sent back on WhatsApp. Each is recorded when the member replies OK." },
  written: { title: "Recorded", sub: "Confirmed by the member and written to Palmera’s workbook." },
  all: { title: "All reports", sub: "Every report received, newest first." },
};

const EMPTY = {
  needs_review: { title: "Nothing to check", text: "Reports with figures that need a second look appear here." },
  awaiting_member: { title: "No one to wait for", text: "Reports sent back to members for confirmation appear here." },
  written: { title: "Nothing recorded yet", text: "Reports appear here once the member confirms and they’re written to the workbook." },
  all: { title: "No reports yet", text: "Send a form from Member’s phone to see the whole flow." },
};

export default function Inbox({ filter, selectedId, subs, loaded, template, notify, refresh }) {
  const f = FILTERS[filter] || FILTERS.all;
  const rows = [...subs].filter((s) => filter === "all" || s.status === filter).sort((a, b) => String(b.created).localeCompare(String(a.created)));
  const empty = EMPTY[filter] || EMPTY.all;
  const noReportsAtAll = loaded && subs.length === 0;

  return (
    <div className={`split is-report ${selectedId ? "has-detail" : ""}`}>
      <section className="list-pane" aria-labelledby="list-h">
        <header className="pane-head">
          <h1 className="pane-title" id="list-h">{f.title}</h1>
          <p className="pane-sub">{f.sub}</p>
        </header>
        {!loaded ? (
          <ul className="rows" aria-busy="true" aria-label="Loading reports">
            {[0, 1].map((i) => <li key={i} className="row-skeleton"><span className="sk sk-dot" /><span className="sk sk-row" /></li>)}
          </ul>
        ) : rows.length === 0 ? (
          noReportsAtAll && filter === "needs_review" ? (
            <div className="empty start-here">
              <Icon name="phone" size={34} stroke={1.3} />
              <h2>Start here</h2>
              <p>No reports yet. Send a form photo from the member’s phone, as she would on WhatsApp.</p>
              <a className="btn btn-primary" href="#/phone">Open Member’s phone</a>
              <a className="link-small" href="#/guide/presenting">How the demo goes</a>
            </div>
          ) : (
            <div className="empty">
              <Icon name="tray" size={34} stroke={1.3} />
              <h2>{empty.title}</h2>
              <p>{empty.text}</p>
              {filter !== "written" && <a className="btn btn-quiet" href="#/phone">Open Member’s phone</a>}
            </div>
          )
        ) : (
          <ul className="rows">
            {rows.map((s) => {
              const st = statusOf(s);
              const sel = s.id === selectedId;
              return (
                <li key={s.id}>
                  <a href={`#/inbox/${filter}/${s.id}`} className={`row ${sel ? "is-selected" : ""}`} aria-current={sel ? "page" : undefined}>
                    <span className={`dot tone-${st.tone}`} aria-hidden />
                    <span className="row-main">
                      <span className="row-title">{s.shg || "New report"}</span>
                      <span className="row-sub">
                        {s.month ? monthName(s.month) : s.pages?.length ? `Page ${s.pages.join(" and ")} received` : "Waiting for photos"}
                        {s.gn ? `, ${s.gn}` : ""}
                      </span>
                      <span className="row-meta">
                        <span className={`tag tone-${st.tone}`}>
                          {s.status === "needs_review" && s.errors ? `${s.errors} to check` : st.label}
                        </span>
                        <span className="row-time">{relTime(s.created)}</span>
                      </span>
                    </span>
                    <Icon name="chevron" size={14} className="row-chevron" />
                  </a>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <section className="detail-pane" aria-label="Report">
        {selectedId ? (
          <ReportDetail key={selectedId} id={selectedId} filter={filter} template={template} notify={notify} refresh={refresh} />
        ) : (
          <div className="empty empty-detail">
            <Icon name="photo" size={40} stroke={1.2} />
            <h2>Select a report</h2>
            <p>You’ll see the photo, every figure read from it, and anything that needs your check.</p>
          </div>
        )}
      </section>
    </div>
  );
}
