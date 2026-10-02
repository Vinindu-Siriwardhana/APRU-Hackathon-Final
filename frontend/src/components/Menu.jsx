import { useEffect, useId, useRef, useState } from "react";
import Icon from "./Icon.jsx";

/** A small "•••" menu of secondary actions. Closes on Esc, outside click or after a choice. */
export default function Menu({ label = "More actions", items, align = "end", icon = "more" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const away = (e) => !ref.current?.contains(e.target) && setOpen(false);
    const esc = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
        ref.current?.querySelector("button")?.focus();
      }
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc, true);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc, true);
    };
  }, [open]);
  const shown = items.filter(Boolean);
  if (!shown.length) return null;
  return (
    <div className="menu" ref={ref}>
      <button className="icon-btn icon-btn-lg" aria-label={label} title={label} aria-haspopup="menu" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        <Icon name={icon} size={18} stroke={2} />
      </button>
      {open && (
        <ul className={`menu-pop align-${align}`} role="menu" id={id}>
          {shown.map((it) => (
            <li key={it.label} role="none">
              {it.href ? (
                <a role="menuitem" href={it.href} download={it.download} className={`menu-item ${it.danger ? "is-danger" : ""}`} onClick={() => setOpen(false)}>
                  {it.icon && <Icon name={it.icon} size={16} />}
                  {it.label}
                </a>
              ) : (
                <button role="menuitem" className={`menu-item ${it.danger ? "is-danger" : ""}`} disabled={it.disabled}
                  onClick={() => { setOpen(false); it.onClick(); }}>
                  {it.icon && <Icon name={it.icon} size={16} />}
                  {it.label}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
