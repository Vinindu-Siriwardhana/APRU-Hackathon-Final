import { useEffect, useState } from "react";

export default function Toast({ toast }) {
  const [shown, setShown] = useState(null);
  useEffect(() => {
    if (!toast) return;
    setShown(toast);
    const t = setTimeout(() => setShown(null), 3200);
    return () => clearTimeout(t);
  }, [toast]);
  return (
    <div className="toast-wrap" role="status" aria-live="polite">
      {shown && (
        <div key={shown.at} className={`toast tone-${shown.tone}`}>
          {shown.tone === "green" && <span className="toast-dot" aria-hidden />}
          {shown.text}
        </div>
      )}
    </div>
  );
}
