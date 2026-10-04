import { useEffect, useId, useRef, useState } from "react";
import Icon from "./Icon.jsx";

/**
 * A small "•••" menu of secondary actions, with the WAI-ARIA menu-button keyboard model:
 * opening focuses the first item (↑ on the button: the last), ↑ ↓ Home End move, Tab or Esc
 * close, and after a choice focus goes back to the button (so a sheet it opens returns there).
 */
export default function Menu({ label = "More actions", items, align = "end", icon = "more" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const trigger = useRef(null);
  const start = useRef("first");
  const id = useId();
  const entries = () => [...(ref.current?.querySelectorAll('[role="menuitem"]') || [])];

  useEffect(() => {
    if (!open) return;
    requestAnimationFrame(() => {
      const list = entries();
      (start.current === "last" ? list[list.length - 1] : list[0])?.focus();
    });
    const away = (e) => !ref.current?.contains(e.target) && setOpen(false);
    const esc = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        e.preventDefault();
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc, true);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc, true);
    };
  }, [open]);

  const onMenuKey = (e) => {
    const list = entries();
    const i = list.indexOf(document.activeElement);
    let n = null;
    if (e.key === "ArrowDown") n = (i + 1) % list.length;
    else if (e.key === "ArrowUp") n = (i - 1 + list.length) % list.length;
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = list.length - 1;
    else if (e.key === "Tab") setOpen(false);
    if (n !== null) {
      e.preventDefault();
      list[n]?.focus();
    }
  };
  const choose = (it) => {
    if (it.disabled) return;
    setOpen(false);
    trigger.current?.focus();
    it.onClick?.();
  };

  const shown = items.filter(Boolean);
  if (!shown.length) return null;
  return (
    <div className="menu" ref={ref}>
      <button ref={trigger} className="icon-btn icon-btn-lg" aria-label={label} title={label} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? id : undefined}
        onClick={() => { start.current = "first"; setOpen((o) => !o); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            start.current = e.key === "ArrowUp" ? "last" : "first";
            setOpen(true);
          }
        }}>
        <Icon name={icon} size={18} stroke={2} />
      </button>
      {open && (
        <ul className={`menu-pop align-${align}`} role="menu" id={id} aria-label={label} onKeyDown={onMenuKey}>
          {shown.map((it) => (
            <li key={it.label} role="none">
              {it.href ? (
                <a role="menuitem" tabIndex={-1} href={it.href} download={it.download} className={`menu-item ${it.danger ? "is-danger" : ""}`} onClick={() => setOpen(false)}>
                  {it.icon && <Icon name={it.icon} size={16} />}
                  {it.label}
                </a>
              ) : (
                <button role="menuitem" tabIndex={-1} className={`menu-item ${it.danger ? "is-danger" : ""} ${it.disabled ? "is-disabled" : ""}`}
                  aria-disabled={it.disabled || undefined} aria-describedby={it.note ? `${id}-${it.label.length}` : undefined} onClick={() => choose(it)}>
                  {it.icon && <Icon name={it.icon} size={16} />}
                  <span className="menu-text">
                    {it.label}
                    {it.note && <span className="menu-note" id={`${id}-${it.label.length}`}>{it.note}</span>}
                  </span>
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
