import { useEffect, useState } from "react";
import { api } from "../../api.js";
import Sheet from "../Sheet.jsx";

/** "Send anyway…": the officer's escape hatch when a check can't be resolved. A reason is required. */
export function ForceSheet({ open, onClose, onConfirm, errors, busy, recorded }) {
  const [reason, setReason] = useState("");
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Send anyway?"
      labelledBy="force-title"
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
export function RejectSheet({ open, onClose, onConfirm, busy }) {
  const [reasons, setReasons] = useState(FALLBACK_REASONS);
  const [code, setCode] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    if (open) api.rejectReasons().then((r) => Array.isArray(r) && r.length && setReasons(r)).catch(() => {});
  }, [open]);
  const chosen = reasons.find((r) => r.code === code);
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Ask for a new photo"
      labelledBy="reject-title"
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
      <div className="preset-row" role="radiogroup" aria-labelledby="reject-why">
        {reasons.map((r) => (
          <button key={r.code} type="button" role="radio" className={`chip ${code === r.code ? "is-selected" : ""}`} aria-checked={code === r.code} onClick={() => setCode(r.code)}>
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
