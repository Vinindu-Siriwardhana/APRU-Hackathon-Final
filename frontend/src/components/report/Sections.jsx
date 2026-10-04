import { pageUrl, sampleUrl } from "../../api.js";
import { clock, curly, display, isMoneyLabel, money, page2Short, shortMonthly } from "../../format.js";
import Icon from "../Icon.jsx";

/** The field a monthly workbook row comes from: the flagged week while reviewing, else its total. */
function monthlyTarget(m, fields, flagged, review) {
  if (m.from === "header") return `header.${m.field}`;
  return (
    (review && Object.keys(flagged).find((f) => f.startsWith(`weekly.${m.field}.`))) ||
    (fields[`weekly.${m.field}.Total`] ? `weekly.${m.field}.Total` : ["W5", "W4", "W3", "W2", "W1"].map((w) => `weekly.${m.field}.${w}`).find((f) => fields[f]?.value != null))
  );
}

/**
 * The 16 monthly figures exactly as they'll go into Palmera's workbook. While she is
 * confirming, the numbered items of her WhatsApp summary come first, with the same numbers,
 * so "5 12000" on the phone reads straight across.
 */
export function MonthlyList({ template, sub, flagged, selected, onSelect }) {
  const fields = sub.record?.fields || {};
  const review = sub.status === "needs_review";
  const awaiting = sub.status === "awaiting_member";
  const items = awaiting ? sub.summary_items || [] : [];
  const numberOf = Object.fromEntries(items.filter((i) => i.monthly_label).map((i) => [i.monthly_label, i.n]));
  const byLabel = Object.fromEntries(template.monthly.map((m) => [m.label, m]));
  const her = sub.lang && sub.lang !== "en" ? sub.lang : null;
  const unshown = template.monthly.length - Object.keys(numberOf).length;
  return (
    <>
      {items.length > 0 && (
        <section className="group" aria-labelledby="confirming-h">
          <h2 className="group-title" id="confirming-h">What she’s confirming</h2>
          <p className="group-note">The {items.length} numbered items of her WhatsApp summary. She replies OK, or an item number and the right figure.</p>
          <ol className="inset summary-items">
            {items.map((it) => {
              const m = it.monthly_label ? byLabel[it.monthly_label] : null;
              const target = m ? monthlyTarget(m, fields, flagged, false) : fields[it.key] ? it.key : null;
              return (
                <li key={it.n}>
                  <button className={`inset-row ${target && target === selected ? "is-selected" : ""}`} data-fid={target || undefined}
                    onClick={() => target && onSelect(target, { scroll: true })} disabled={!target}>
                    <span className="item-n" aria-hidden>{it.n}</span>
                    <span className="inset-label">
                      <span className="sr-only">Item {it.n}: </span>{curly(it.label_en)}
                      {her && it.label && it.label !== it.label_en && <span className="item-her" lang={her}>{it.label}</span>}
                    </span>
                    <span className="inset-value">{it.display_en ?? display(it.value)}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        </section>
      )}
      <section className="group" aria-labelledby="monthly-h">
        <h2 className="group-title" id="monthly-h">{awaiting ? "Goes to the workbook when she says OK" : "This month in the workbook"}</h2>
        {awaiting && items.length > 0 && (
          <p className="group-note">Numbered rows are in her summary. The other {unshown} passed the ledger checks.</p>
        )}
        <ul className="inset">
          {template.monthly.map((m) => {
            const rowFlag = review && Object.keys(flagged).some((f) => f.startsWith(`weekly.${m.field}.`) || f === `header.${m.field}`);
            const target = monthlyTarget(m, fields, flagged, review);
            const v = sub.monthly?.[m.label];
            const n = numberOf[m.label];
            return (
              <li key={m.label}>
                <button className={`inset-row ${target && target === selected ? "is-selected" : ""}`} data-fid={items.length ? undefined : target || undefined}
                  onClick={() => target && onSelect(target, { scroll: true })} disabled={!target}>
                  {awaiting && items.length > 0 && (n ? <span className="item-n" title={`Item ${n} in her summary`}><span className="sr-only">Item </span>{n}</span> : <span className="item-n is-none" aria-hidden />)}
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
    </>
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
        <button className={`inset-row stacked ${selected === fid ? "is-selected" : ""}`} data-fid={fid} onClick={() => onSelect(fid, { scroll: true })}>
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
                  <button className={`inset-row ${selected === fid ? "is-selected" : ""}`} data-fid={fid} onClick={() => onSelect(fid, { scroll: true })}>
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
                <button className="inset-row stacked" data-fid={`page2.issues.${i}.issue`} onClick={() => onSelect(`page2.issues.${i}.issue`, { scroll: true })}>
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
export function Conversation({ sid, log, lang, onResend, busy }) {
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
          const failed = !mine && m.delivered === false;
          // bot lines are in her language; her own texts are usually too ("OK" reads the same either way)
          const textLang = lang && lang !== "en" && (!mine || /[^\x00-\x7F]/.test(m.text || "")) ? lang : "en";
          return (
            <div key={i} className={`bubble ${mine ? "from-member" : "from-bot"} ${m.img ? "has-image" : ""} ${failed ? "is-undelivered" : ""}`}>
              {m.img ? (
                <img src={m.img} alt="Form photo she sent" loading="lazy" />
              ) : m.image ? (
                <span className="bubble-photo"><Icon name="photo" size={15} /> Photo, asked for a retake</span>
              ) : (
                <span lang={textLang}>{m.text}</span>
              )}
              {m.text_en && lang !== "en" && m.text_en !== m.text && <span className="bubble-en" lang="en">{m.text_en}</span>}
              <span className="bubble-time">
                {failed && <span className="bubble-failed"><Icon name="warn" size={12} stroke={2} /> Not delivered</span>}
                {clock(m.at)}
              </span>
              {failed && (
                <span className="bubble-resend">
                  {m.delivery_error && <span className="bubble-why">{curly(m.delivery_error)}</span>}
                  {onResend && <button className="btn btn-small btn-tinted" disabled={busy} onClick={onResend}>Resend</button>}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
