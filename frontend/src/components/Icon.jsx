// Small line icons in the spirit of SF Symbols (drawn here; no icon font needed offline).
const P = {
  tray: "M4 13.5V18a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4.5M4 13.5 6.3 5.6A2 2 0 0 1 8.2 4h7.6a2 2 0 0 1 1.9 1.6l2.3 7.9M4 13.5h4.5l1.2 2.2h4.6l1.2-2.2H20",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm0-13.5V12l3 2",
  check: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm-4-9 2.8 2.8L16.5 9",
  stack: "M4 8.5 12 4l8 4.5-8 4.5-8-4.5zm0 4 8 4.5 8-4.5M4 16l8 4.5 8-4.5",
  chart: "M4 20h16M6.5 16.5l4-5 3.5 3 5-7",
  phone: "M8 2.8h8a1.8 1.8 0 0 1 1.8 1.8v14.8a1.8 1.8 0 0 1-1.8 1.8H8a1.8 1.8 0 0 1-1.8-1.8V4.6A1.8 1.8 0 0 1 8 2.8zM10.5 5h3",
  download: "M12 4v11m0 0-4-4m4 4 4-4M5 19h14",
  reset: "M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4.5v3.8h3.8",
  warn: "M12 4 2.8 19.5h18.4L12 4zm0 6v4.2m0 2.6v.1",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm0-10v5.5m0-8.3v.1",
  checkmark: "m5 12.5 4.5 4.5L19 7.5",
  chevron: "m9 5 7 7-7 7",
  back: "m15 5-7 7 7 7",
  send: "M12 19V5m0 0-5.5 5.5M12 5l5.5 5.5",
  photo: "M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7zm0 9 5-5 4 4 2.5-2.5L20 17M15.5 9.5v.1",
  person: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-7 8a7 7 0 0 1 14 0",
  flag: "M5 21V4m0 0h11l-2 4 2 4H5",
  spark: "M12 3v4m0 10v4M3 12h4m10 0h4M6 6l2.5 2.5m7 7L18 18M6 18l2.5-2.5m7-7L18 6",
  close: "M6 6l12 12M18 6 6 18",
  more: "M6 12h.01M12 12h.01M18 12h.01",
  expand: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  book: "M12 6.5C10.3 5.2 7.8 4.5 4 4.5v14c3.8 0 6.3.7 8 2m0-14c1.7-1.3 4.2-2 8-2v14c-3.8 0-6.3.7-8 2m0-14v14",
  list: "M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01",
  dock: "M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zm11 0v14",
  retry: "M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v3.8h-3.8",
  wifi: "M2.5 9a14 14 0 0 1 19 0M5.5 12.5a9.5 9.5 0 0 1 13 0M8.8 16a4.8 4.8 0 0 1 6.4 0M12 19.5h.01",
  arrow: "M5 12h14m0 0-5-5m5 5-5 5",
};

export default function Icon({ name, size = 18, stroke = 1.7, className = "", title }) {
  return (
    <svg
      className={`icon ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title && <title>{title}</title>}
      <path d={P[name]} strokeWidth={name === "more" ? stroke * 1.6 : undefined} />
    </svg>
  );
}
