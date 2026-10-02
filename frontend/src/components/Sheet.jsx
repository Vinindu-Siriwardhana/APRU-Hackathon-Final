import { useEffect, useRef } from "react";

/** An in-app modal sheet (native <dialog>: focus stays inside, Esc closes). Centered on
 *  desktop, slides up from the bottom on phones. */
export default function Sheet({ open, onClose, title, children, actions, labelledBy = "sheet-title" }) {
  const ref = useRef(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className="sheet"
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
