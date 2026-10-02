import { useLayoutEffect, useRef, useState } from "react";
import { SHORT, display } from "../../format.js";
import { EDITED } from "./ranking.js";

/** Visible edge fade + hint when a table is wider than its card, so nothing is silently cut off. */
export function useOverflow() {
  const ref = useRef(null);
  const [state, setState] = useState({ more: false, scrolled: false });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setState({ more: el.scrollLeft + el.clientWidth < el.scrollWidth - 2, scrolled: el.scrollLeft > 2 });
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    if (el.firstElementChild) ro.observe(el.firstElementChild);
    el.addEventListener("scroll", check, { passive: true });
    return () => {
      ro.disconnect();
      el.removeEventListener("scroll", check);
    };
  }, []);
  return [ref, state];
}

export const hasW5 = (fields) => Object.keys(fields).some((f) => f.startsWith("weekly.") && f.endsWith(".W5") && fields[f]?.value != null);

export default function WeeklyTable({ template, fields, flagged, selected, onSelect, review }) {
  const cols = ["W1", "W2", "W3", "W4", ...(hasW5(fields) ? ["W5"] : []), "Total"];
  const [ref, ov] = useOverflow();
  const anyEdited = Object.values(fields).some((fv) => EDITED.includes(fv?.status));
  const anyFlagged = review && Object.keys(flagged).length > 0;
  let lastSection = null;
  return (
    <>
      <div className={`table-scroll ${ov.more ? "has-more" : ""} ${ov.scrolled ? "is-scrolled" : ""}`}>
        <div className="table-wrap" ref={ref} tabIndex={ov.more ? 0 : undefined} role={ov.more ? "region" : undefined} aria-label={ov.more ? "Weekly figures, scrolls sideways" : undefined}>
          <table className="weekly">
            <thead>
              <tr>
                <th scope="col"><span className="sr-only">Row</span></th>
                {cols.map((c) => <th key={c} scope="col">{c}</th>)}
              </tr>
            </thead>
            <tbody>
              {template.weekly.map((r) => {
                const out = [];
                if (r.section && r.section !== lastSection && r.section !== "Financial Statement") {
                  out.push(<tr key={`s-${r.key}`} className="section-row"><th colSpan={cols.length + 1} scope="rowgroup">{r.section}</th></tr>);
                }
                lastSection = r.section;
                out.push(
                  <tr key={r.key}>
                    <th scope="row" className={r.key.startsWith("loan_purpose") ? "sub" : ""}>{SHORT[r.key]}</th>
                    {cols.map((c) => {
                      const fid = `weekly.${r.key}.${c}`;
                      if (!r.columns.includes(c)) return <td key={c} className="shaded"><span className="sr-only">Not used on the form</span></td>;
                      const fv = fields[fid];
                      const v = fv?.value;
                      const cls = [review && flagged[fid] ? "is-flagged" : "", selected === fid ? "is-selected" : "", EDITED.includes(fv?.status) ? "is-edited" : ""].join(" ");
                      return (
                        <td key={c} className={cls}>
                          <button onClick={() => onSelect(fid, { scroll: true })} aria-pressed={selected === fid}
                            aria-label={`${SHORT[r.key]}, ${c === "Total" ? "total" : c}: ${display(v, r.type) || "blank"}${review && flagged[fid] ? ", needs a check" : ""}`}>
                            {display(v, r.type)}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                );
                return out;
              })}
            </tbody>
          </table>
        </div>
        {ov.more && <span className="scroll-hint" aria-hidden>Scroll sideways for more</span>}
      </div>
      <ul className="legend" aria-label="What the colours mean">
        {anyFlagged && <li><i className="sw sw-flag" />In a check that fails</li>}
        {anyEdited && <li><i className="sw sw-edit" />Corrected</li>}
        <li><i className="sw sw-shade" />Not used on the form</li>
      </ul>
    </>
  );
}
