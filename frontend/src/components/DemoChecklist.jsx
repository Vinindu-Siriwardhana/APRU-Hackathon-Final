import { useEffect, useRef } from "react";
import Icon from "./Icon.jsx";

const ORDER = ["collecting", "needs_review", "awaiting_member", "written"];
const stage = (s) => ORDER.indexOf(s.status);

/**
 * The six beats of the demo, ticked from what has actually happened (reports and the
 * phone conversation), with a Go link to the screen for each step.
 */
export function demoSteps(subs, phone) {
  const sorted = [...subs].sort((a, b) => stage(b) - stage(a) || String(b.created).localeCompare(String(a.created)));
  const best = sorted.find((s) => stage(s) >= 1) || sorted[0];
  const reached = (n) => subs.some((s) => stage(s) >= n);
  const fixed = subs.some((s) => (s.status === "needs_review" && !s.errors) || stage(s) >= 2);
  const sentImage = phone.messages.some((m) => m.from !== "bot" && m.image) || subs.length > 0;
  const saidOk = phone.messages.some((m) => m.from !== "bot" && /^\s*ok\b/i.test(m.text || "")) || reached(3);
  const report = (filter) => (best ? `#/inbox/${filter}/${best.id}` : `#/inbox/${filter}`);
  return [
    { title: "Send a form photo", sub: "On Member’s phone, pick Tamil, then send Kalaimagal October page 1 and page 2.", done: sentImage, href: "#/phone" },
    { title: "A report needs review", sub: "The ledger checks found figures that don’t add up.", done: reached(1), href: report("needs_review") },
    { title: "Fix the reading mistakes", sub: "Use 310 for interest in week 3, then pick 2800 for savings in week 2.", done: fixed, href: report("needs_review") },
    { title: "Send it to the member", sub: "She gets the summary on WhatsApp, in Tamil.", done: reached(2), href: report("awaiting_member") },
    { title: "The member replies OK", sub: "Tap OK on the phone. The receipt comes back.", done: saidOk, href: "#/phone" },
    { title: "Recorded in the workbook", sub: "Open the report to see the cells written to Palmera’s sheet.", done: reached(3), href: report("written") },
  ];
}

export default function DemoChecklist({ steps, onClose }) {
  const ref = useRef(null);
  const done = steps.filter((s) => s.done).length;
  const current = steps.findIndex((s) => !s.done);
  useEffect(() => {
    const esc = (e) => e.key === "Escape" && !document.querySelector("dialog[open]") && onClose();
    window.addEventListener("keydown", esc);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  return (
    <section className="checklist" aria-labelledby="checklist-h" tabIndex={-1} ref={ref}>
      <header className="checklist-head">
        <div>
          <h2 id="checklist-h">Demo guide</h2>
          <p>{done === steps.length ? "All done. Restart the demo to run it again." : `${done} of ${steps.length} done`}</p>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close the demo guide"><Icon name="close" size={14} stroke={2.2} /></button>
      </header>
      <div className="progress" aria-hidden><span style={{ width: `${(done / steps.length) * 100}%` }} /></div>
      <ol className="steps">
        {steps.map((s, i) => (
          <li key={s.title} className={`step ${s.done ? "is-done" : ""} ${i === current ? "is-current" : ""}`}>
            <span className="step-mark" aria-hidden>{s.done ? <Icon name="checkmark" size={12} stroke={3} /> : i + 1}</span>
            <div className="step-body">
              <span className="step-title">{s.title}<span className="sr-only">{s.done ? ", done" : ", to do"}</span></span>
              {i === current && <span className="step-sub">{s.sub}</span>}
            </div>
            <a className={`step-go ${i === current ? "is-primary" : ""}`} href={s.href} aria-label={`Go: ${s.title}`}>Go</a>
          </li>
        ))}
      </ol>
      <a className="checklist-foot" href="#/guide/presenting">The full presenter script</a>
    </section>
  );
}
