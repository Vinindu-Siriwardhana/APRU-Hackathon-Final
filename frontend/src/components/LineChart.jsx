import { useLayoutEffect, useRef, useState } from "react";

/** Single-series line chart drawn at the container's real pixel width, so text never
 *  shrinks. The y axis is labelled (top and bottom) so a small change never looks like a
 *  spike; money charts start at 0. Points are not tab stops: the svg's label reads them all. */
export default function LineChart({ title, labels, values, format = String, axisFormat = format, min, max }) {
  const wrap = useRef(null);
  const [W, setW] = useState(320);
  const [hover, setHover] = useState(null);
  useLayoutEffect(() => {
    const ro = new ResizeObserver(([e]) => setW(Math.max(200, e.contentRect.width)));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  const H = 150, L = 46, R = 8, T = 12, B = 26;
  const dataLo = Math.min(...values), dataHi = Math.max(...values);
  const lo = min ?? Math.max(0, dataLo - (dataHi - dataLo || Math.abs(dataHi) || 1) * 0.35);
  const rawHi = max ?? (dataHi <= lo ? lo + 1 : dataHi);
  const hi = max ?? niceCeil(rawHi);
  const x = (i) => L + (values.length === 1 ? (W - L - R) / 2 : (i / (values.length - 1)) * (W - L - R));
  const y = (v) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
  const pts = values.map((v, i) => [x(i), y(v)]);
  const last = values.length - 1;
  const area = `M${pts[0][0]},${H - B} ` + pts.map((p) => `L${p[0]},${p[1]}`).join(" ") + ` L${pts[last][0]},${H - B} Z`;
  const gid = `g-${title.replace(/\W/g, "")}`;

  return (
    <figure className="chart">
      <figcaption className="chart-title">
        <span className="chart-name">{title}</span>
        <span className="chart-now">
          {format(values[last])}
          <small>in {labels[last]}</small>
        </span>
      </figcaption>
      <div className="chart-body" ref={wrap}>
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
          aria-label={`${title}: ${labels.map((l, i) => `${l} ${format(values[i])}`).join(", ")}`}
          onMouseLeave={() => setHover(null)}>
          <defs>
            <linearGradient id={gid} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="var(--accent)" stopOpacity="0.16" />
              <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[0, 0.5, 1].map((f) => (
            <line key={f} x1={L} x2={W - R} y1={T + f * (H - T - B)} y2={T + f * (H - T - B)} className="chart-grid" />
          ))}
          <text x={L - 8} y={T + 4} className="chart-ylabel" textAnchor="end">{axisFormat(hi)}</text>
          <text x={L - 8} y={H - B + 4} className="chart-ylabel" textAnchor="end">{axisFormat(lo)}</text>
          <path d={area} fill={`url(#${gid})`} />
          <polyline points={pts.map((p) => p.join(",")).join(" ")} className="chart-line" />
          {hover !== null && <line x1={pts[hover][0]} x2={pts[hover][0]} y1={T - 6} y2={H - B} className="chart-grid" />}
          {pts.map(([px, py], i) => (
            <g key={i} aria-hidden>
              <circle cx={px} cy={py} r={i === hover ? 5 : 4} className="chart-dot" />
              <rect x={px - (W - L) / values.length / 2} y={0} width={(W - L) / values.length} height={H} fill="transparent" onMouseEnter={() => setHover(i)} />
              <text x={px} y={H - 7} className="chart-axis" textAnchor={i === 0 ? "start" : i === last ? "end" : "middle"}>{labels[i]}</text>
            </g>
          ))}
        </svg>
        {hover !== null && (
          <div className="chart-tip" style={{ left: pts[hover][0], top: pts[hover][1] }} aria-hidden>
            <span>{labels[hover]}</span>
            <strong>{format(values[hover])}</strong>
          </div>
        )}
      </div>
    </figure>
  );
}

/** Round up to a tidy axis maximum (1, 2, 2.5 or 5 × a power of ten). */
function niceCeil(v) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}
