import { WORKBOOK_URL } from "../../api.js";
import { isMoneyLabel, money, monthName, shortMonthly } from "../../format.js";
import Icon from "../Icon.jsx";

const lastEvent = (log, test) => [...(log || [])].reverse().find((e) => e.event && test(e.event));
const REJECT_TEXT = {
  unclear: "The photos are not clear enough to read.",
  missing_page: "A page is missing.",
  wrong_form: "This is not the SHG monthly report form.",
  wrong_group: "The group name or the month on the form is not right.",
  incomplete: "Some parts of the form are empty.",
};
const ID = /^[0-9a-f]{10}$/;
/** The id of the report that replaced this one, wherever the log event keeps it. */
const newerId = (e) => e && [e.by_id, e.new_id, e.newer, e.replaced_by, e.superseded_by, e.id, e.by].find((v) => typeof v === "string" && ID.test(v));

/** One clear sentence (or card) saying where this report stands and what happens next. */
export default function StatusCard({ sub, errors, cleared, onRetry, busy }) {
  const log = sub.log;
  const forced = sub.forced || (lastEvent(log, (n) => n === "officer_approved")?.forced ? lastEvent(log, (n) => n === "officer_approved") : null);
  const forcedNote = forced ? (
    <p className="status-note">
      <Icon name="warn" size={14} /> Sent without every check passing{forced.reason ? `: “${forced.reason}”` : "."}
    </p>
  ) : null;

  switch (sub.status) {
    case "needs_review": {
      // she already said OK, but the workbook refused the write (e.g. Excel had the file open)
      const failedWrite = errors.find((i) => i.rule === "write_failed");
      const others = errors.filter((i) => i.rule !== "write_failed");
      if (failedWrite && !others.length)
        return (
          <div className="statusline tone-red" role="status">
            <span>
              She confirmed the figures, but the workbook couldn’t be written: {failedWrite.message} Then press <strong>Write to workbook</strong>.
            </span>
          </div>
        );
      return (
        <div className={`statusline tone-${errors.length ? "orange" : "green"}`} role="status">
          <span>
            {errors.length
              ? `${errors.length === 1 ? "One check needs" : `${errors.length} checks need`} your eye before this goes back to the member.`
              : "Everything checks out. Send it to the member to confirm."}
          </span>
          {cleared && (
            <span key={cleared.at} className="cleared-pill">
              <Icon name="checkmark" size={13} stroke={2.6} /> {cleared.n === 1 ? "1 check cleared" : `${cleared.n} checks cleared`}
            </span>
          )}
        </div>
      );
    }
    case "awaiting_member":
      return (
        <div className="statusline tone-blue" role="status">
          <span>She has the summary on WhatsApp. It’s written to the workbook when she replies OK.</span>
          {forcedNote}
        </div>
      );
    case "written":
      return <WrittenCard sub={sub} forcedNote={forcedNote} />;
    case "failed": {
      const e = lastEvent(log, (n) => n.includes("fail"));
      const why = sub.failure || e?.reason || e?.error;
      return (
        <div className="statusline tone-red" role="status">
          <span>
            The photos couldn’t be read{why ? `: ${why.replace(/\.$/, "")}.` : "."} She’s been told an officer will follow up.
          </span>
          <button className="btn btn-small btn-primary" onClick={onRetry} disabled={busy}>Try again</button>
        </div>
      );
    }
    case "superseded": {
      const e = lastEvent(log, (n) => n.includes("supersed") || n.includes("replaced"));
      const id = sub.superseded_by || newerId(e);
      return (
        <div className="statusline tone-grey" role="status">
          <span>A newer report for this group and month replaced this one. Nothing from it was written.</span>
          {id && <a href={`#/inbox/all/${id}`}>Open the newer report</a>}
        </div>
      );
    }
    case "rejected": {
      const e = lastEvent(log, (n) => n.includes("reject"));
      const code = sub.rejected_reason || e?.reason;
      const text = code === "member_opted_out"
        ? "The member replied STOP, so this report was closed. Nothing from it was written."
        : `You asked the member for new photos${REJECT_TEXT[code] ? `: ${REJECT_TEXT[code].toLowerCase().replace(/\.$/, "")}.` : "."}${e?.note && e.note !== code ? ` Your note: “${e.note}”.` : ""} Nothing from this report was written.`;
      return (
        <div className="statusline tone-grey" role="status">
          <span>{text}</span>
        </div>
      );
    }
    default:
      return (
        <div className="statusline tone-grey" role="status">
          <span>{sub.pages?.[1] && !sub.pages?.[2] ? "Page 1 arrived. Waiting for page 2." : sub.pages?.[2] ? "Page 2 arrived. Waiting for page 1." : "Waiting for the member’s photos."}</span>
        </div>
      );
  }
}

/** The proper ending: exactly which cells went into Palmera's workbook. */
function WrittenCard({ sub, forcedNote }) {
  const w = sub.write_report;
  if (!w) {
    return (
      <div className="statusline tone-green" role="status">
        <span>Confirmed by the member and recorded in Palmera’s workbook.</span>
      </div>
    );
  }
  const val = (label, v) => (v === null || v === undefined || v === "" ? "—" : isMoneyLabel(label) && typeof v === "number" ? money(v) : typeof v === "number" ? v.toLocaleString("en-US") : String(v));
  return (
    <section className="written-card" aria-labelledby="written-h">
      <div className="written-head">
        <span className="written-mark" aria-hidden><Icon name="checkmark" size={18} stroke={2.6} /></span>
        <div>
          <h2 className="written-title" id="written-h">Written to Palmera’s workbook</h2>
          <p className="written-sub">
            Tab {w.sheet}, column {w.column}, {w.writes.length} cells{w.month ? ` for ${monthName(w.month)}` : ""}. The member confirmed every figure.
            {w.created_tab ? " A new tab was made for this group." : ""}
          </p>
        </div>
        <a className="btn btn-small btn-quiet" href={WORKBOOK_URL} download>
          <Icon name="download" size={15} /> Download workbook
        </a>
      </div>
      {forcedNote}
      <div className="table-wrap written-table">
        <table className="cells">
          <thead>
            <tr><th scope="col">Row</th><th scope="col">Cell</th><th scope="col">Before</th><th scope="col">Now</th></tr>
          </thead>
          <tbody>
            {w.writes.map((c) => (
              <tr key={c.cell}>
                <th scope="row">{shortMonthly(c.label)}</th>
                <td className="cell-ref">{String(c.cell).replace(/^.*!/, "")}</td>
                <td className="muted">{val(c.label, c.old)}</td>
                <td className="cell-new">{val(c.label, c.new)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {w.warnings?.length > 0 && <ul className="written-warn">{w.warnings.map((t, i) => <li key={i}>{t}</li>)}</ul>}
    </section>
  );
}
