import { pageUrl, sampleUrl } from "../../api.js";
import { clock, display, isMoneyLabel, money, page2Short, shortMonthly } from "../../format.js";
import Icon from "../Icon.jsx";

/** The 16 monthly figures exactly as they'll go into Palmera's workbook. */
export function MonthlyList({ template, sub, flagged, selected, onSelect }) {
  const fields = sub.record?.fields || {};
  const review = sub.status === "needs_review";
  return (
    <section className="group" aria-labelledby="monthly-h">
      <h2 className="group-title" id="monthly-h">{sub.status === "awaiting_member" ? "What she’s confirming" : "This month in the workbook"}</h2>
      <ul className="inset">
        {template.monthly.map((m) => {
          const rowFlag = review && Object.keys(flagged).some((f) => f.startsWith(`weekly.${m.field}.`) || f === `header.${m.field}`);
          const target =
            m.from === "header"
              ? `header.${m.field}`
              : (review && Object.keys(flagged).find((f) => f.startsWith(`weekly.${m.field}.`))) ||
                (fields[`weekly.${m.field}.Total`] ? `weekly.${m.field}.Total` : ["W5", "W4", "W3", "W2", "W1"].map((w) => `weekly.${m.field}.${w}`).find((f) => fields[f]?.value != null));
          const v = sub.monthly?.[m.label];
          return (
            <li key={m.label}>
              <button className={`inset-row ${target && target === selected ? "is-selected" : ""}`} onClick={() => target && onSelect(target, { scroll: true })} disabled={!target}>
                <span className={`inset-label ${m.label.startsWith("Loan Purpose") ? "is-sub" : ""}`}>{shortMonthly(m.label)}</span>
                <span className="inset-value">
                  {rowFlag && <Icon name="warn" size={14} className="tone-text-orange" title="In a check that fails" />}
                  {isMoneyLabel(m.label) ? money(v) : display(v)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const PAGE2_SIMPLE = (template, fields) => template.page2.filter((f) => f.type !== "table" && fields[`page2.${f.key}`]?.value != null);

export function PageTwo({ template, fields, flagged, selected, onSelect, review }) {
  const simple = PAGE2_SIMPLE(template, fields);
  const overdue = [0, 1, 2, 3, 4].filter((i) => fields[`page2.overdue_members.${i}.name`]?.value);
  const issues = [0, 1].filter((i) => fields[`page2.issues.${i}.issue`]?.value);
  if (!simple.length && !overdue.length && !issues.length) return null;
  const row = (fid, label) => {
    const fv = fields[fid];
    const tr = (fv.history || []).find((h) => h.event === "translation")?.english;
    return (
      <li key={fid}>
        <button className={`inset-row stacked ${selected === fid ? "is-selected" : ""}`} onClick={() => onSelect(fid, { scroll: true })}>
          <span className="inset-label">{label}</span>
          <span className="inset-text">
            {review && flagged[fid] && <Icon name="warn" size={14} className="tone-text-orange" title="In a check that fails" />}
            {display(fv.value)}
          </span>
          {tr && <span className="inset-translation">{tr}</span>}
        </button>
      </li>
    );
  };
  return (
    <section className="group" aria-labelledby="p2-h">
      <h2 className="group-title" id="p2-h">Page 2</h2>
      {overdue.length > 0 && (
        <>
          <h3 className="group-sub">Members with overdue loans</h3>
          <ul className="inset">
            {overdue.map((i) => {
              const g = (c) => fields[`page2.overdue_members.${i}.${c}`]?.value;
              const fid = `page2.overdue_members.${i}.name`;
              const mo = g("months_overdue");
              return (
                <li key={i}>
                  <button className={`inset-row ${selected === fid ? "is-selected" : ""}`} onClick={() => onSelect(fid, { scroll: true })}>
                    <span className="inset-label">{g("name")}</span>
                    <span className="inset-value">
                      {money(g("amount_left"))}
                      {mo != null && <span className="muted"> · {mo} {Number(mo) === 1 ? "month" : "months"} overdue</span>}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}
      {simple.length > 0 && <ul className="inset">{simple.map((f) => row(`page2.${f.key}`, page2Short(f.key, f.label)))}</ul>}
      {issues.length > 0 && (
        <>
          <h3 className="group-sub">Issues raised</h3>
          <ul className="inset">
            {issues.map((i) => (
              <li key={i}>
                <button className="inset-row stacked" onClick={() => onSelect(`page2.issues.${i}.issue`, { scroll: true })}>
                  <span className="inset-text">{fields[`page2.issues.${i}.issue`]?.value}</span>
                  {fields[`page2.issues.${i}.support_from_cluster`]?.value && (
                    <span className="inset-translation">Asked of the cluster: {fields[`page2.issues.${i}.support_from_cluster`].value}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

/**
 * The report's WhatsApp history. Member photos show as thumbnails: a photo that passed the
 * quality gate is matched to the page it became; a refused one shows as a plain pill.
 */
export function Conversation({ sid, log, lang }) {
  const items = [];
  (log || []).forEach((e, i) => {
    if (!e.from) return;
    let img = null;
    if (e.image && typeof e.image === "string") img = /\.(jpe?g|png)$/i.test(e.image) ? sampleUrl(e.image) : null;
    if (e.image && !img) {
      const next = (log || []).slice(i + 1).find((x) => x.event === "page_accepted" || x.event === "quality_rejected" || x.from);
      if (next?.event === "page_accepted") img = pageUrl(sid, next.page);
    }
    items.push({ ...e, img });
  });
  if (!items.length) return null;
  return (
    <section className="group" aria-labelledby="convo-h">
      <h2 className="group-title" id="convo-h">WhatsApp conversation</h2>
      <div className="convo">
        {items.map((m, i) => {
          const mine = m.from !== "bot";
          return (
            <div key={i} className={`bubble ${mine ? "from-member" : "from-bot"} ${m.img ? "has-image" : ""}`}>
              {m.img ? (
                <img src={m.img} alt="Form photo she sent" loading="lazy" />
              ) : m.image ? (
                <span className="bubble-photo"><Icon name="photo" size={15} /> Photo, asked for a retake</span>
              ) : (
                <span>{m.text}</span>
              )}
              {m.text_en && lang !== "en" && m.text_en !== m.text && <span className="bubble-en" lang="en">{m.text_en}</span>}
              <span className="bubble-time">{clock(m.at)}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
