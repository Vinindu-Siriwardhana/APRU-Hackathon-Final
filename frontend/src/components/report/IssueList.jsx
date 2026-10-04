import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { curly, fieldName, money, shortMonthly } from "../../format.js";
import Icon from "../Icon.jsx";
import { CHECKED, issueKey } from "./ranking.js";

/**
 * Keeps issues that just disappeared on screen for a moment, struck through, so the officer
 * sees which checks a save cleared. State is derived during render (no flash of the
 * shorter list before the leaving rows come back).
 */
function useLeaving(items, ms = 900) {
  const keys = items.map(issueKey).join("¦");
  const [st, setSt] = useState({ keys, prev: items, gone: [] });
  if (keys !== st.keys) {
    const now = new Set(items.map(issueKey));
    const gone = st.prev.map((item, index) => ({ item, index })).filter((x) => !now.has(issueKey(x.item)));
    setSt({ keys, prev: items, gone });
  }
  useEffect(() => {
    if (!st.gone.length) return;
    const t = setTimeout(() => setSt((s) => ({ ...s, gone: [] })), ms);
    return () => clearTimeout(t);
  }, [st.gone, ms]);
  const out = items.map((item) => ({ item, leaving: false }));
  for (const g of st.gone) out.splice(Math.min(g.index, out.length), 0, { item: g.item, leaving: true });
  return out;
}

export default function IssueList({ sid, sub, errors, notes, order, selected, onSelect, act, showW5, onNewGroup }) {
  const rows = useLeaving(errors);
  const fields = sub.record?.fields || {};
  const review = sub.status === "needs_review";
  if (!rows.length && !notes.length) return null;
  const common = { fields, labels: sub.labels, selected, onSelect, order, showW5 };
  return (
    <section className="group" aria-labelledby="checks-h">
      {rows.length > 0 && (
        <>
          <h2 className="group-title" id="checks-h">{review ? "Needs your check" : "Open checks"}</h2>
          <ul className="inset issues">
            {rows.map(({ item: i, leaving }) => {
              const k = issueKey(i) + (leaving ? "-x" : "");
              if (i.rule === "member_correction") return <MemberCorrection key={k} issue={i} sub={sub} sid={sid} act={act} leaving={leaving} {...common} />;
              if (i.rule === "unknown_shg") return <UnknownGroup key={k} issue={i} sid={sid} act={act} leaving={leaving} editable={review} onNewGroup={onNewGroup} {...common} />;
              return <IssueRow key={k} issue={i} leaving={leaving} editable={review} onNewGroup={onNewGroup} {...common} />;
            })}
          </ul>
        </>
      )}
      {notes.length > 0 && (
        <>
          <h2 className="group-title" id={rows.length ? undefined : "checks-h"}>Worth knowing</h2>
          <ul className="inset issues">
            {notes.map((i) => <IssueRow key={issueKey(i)} issue={i} quiet {...common} />)}
          </ul>
        </>
      )}
    </section>
  );
}

/** Zoom chips for the cells a check depends on, likeliest culprit first. */
function Chips({ issue, fields, labels, selected, onSelect, order, quiet, showW5, max = 6 }) {
  const rank = (f) => (order.includes(f) ? order.indexOf(f) : 999);
  const targets = (issue.fields || [])
    .filter((f) => fields[f] && (showW5 || !f.endsWith(".W5")))
    .sort((a, b) => rank(a) - rank(b));
  if (!targets.length) return null;
  const top = !quiet && rank(targets[0]) === 0 ? targets[0] : null;
  return (
    <div className="chips">
      {targets.slice(0, max).map((f) => {
        const done = CHECKED.includes(fields[f]?.status);
        return (
          <button key={f} data-fid={f} className={`chip ${f === selected ? "is-selected" : ""} ${done ? "is-done" : ""} ${f === top ? "is-likely" : ""}`}
            onClick={() => onSelect(f, { scroll: true })} aria-pressed={f === selected}
            title={done ? "Already checked against the photo" : f === top ? "Appears in the most failing checks" : "Show on the photo"}>
            {done && <Icon name="checkmark" size={12} stroke={2.4} />}
            {fieldName(f, labels)}
            {f === top && <span className="chip-hint">Most likely</span>}
          </button>
        );
      })}
      {targets.length > max && <span className="chip-more">and {targets.length - max} more</span>}
    </div>
  );
}

/** Continuity checks the officer settles against the photo: open the cell, then Keep confirms it as written. */
const CONFIRMABLE = { month_unexpected: "header.month_year", members_jump: "header.total_members" };

function IssueRow({ issue, quiet, leaving, selected, editable, onNewGroup, ...rest }) {
  const active = (issue.fields || []).includes(selected);
  const confirmField = !quiet && editable && CONFIRMABLE[issue.rule] && rest.fields[CONFIRMABLE[issue.rule]] ? CONFIRMABLE[issue.rule] : null;
  const opening = !quiet && editable && issue.rule === "opening_inconsistent" && onNewGroup;
  return (
    <li className={`issue ${quiet ? "is-quiet" : ""} ${active && !leaving ? "is-selected" : ""} ${leaving ? "is-leaving" : ""}`} aria-hidden={leaving || undefined}>
      <div className="issue-inner">
        <Icon name={leaving ? "checkmark" : quiet ? "info" : "warn"} size={16} stroke={leaving ? 2.4 : 1.7}
          className={leaving ? "tone-text-green" : quiet ? "tone-text-grey" : "tone-text-orange"} />
        <div className="issue-body">
          <p className="issue-text">{curly(issue.message)}</p>
          {!leaving && !confirmField && <Chips issue={issue} quiet={quiet} selected={selected} {...rest} />}
          {!leaving && confirmField && (
            <>
              <p className="issue-help">Open it beside the photo. If the photo shows the same, choose <strong>Keep</strong> to confirm it as written; otherwise type the right one.</p>
              <div className="issue-actions">
                <button className={`btn btn-small ${active ? "btn-quiet" : "btn-primary"}`} data-fid={confirmField} onClick={() => rest.onSelect(confirmField, { scroll: true })} aria-pressed={active}>
                  Check the {confirmField === "header.month_year" ? "month" : "member count"} on the photo
                </button>
              </div>
            </>
          )}
          {!leaving && opening && (
            <div className="issue-actions">
              <button className="btn btn-small btn-primary" onClick={() => onNewGroup("book")}>Enter its totals from the mother book</button>
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

/**
 * The member replied "5 12000": her figure vs the form's. The officer either fixes the
 * weekly cells (the issue then resolves itself), keeps the form's figure, or — only for a
 * figure that comes from a single cell — uses hers.
 */
function MemberCorrection({ issue, sub, sid, act, leaving, selected, ...rest }) {
  const list = sub.corrections || [];
  const c = list.find((x) => (issue.label && x.label === issue.label) || Number(x.value) === Number(issue.expected)) || list[0] || {};
  const overrides = sub.overrides || {};
  const label = c.label || issue.label || Object.keys(overrides).find((k) => Number(overrides[k]) === Number(issue.expected)) || Object.keys(overrides)[0];
  const name = c.short || (label ? shortMonthly(label) : "a figure");
  const isMoney = label ? /\(Rs\.\)/.test(label) : true;
  const fmt = (v) => (v === null || v === undefined ? "blank" : isMoney ? money(v) : Number(v).toLocaleString("en-US"));
  const her = c.value ?? issue.expected;
  const form = c.form_value ?? issue.found;
  // "Use her figure" only when the figure is one cell on the form (the backend refuses otherwise)
  const single = c.can_accept ?? (issue.fields || []).length === 1;
  const editable = sub.status === "needs_review";
  return (
    <li className={`issue is-member ${leaving ? "is-leaving" : ""}`} aria-hidden={leaving || undefined}>
      <div className="issue-inner">
        <Icon name={leaving ? "checkmark" : "person"} size={16} className={leaving ? "tone-text-green" : "tone-text-blue"} />
        <div className="issue-body">
          <p className="issue-text">
            <strong>The member replied that {c.item ? `item ${c.item}, ` : ""}{String(name).toLowerCase()}, should be different.</strong>
          </p>
          <dl className="compare">
            <div><dt>Her figure</dt><dd>{fmt(her)}</dd></div>
            <div><dt>The form says</dt><dd>{fmt(form)}</dd></div>
          </dl>
          {!leaving && <Chips issue={{ ...issue, fields: issue.fields?.length ? issue.fields : c.cells || [] }} selected={selected} {...rest} />}
          {!leaving && editable && (
            <>
              <p className="issue-help">
                {single
                  ? "Look at the cell on the photo. If she’s right, use her figure; if the form is right, keep it."
                  : "This figure adds up from the weekly cells. Correct the cells against the photo and this clears by itself, or keep the form’s figure."}
              </p>
              <div className="issue-actions">
                {single && (
                  <button className="btn btn-small btn-primary" onClick={() => act(() => api.override(sid, label, true), "Used her figure")}>
                    Use her figure
                  </button>
                )}
                <button className="btn btn-small btn-quiet" onClick={() => act(() => api.override(sid, label, false), "Kept the form’s figure")}>
                  Keep the form’s figure
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </li>
  );
}

/** The group name on the form isn't a tab in Palmera's workbook. */
function UnknownGroup({ issue, sid, act, leaving, editable, fields, onNewGroup }) {
  const [tabs, setTabs] = useState(null);
  const [pick, setPick] = useState("");
  useEffect(() => {
    if (editable) api.shgTabs().then(setTabs).catch(() => setTabs([]));
  }, [editable]);
  const written = fields["header.shg_name"]?.value;
  return (
    <li className={`issue ${leaving ? "is-leaving" : ""}`} aria-hidden={leaving || undefined}>
      <div className="issue-inner">
        <Icon name={leaving ? "checkmark" : "warn"} size={16} className={leaving ? "tone-text-green" : "tone-text-orange"} />
        <div className="issue-body">
          <p className="issue-text">{curly(issue.message)}</p>
          {!leaving && editable && (
            <div className="group-pick">
              <label className="edit-label" htmlFor="shg-pick">Which group is “{written || "this"}”?</label>
              <div className="edit-row">
                <select id="shg-pick" className="field" value={pick} onChange={(e) => setPick(e.target.value)} disabled={!tabs}>
                  <option value="">{tabs ? "Pick a group in the workbook" : "Loading groups…"}</option>
                  {(tabs || []).map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                <button className="btn btn-primary" disabled={!pick} onClick={() => act(() => api.setField(sid, "header.shg_name", pick), `Set the group to ${pick}`)}>
                  Use this group
                </button>
              </div>
              <button className="btn btn-small btn-quiet" onClick={() => onNewGroup?.("start")}>
                It’s a new group…
              </button>
            </div>
          )}
        </div>
      </div>
    </li>
  );
}
