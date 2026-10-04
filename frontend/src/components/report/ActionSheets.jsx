import { useEffect, useState } from "react";
import { api } from "../../api.js";
import Sheet from "../Sheet.jsx";

/** "Send anyway…": the officer's escape hatch when a check can't be resolved. A reason is required. */
export function ForceSheet({ open, onClose, onConfirm, errors, busy, recorded, returnFocus }) {
  const [reason, setReason] = useState("");
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Send anyway?"
      labelledBy="force-title"
      returnFocus={returnFocus}
      actions={
        <>
          <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!reason.trim() || busy} onClick={() => onConfirm(reason.trim())}>
            Send to member
          </button>
        </>
      }
    >
      <p className="sheet-text">
        {errors === 1 ? "One check still fails." : `${errors} checks still fail.`} The member will be asked to confirm the figures as they are,
        and your reason is kept with the report.
      </p>
      {recorded && (
        <p className="sheet-quote is-warn">This month is already in Palmera’s workbook for this group. Sending anyway replaces it once she confirms.</p>
      )}
      <label className="edit-label" htmlFor="force-reason">Why is it right to send it?</label>
      <textarea id="force-reason" className="field field-area" rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
        placeholder="For example: I phoned the group leader; the mother book shows the same figure." autoFocus />
    </Sheet>
  );
}

const FALLBACK_REASONS = [
  { code: "unclear", en: "The photos are not clear enough to read." },
  { code: "missing_page", en: "A page is missing." },
  { code: "wrong_group", en: "The group name or the month on the form is not right." },
  { code: "wrong_form", en: "This is not the SHG monthly report form." },
  { code: "incomplete", en: "Some parts of the form are empty." },
  { code: "other", en: "Other (no reason given to the member)" },
];
/** Short chip labels for the reasons; the member gets the full sentence in her language. */
const CHIP = { unclear: "Photo is unclear", missing_page: "Page missing", wrong_group: "Wrong group or month", wrong_form: "Not the report form", incomplete: "Parts left empty", other: "Other" };

/** "Ask for a new photo": rejects this report; the member gets a message in her language. */
export function RejectSheet({ open, onClose, onConfirm, busy, initialCode = "", returnFocus }) {
  const [reasons, setReasons] = useState(FALLBACK_REASONS);
  const [code, setCode] = useState(initialCode);
  const [note, setNote] = useState("");
  useEffect(() => {
    if (!open) return;
    setCode(initialCode);
    api.rejectReasons().then((r) => Array.isArray(r) && r.length && setReasons(r)).catch(() => {});
  }, [open]);
  const chosen = reasons.find((r) => r.code === code);
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Ask for a new photo"
      labelledBy="reject-title"
      returnFocus={returnFocus}
      actions={
        <>
          <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!code || busy} onClick={() => onConfirm(code, note.trim())}>
            Ask for a new photo
          </button>
        </>
      }
    >
      <p className="sheet-text">She gets a WhatsApp message in her language asking her to send the photos again. Nothing from this report is written.</p>
      <p className="edit-label" id="reject-why">Why?</p>
      <div className="preset-row" role="radiogroup" aria-labelledby="reject-why"
        onKeyDown={(e) => {
          const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
          if (!d) return;
          e.preventDefault();
          const i = reasons.findIndex((r) => r.code === code);
          const n = reasons[(i + d + reasons.length) % reasons.length];
          setCode(n.code);
          e.currentTarget.querySelector(`[data-code="${n.code}"]`)?.focus();
        }}>
        {reasons.map((r, i) => (
          <button key={r.code} type="button" role="radio" data-code={r.code} tabIndex={code ? (code === r.code ? 0 : -1) : i === 0 ? 0 : -1}
            className={`chip ${code === r.code ? "is-selected" : ""}`} aria-checked={code === r.code} onClick={() => setCode(r.code)}>
            {CHIP[r.code] || r.en}
          </button>
        ))}
      </div>
      {chosen && (
        <p className="sheet-quote">{chosen.code === "other" ? "She’s asked to send the photos again, with no reason given." : <>She’ll read, in her language: “{chosen.en}”</>}</p>
      )}
      <label className="edit-label" htmlFor="reject-note">Note for the record (optional, she won’t see it)</label>
      <input id="reject-note" className="field" value={note} onChange={(e) => setNote(e.target.value)} placeholder="For example: page 2 photographed twice" autoComplete="off" />
    </Sheet>
  );
}

/** Palmera's "… to date" workbook rows, in words an officer reads off the mother book. */
const OPENING_SHORT = {
  "Total savings to date (Rs.)": "Savings",
  "Total Principal loan repayments to date (Rs.)": "Loan repayments (principal)",
  "Total Interest repayments to date (Rs.)": "Interest repaid",
  "Total Other income to date (Rs.)": "Other income",
  "Total Loans distributed to date (Rs.)": "Loans given",
  "Total Savings refunded to date (Rs.)": "Savings refunded",
  "Total Other expenses to date (Rs.)": "Other expenses",
  "Total Loan right off to date (Rs.)": "Loans written off",
  "Total Loans outstanding to date (Rs.)": "Loans outstanding",
};
const openingShort = (label) => OPENING_SHORT[label] || String(label).replace(/^Total\s+/i, "").replace(/\s*to date.*$/i, "");
const asFigure = (v) => (v === null || v === undefined || v === "" ? "" : Number(v).toLocaleString("en-US"));
const FIGURE = /^\d[\d,\s]*(\.\d+)?$/;

/**
 * "It's a new group": the workbook needs the group's lifetime totals BEFORE this month.
 * Either it started this month (all zero), or the officer copies them from the mother book;
 * what the form itself implies (savings and loans outstanding) is filled in for her to check.
 */
export function NewGroupSheet({ open, onClose, onConfirm, busy, rows, suggestion, current, startedBefore, monthLabel, name, initialMode = "start", returnFocus }) {
  const [mode, setMode] = useState(initialMode);
  const [vals, setVals] = useState({});
  const [tried, setTried] = useState(false);
  useEffect(() => {
    if (!open) return;
    setMode(initialMode);
    setTried(false);
    const seed = {};
    for (const r of rows || []) seed[r] = asFigure(current?.[r] ?? suggestion?.[r]);
    setVals(seed);
  }, [open, initialMode]);
  const missing = (rows || []).filter((r) => !FIGURE.test(String(vals[r] ?? "").trim()));
  const ok = mode === "start" || missing.length === 0;
  const before = monthLabel ? `before ${monthLabel}` : "before this month";
  const submit = () => {
    setTried(true);
    if (!ok || busy) return;
    if (mode === "start") onConfirm({ startedThisMonth: true });
    else onConfirm({ opening: Object.fromEntries(rows.map((r) => [r, Number(String(vals[r]).replace(/[,\s]/g, ""))])) });
  };
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={`${name ? `“${name}”` : "This group"} is a new group`}
      labelledBy="newgroup-title"
      returnFocus={returnFocus}
      wide
      actions={
        <>
          <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || (tried && !ok)} onClick={submit}>
            {mode === "start" ? "Make its tab" : "Make its tab with these totals"}
          </button>
        </>
      }
    >
      <p className="sheet-text">A new tab is made in Palmera’s workbook. Its first column needs the group’s totals so far, so the ledger checks have something to start from.</p>
      <div className="option-list" role="radiogroup" aria-label="Where its totals come from">
        <label className={`option ${mode === "start" ? "is-on" : ""}`}>
          <input type="radio" name="opening-mode" checked={mode === "start"} onChange={() => setMode("start")} />
          <span>
            <span className="option-title">The group started this month</span>
            <span className="option-text">Nothing was saved or lent before {monthLabel || "this month"}, so every total starts at 0.</span>
          </span>
        </label>
        <label className={`option ${mode === "book" ? "is-on" : ""}`}>
          <input type="radio" name="opening-mode" checked={mode === "book"} onChange={() => setMode("book")} />
          <span>
            <span className="option-title">Enter its totals from the mother book</span>
            <span className="option-text">For a group that was already running. {startedBefore ? "" : "Figures the form already implies are filled in: check them."}</span>
          </span>
        </label>
      </div>
      {mode === "book" && (
        <fieldset className="opening-grid">
          <legend>Totals {before} (Rs)</legend>
          {(rows || []).map((r, i) => {
            const fromForm = suggestion?.[r] !== null && suggestion?.[r] !== undefined && asFigure(suggestion[r]) === vals[r];
            const bad = tried && missing.includes(r);
            return (
              <div className="opening-row" key={r}>
                <label htmlFor={`opening-${i}`}>
                  {openingShort(r)} <span className="sr-only">to date, {before}</span>
                  {fromForm && <span className="from-form">From the form</span>}
                </label>
                <input id={`opening-${i}`} className={`field ${bad ? "is-invalid" : ""}`} inputMode="decimal" autoComplete="off" placeholder="0"
                  value={vals[r] ?? ""} aria-invalid={bad || undefined}
                  onChange={(e) => setVals((v) => ({ ...v, [r]: e.target.value.replace(/[^0-9.,\s]/g, "") }))} />
              </div>
            );
          })}
          {tried && missing.length > 0 && (
            <p className="edit-hint is-warn" role="alert">
              {missing.length === 1 ? "One total is still empty." : `${missing.length} totals are still empty.`} Type 0 where the mother book shows nothing.
            </p>
          )}
        </fieldset>
      )}
    </Sheet>
  );
}
