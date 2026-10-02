/** Which values the officer should look at, in which order, and what they probably should be. */

/** Statuses that mean a person has already looked at the value against the photo. */
export const CHECKED = ["officer_confirmed", "officer_corrected", "member_corrected"];
/** Statuses where the value differs from what was read: shown in green in the table. */
export const EDITED = ["officer_corrected", "member_corrected"];

export const errorsOf = (sub) => (sub?.validation?.issues || []).filter((i) => i.severity === "error");
export const issueKey = (i) => `${i.rule}|${(i.fields || []).join(",")}`;

const isOpen = (sub, f) => {
  const fv = sub?.record?.fields?.[f];
  return !!fv && !CHECKED.includes(fv.status);
};

/** How many failing checks each unchecked value takes part in. */
export function suspicion(sub) {
  const n = {};
  for (const i of errorsOf(sub)) for (const f of i.fields || []) if (isOpen(sub, f)) n[f] = (n[f] || 0) + 1;
  return n;
}

/**
 * Flagged values in review order. The backend's `validation.likely` ranking comes first
 * (a misread digit breaks several checks at once, so the value shared by the most failures
 * is the likeliest culprit); the rest follow by how many checks they're in, then form order.
 */
export function reviewOrder(sub) {
  const n = suspicion(sub);
  const likely = (sub?.validation?.likely || []).map((l) => l.field).filter((f) => n[f]);
  const formOrder = Object.keys(sub?.validation?.flagged || {});
  const rest = Object.keys(n)
    .filter((f) => !likely.includes(f))
    .sort((a, b) => n[b] - n[a] || formOrder.indexOf(a) - formOrder.indexOf(b));
  return [...new Set([...likely, ...rest])];
}

/** The value a field would need for its failing checks to balance, if they agree on one. */
export function suggestionFor(sub, fid) {
  const fv = sub?.record?.fields?.[fid];
  if (!fv) return null;
  const same = (v) => v !== null && v !== undefined && Number(v) === Number(fv.value);
  const l = (sub.validation?.likely || []).find((x) => x.field === fid);
  if (l && l.suggest !== null && l.suggest !== undefined) return same(l.suggest) ? null : { value: l.suggest, balances: l.balances || l.checks || 1 };
  if (l) return null; // the backend looked and found no value the checks agree on
  const mine = errorsOf(sub).filter((i) => (i.fields || []).includes(fid));
  const vals = mine.map((i) => i.suggest?.[fid]).filter((v) => v !== undefined && v !== null);
  if (!vals.length || new Set(vals.map(Number)).size > 1) return null;
  if (vals.length === 1 && mine.length > 1) return null;
  return same(vals[0]) ? null : { value: vals[0], balances: vals.length };
}

/** Sort issues so the ones involving the likeliest culprit come first. */
export function sortIssues(issues, order) {
  const pos = (i) => Math.min(...(i.fields || []).map((f) => (order.includes(f) ? order.indexOf(f) : 999)), 999);
  return [...issues].sort((a, b) => pos(a) - pos(b));
}
