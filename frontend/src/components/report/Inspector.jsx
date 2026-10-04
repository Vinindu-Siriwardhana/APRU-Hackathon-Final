import { useEffect, useRef, useState } from "react";
import { OFFICER, cropUrl } from "../../api.js";
import { curly, display, fieldParts, money, num } from "../../format.js";
import Icon from "../Icon.jsx";

const asText = (v) => (v === null || v === undefined ? "" : typeof v === "boolean" ? (v ? "Yes" : "No") : String(v));
const coarse = () => typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches;
const INPUT_MODE = { money: "decimal", int: "numeric", text: "text", month: "text", date: "text" };
/** The key officers hold to move between flagged values: Option on a Mac, Alt elsewhere. */
export const ALT_KEY = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || "") ? "⌥" : "Alt";
/** Money and counts take digits only: a stray letter never reaches the field, let alone the server. */
const NUMERIC = { money: /[^0-9.,\s]/g, int: /[^0-9,\s]/g };
const isFigure = (v, type) => v === "" || !NUMERIC[type] || /^\d[\d,\s]*(\.\d+)?$|^\.\d+$/.test(v.trim());

/** What we can honestly say about a value, given where the whole report is. */
function statusText(fv, reportStatus) {
  if (fv.status === "officer_confirmed") return "Checked against the photo, kept as written";
  if (fv.status === "officer_corrected") return "Corrected by an officer";
  if (fv.status === "member_corrected") return "Corrected by the member";
  if (fv.status === "member_confirmed" || reportStatus === "written") return "Confirmed by the member";
  if (fv.status === "needs_review" && reportStatus === "needs_review") return "Needs your check";
  return "Read automatically";
}

/**
 * The selected value: the handwriting itself, what the AI read, what the ledger suggests,
 * and the officer's three choices — Use the suggestion, Save a typed value, Keep as written.
 */
export default function Inspector({ sid, fid, fv, type, labels, issues, suggestion, reportStatus, editable, busy, canNav, onSave, onClose }) {
  const initial = asText(fv.value);
  const [val, setVal] = useState(initial);
  const [picked, setPicked] = useState(false);
  const [hint, setHint] = useState(false); // false | "choose" | "figure"
  const [cropOk, setCropOk] = useState(true);
  const input = useRef(null);
  const passes = (fv.passes || []).map(asText);
  const disagree = passes.length > 1 && new Set(passes).size > 1;
  const translation = (fv.history || []).find((h) => h.event === "translation")?.english;
  const officer = [...(fv.history || [])].reverse().find((h) => h.event === "officer");
  const changed = val.trim() !== initial;
  const { row, col } = fieldParts(fid, labels);
  const isYesNo = type === "yesno";
  const isMoney = type === "money";
  const readAs = fv.raw ?? (initial || null);
  const status = statusText(fv, reportStatus);

  useEffect(() => {
    if (!editable || isYesNo || coarse()) return;
    input.current?.focus({ preventScroll: true });
    input.current?.select();
  }, [editable, isYesNo]);

  const submit = (e) => {
    e?.preventDefault();
    if (busy) return;
    if (!isFigure(val, type)) {
      setHint("figure");
      input.current?.focus({ preventScroll: true });
      return;
    }
    onSave(val.trim() === "" ? null : val.trim());
  };

  const by = (h) => (h.by === OFFICER ? "you" : h.by);
  const shown = (v) => (isMoney && v !== "" && v !== null && v !== undefined && !isNaN(Number(v)) ? money(v) : display(v, type) || "blank");

  return (
    <section className="inspector" aria-labelledby="insp-title">
      <header className="inspector-head">
        <div className="inspector-titles">
          <h2 className="inspector-title" id="insp-title">
            {row} <span className="inspector-col">{col}</span>
          </h2>
          <p className={`inspector-status ${status === "Needs your check" ? "is-attention" : ""}`}>{status}</p>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close (Esc)" title="Close (Esc)">
          <Icon name="close" size={14} stroke={2.2} />
        </button>
      </header>

      <div className="evidence">
        {fv.box && cropOk && (
          <figure className="crop">
            <img src={cropUrl(sid, fid)} alt={`Handwriting for ${row}, ${col}`} onError={() => setCropOk(false)} />
          </figure>
        )}
        <div className="read-as">
          <span className="read-as-label">Read as</span>
          <span className="read-as-value">{readAs === null || readAs === "" ? "Blank" : isMoney && !isNaN(Number(readAs)) ? num(Number(readAs)) : readAs}</span>
          {passes.length > 1 && !disagree && <span className="read-as-note">Both readings agree</span>}
          {!fv.box && <span className="muted small">This value has no place on the photo.</span>}
        </div>
      </div>

      {disagree && (
        <div className="readings">
          <p className="readings-label" id="readings-l">The two readings disagree. Which matches the handwriting?</p>
          <div className="choice-row" role="group" aria-labelledby="readings-l">
            {passes.map((p, i) => (
              <button
                key={i}
                type="button"
                className={`choice ${picked && val === p ? "is-on" : ""}`}
                aria-pressed={picked && val === p}
                disabled={!editable}
                onClick={() => {
                  setVal(p);
                  setPicked(true);
                  setHint(false);
                  input.current?.focus({ preventScroll: true });
                }}
              >
                <span className="choice-k">Reading {i + 1}</span>
                <span className="choice-v">{p === "" ? "Blank" : isMoney ? num(Number(p)) : p}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {editable && suggestion && (
        <div className="suggest">
          <p className="suggest-text">
            <strong>{isMoney ? num(Number(suggestion.value)) : suggestion.value}</strong> would make{" "}
            {suggestion.balances === 1 ? "the check" : `${suggestion.balances} checks`} balance
          </p>
          <button className="btn btn-primary" disabled={busy} onClick={() => onSave(String(suggestion.value))}>
            Use {isMoney ? num(Number(suggestion.value)) : suggestion.value}
          </button>
        </div>
      )}

      {translation && <p className="translation"><span>In English</span>{translation}</p>}

      {editable ? (
        <form className="edit" onSubmit={submit}>
          <label className="edit-label" id="edit-label" htmlFor={isYesNo ? undefined : "edit-value"}>{fid.includes("meeting_held") ? "Was a meeting held?" : "Value on the form"}</label>
          <div className="edit-row">
            {isYesNo ? (
              <div className="segmented" role="radiogroup" id="edit-value" aria-labelledby="edit-label"
                onKeyDown={(e) => {
                  const opts = ["Yes", "No", ""];
                  const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
                  if (!d || e.altKey) return;
                  e.preventDefault();
                  const n = opts[(opts.indexOf(val) + d + opts.length) % opts.length];
                  setVal(n);
                  e.currentTarget.querySelector(`[data-v="${n}"]`)?.focus();
                }}>
                {["Yes", "No", ""].map((o) => (
                  <button key={o || "blank"} type="button" role="radio" data-v={o} aria-checked={val === o} tabIndex={val === o || (!["Yes", "No", ""].includes(val) && o === "Yes") ? 0 : -1}
                    className={val === o ? "is-on" : ""} onClick={() => setVal(o)}>
                    {o || "Blank"}
                  </button>
                ))}
              </div>
            ) : (
              <input
                id="edit-value"
                ref={input}
                className="field"
                value={val}
                onChange={(e) => {
                  const clean = NUMERIC[type] ? e.target.value.replace(NUMERIC[type], "") : e.target.value;
                  setVal(clean);
                  setPicked(false);
                  setHint(false);
                }}
                onFocus={(e) => e.target.select()}
                onKeyDown={(e) => {
                  // Enter on an untouched value would confirm a number the ledger says is
                  // wrong: ask for an explicit choice instead
                  if (e.key === "Enter" && !changed && !picked && suggestion) {
                    e.preventDefault();
                    setHint("choose");
                  }
                }}
                placeholder="Blank"
                inputMode={INPUT_MODE[type] || "text"}
                autoComplete="off"
                enterKeyHint="done"
                aria-describedby={hint ? "edit-hint" : undefined}
              />
            )}
            {changed || picked ? (
              <button className={`btn ${suggestion ? "btn-tinted" : "btn-primary"}`} disabled={busy}>
                {picked && !changed ? `Use ${shown(val)}` : "Save"}
              </button>
            ) : (
              <button className={`btn ${suggestion ? "btn-quiet" : "btn-primary"}`} disabled={busy} title="The photo shows this value: keep it as written">
                Keep {initial === "" ? "blank" : isMoney ? num(Number(initial)) : display(initial, type) || initial}
              </button>
            )}
          </div>
          {hint ? (
            <p className="edit-hint is-warn" id="edit-hint" role="alert">
              {hint === "figure"
                ? "That isn’t a figure. Type it in digits, as on the photo, for example 1,200."
                : "The checks say this doesn’t add up. Type the figure on the photo, use the suggestion, or choose Keep."}
            </p>
          ) : (
            <p className="edit-hint" aria-hidden>
              <span><kbd>Enter</kbd> save and go to the next</span> <span><kbd>Esc</kbd> close</span>
              {canNav && <span><kbd>{ALT_KEY}</kbd><kbd>↓</kbd><kbd>↑</kbd> next or previous flagged value</span>}
            </p>
          )}
        </form>
      ) : (
        <p className="inspector-value">{shown(fv.value)}</p>
      )}

      {officer && (
        <p className="inspector-note">
          <Icon name="checkmark" size={13} stroke={2.4} />
          {String(officer.old) === String(officer.new)
            ? `Confirmed against the photo by ${by(officer)}.`
            : `Changed from ${shown(officer.old)} to ${shown(officer.new)} by ${by(officer)}.`}
        </p>
      )}
      {issues.length > 0 && (
        <details className="inspector-issues">
          <summary>{issues.length === 1 ? "1 check involves this value" : `${issues.length} checks involve this value`}</summary>
          <ul>{issues.map((i, k) => <li key={k}>{curly(i.message)}</li>)}</ul>
        </details>
      )}
    </section>
  );
}
