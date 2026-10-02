/** Thin fetch wrapper. Errors carry `status` (0 when the server can't be reached) and the
 *  backend's human-readable `detail`, so screens can tell "server down" from "not allowed". */
async function req(path, opts = {}) {
  let r;
  try {
    r = await fetch(path, opts);
  } catch {
    const e = new Error("Can’t reach the server. Check that the app is still running.");
    e.status = 0;
    throw e;
  }
  const isJson = (r.headers.get("content-type") || "").includes("json");
  const body = isJson ? await r.json().catch(() => null) : await r.text();
  if (!r.ok) {
    const detail = body && typeof body.detail === "string" ? body.detail : null;
    const e = new Error(detail || `The server said no (error ${r.status}).`);
    e.status = r.status;
    throw e;
  }
  return body;
}
const post = (path, data) =>
  req(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data || {}) });

/** Name recorded in each report's history for actions taken from this dashboard. */
export const OFFICER = "officer";

const sid = (id) => `/api/submissions/${id}`;

export const api = {
  status: () => req("/api/status"),
  template: () => req("/api/template"),
  list: () => req("/api/submissions"),
  get: (id) => req(sid(id)),
  setField: (id, fid, value) => post(`${sid(id)}/fields/${encodeURIComponent(fid)}`, { value, officer: OFFICER }),
  override: (id, label, accept) => post(`${sid(id)}/overrides`, { label, accept, officer: OFFICER }),
  approve: (id, { force = false, reason = "", overwrite = false } = {}) => post(`${sid(id)}/approve`, { officer: OFFICER, force, reason, overwrite }),
  /** `reason` is a code from rejectReasons(); `note` is free text kept in the log, never sent to her. */
  reject: (id, reason, note = "") => post(`${sid(id)}/reject`, { officer: OFFICER, reason, note }),
  rejectReasons: () => req("/api/reject-reasons"),
  retry: (id) => post(`${sid(id)}/retry`),
  processNow: (id) => post(`${sid(id)}/process-now`),
  newGroup: (id) => post(`${sid(id)}/new-group`, { officer: OFFICER }),
  shgTabs: () => req("/api/shg-tabs"),
  groups: () => req("/api/groups"),
  samples: () => req("/api/sim/samples"),
  conversation: (sender) => req(`/api/sim/conversation?sender=${encodeURIComponent(sender)}`),
  send: (form) => req("/api/sim/message", { method: "POST", body: form }),
  reset: () => post("/api/demo/reset"),
};

export const cropUrl = (id, fid) => `${sid(id)}/crops/${encodeURIComponent(fid)}`;
export const pageUrl = (id, page) => `${sid(id)}/pages/${page}`;
export const sampleUrl = (name) => `/api/sim/samples/${name}`;
export const WORKBOOK_URL = "/api/workbook";

/** localStorage / sessionStorage that never throws (private windows, blocked storage). */
export const store = {
  get(key, fallback = null, session = false) {
    try {
      const v = (session ? sessionStorage : localStorage).getItem(key);
      return v === null ? fallback : JSON.parse(v);
    } catch {
      return fallback;
    }
  },
  set(key, value, session = false) {
    try {
      const s = session ? sessionStorage : localStorage;
      if (value === null || value === undefined) s.removeItem(key);
      else s.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable: the setting just won't be remembered */
    }
  },
};
