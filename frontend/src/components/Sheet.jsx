import { useEffect, useRef } from "react";

/** An in-app modal sheet (native <dialog>: focus stays inside, Esc closes). Centered on
 *  desktop, slides up from the bottom on phones. Closing returns focus to whatever opened it
 *  (or `returnFocus()` when that element has gone, e.g. a menu item). */
export default function Sheet({ open, onClose, title, children, actions, labelledBy = "sheet-title", returnFocus, wide = false }) {
  const ref = useRef(null);
  const opener = useRef(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      opener.current = document.activeElement;
      d.showModal();
    }
    if (!open && d.open) {
      d.close();
      const back = opener.current;
      requestAnimationFrame(() => {
        if (document.activeElement && document.activeElement !== document.body && !d.contains(document.activeElement)) return;
        const el = back && back.isConnected && back !== document.body ? back : returnFocus?.();
        el?.focus?.();
      });
    }
  }, [open]);
  return (
    <dialog
      ref={ref}
      className={`sheet ${wide ? "sheet-wide" : ""}`}
      aria-labelledby={labelledBy}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => e.target === ref.current && onClose()}
    >
      {open && (
        <div className="sheet-body">
          <h2 className="sheet-title" id={labelledBy}>{title}</h2>
          {children}
          {actions && <div className="sheet-actions">{actions}</div>}
        </div>
      )}
    </dialog>
  );
}
