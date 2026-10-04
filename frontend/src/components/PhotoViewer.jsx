import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Icon from "./Icon.jsx";

/** How far the photo may zoom in on a value. Enough to make a digit readable on a projector. */
const MAX_ZOOM = 5;

/**
 * The original photo. When a value is selected, the photo glides and zooms to where that
 * value was written, dims everything else, and labels it — the audit trail, made visible.
 */
export default function PhotoViewer({ pages, page, onPage, src, box, label, onClear }) {
  const frame = useRef(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [nat, setNat] = useState({ w: 0, h: 0 });
  const [loaded, setLoaded] = useState(false);

  useLayoutEffect(() => {
    if (!frame.current) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(frame.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => setLoaded(false), [page]);

  // fit the photo inside the frame (scale 1), then zoom so the value sits in the middle with
  // enough of its row and column around it to read it in context
  const fit = nat.w && size.w ? Math.min(size.w / nat.w, size.h / nat.h) : 1;
  const W = nat.w * fit, H = nat.h * fit;
  const ox = (size.w - W) / 2, oy = (size.h - H) / 2;
  let s = 1, tx = ox, ty = oy, pill = null;
  if (box && W) {
    const bw = (box.x1 - box.x0) * W, bh = (box.y1 - box.y0) * H;
    s = Math.max(1, Math.min(MAX_ZOOM, (size.w * 0.3) / bw, (size.h * 0.16) / bh));
    const cx = ((box.x0 + box.x1) / 2) * W, cy = ((box.y0 + box.y1) / 2) * H;
    tx = size.w / 2 - cx * s;
    ty = size.h / 2 - cy * s;
    // keep the photo edges from pulling into view when the box is near a corner
    tx = Math.min(0, Math.max(size.w - W * s, tx));
    ty = Math.min(0, Math.max(size.h - H * s, ty));
    if (W * s < size.w) tx = (size.w - W * s) / 2;
    if (H * s < size.h) ty = (size.h - H * s) / 2;
    const top = ty + box.y0 * H * s;
    const below = top < 54;
    pill = {
      x: Math.min(size.w - 90, Math.max(90, tx + cx * s)),
      y: below ? ty + box.y1 * H * s + 12 : top - 12,
      below,
    };
  }

  return (
    <div className="viewer">
      <div className="viewer-bar">
        {pages.length > 1 ? (
          <div className="segmented" role="tablist" aria-label="Page of the form"
            onKeyDown={(e) => {
              const i = pages.indexOf(page);
              const n = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? pages.length - 1 : null;
              if (n === null) return;
              e.preventDefault();
              const p = pages[(n + pages.length) % pages.length];
              onPage(p);
              e.currentTarget.querySelector(`[data-page="${p}"]`)?.focus();
            }}>
            {pages.map((p) => (
              <button key={p} role="tab" data-page={p} id={`page-tab-${p}`} aria-selected={page === p} aria-controls="page-panel" tabIndex={page === p ? 0 : -1}
                className={page === p ? "is-on" : ""} onClick={() => onPage(p)}>
                Page {p}
              </button>
            ))}
          </div>
        ) : (
          <span className="viewer-caption">{pages.length ? `Page ${pages[0]} of the form` : "No photo yet"}</span>
        )}
        {box && (
          <button className="viewer-reset" onClick={onClear}>
            <Icon name="expand" size={15} /> Whole page
          </button>
        )}
      </div>
      <div className="viewer-frame" ref={frame} id="page-panel" role={pages.length > 1 ? "tabpanel" : undefined} aria-labelledby={pages.length > 1 ? `page-tab-${page}` : undefined}>
        {pages.includes(page) ? (
          <>
            <div
              className={`viewer-layer ${loaded ? "is-loaded" : ""}`}
              style={{ width: W || "100%", height: H || "auto", transform: `translate(${tx}px, ${ty}px) scale(${s})` }}
            >
              <img
                src={src(page)}
                alt={`Photo of page ${page} of the form`}
                draggable={false}
                onLoad={(e) => {
                  setNat({ w: e.target.naturalWidth, h: e.target.naturalHeight });
                  setLoaded(true);
                }}
              />
              {box && (
                <div
                  className="focus-ring"
                  style={{
                    left: `${box.x0 * 100}%`,
                    top: `${box.y0 * 100}%`,
                    width: `${(box.x1 - box.x0) * 100}%`,
                    height: `${(box.y1 - box.y0) * 100}%`,
                    "--inv": 1 / s,
                  }}
                />
              )}
            </div>
            {pill && label && loaded && (
              <div className={`viewer-pill ${pill.below ? "is-below" : ""}`} style={{ transform: `translate(${pill.x}px, ${pill.y}px)` }} aria-hidden>
                <span key={label}>{label}</span>
              </div>
            )}
            {!loaded && <div className="viewer-loading" aria-hidden />}
          </>
        ) : (
          <div className="viewer-empty">
            <Icon name="photo" size={36} stroke={1.2} />
            <p>Page {page} hasn’t arrived yet.</p>
          </div>
        )}
      </div>
    </div>
  );
}
