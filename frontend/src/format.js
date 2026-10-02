export const PRODUCT = "SHG Reports · Palmera";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export const monthName = (ym, short = false) => {
  if (!ym) return "";
  const [y, m] = String(ym).split("-").map(Number);
  const n = MONTHS[m - 1] || "";
  return short ? n.slice(0, 3) : `${n} ${y}`;
};

export const money = (v) => (v === null || v === undefined || v === "" ? "—" : `Rs ${Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}`);
export const num = (v) => (v === null || v === undefined || v === "" ? "" : typeof v === "number" ? v.toLocaleString("en-US") : String(v));
/** Short money for chart axes: Rs 12k, Rs 950. */
export const moneyShort = (v) => (Math.abs(v) >= 1000 ? `Rs ${(v / 1000).toFixed(v % 1000 === 0 || Math.abs(v) >= 10000 ? 0 : 1)}k` : `Rs ${Math.round(v)}`);
export const pct = (v) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

export const display = (v, type) => {
  if (v === null || v === undefined || v === "") return "";
  if (type === "yesno" || typeof v === "boolean") return v ? "Yes" : "No";
  if (type === "month" && typeof v === "string") return monthName(v);
  if (typeof v === "number") return v.toLocaleString("en-US");
  return String(v);
};

/** Every status a report can be in, with the words officers see. */
export const STATUS = {
  collecting: { label: "Waiting for photos", tone: "grey" },
  needs_review: { label: "Needs review", tone: "orange" },
  awaiting_member: { label: "Waiting for member", tone: "blue" },
  written: { label: "Recorded", tone: "green" },
  failed: { label: "Couldn’t read", tone: "red" },
  superseded: { label: "Replaced", tone: "grey" },
  rejected: { label: "New photo asked", tone: "grey" },
};
export const statusOf = (s) => {
  if (s?.status === "needs_review" && s.errors === 0) return { label: "Ready to send", tone: "green" };
  return STATUS[s?.status] || STATUS.collecting;
};

/** "just now", "5 min ago" — lower case, so it reads inside a sentence. */
export const relTime = (iso) => {
  const d = new Date(iso);
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
};
export const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "");

export const LANGS = { en: "English", si: "සිංහල", ta: "தமிழ்" };

// Short row names for the weekly table (the printed labels are long)
export const SHORT = {
  meeting_held: "Meeting held",
  attendance: "Attended",
  inactive_members: "Inactive members",
  members_loans_overdue: "Overdue members",
  savings: "Savings",
  savings_to_date: "Savings to date",
  principal_repaid: "Principal repaid",
  interest_repaid: "Interest repaid",
  other_income: "Other income",
  loans_distributed: "Loans given",
  loan_purpose_income: "for income generation",
  loan_purpose_emergency: "for emergencies",
  loan_purpose_other: "for other purposes",
  savings_refunded: "Savings refunded",
  loans_outstanding: "Loans outstanding",
  write_offs: "Write-offs",
  other_expenses: "Other expenses",
  total_income: "Total income",
  total_loan: "Total loan",
  total_expenses: "Total expenses",
  expected_balance: "Expected balance",
  cash_in_hand: "Cash in hand",
  cash_deposited_bank: "Deposited in bank",
};

const HEADER_SHORT = {
  shg_name: "Group name",
  total_members: "Members",
  village_gn: "Village / GN",
  month_year: "Month",
  last_audit_date: "Last audit",
  graded_last_3_months: "Graded recently",
  monthly_interest: "Monthly interest",
  constitution_updated: "Constitution updated",
};

const PAGE2_SHORT = {
  high_cash_reason: "Reason for high cash",
  social_work: "Social work this month",
  members_with_goals: "Members with written goals",
  group_goal: "Group goal",
  govt_ngo_support: "Government or NGO support",
  signed_by_completer: "Completed by",
  signed_by_cluster_rep: "Cluster representative",
};
export const page2Short = (key, label) => PAGE2_SHORT[key] || label;

const MONTHLY_SHORT = {
  "Total number of meetings held": "Meetings held",
  "Number of SHG members": "Members",
  "Total attendance for the month": "Total attendance",
  "Number of people who are inactive – waiting to pay loans off and then leave, or to leave for another reason": "Inactive members",
  "Savings (Rs.)": "Savings",
  "Principal loan repayments (Rs.)": "Loan repayments",
  "Interest repayment (Rs.)": "Interest",
  "Other income (Membership fees, Other NGO funds, Fines, Social fund, Other) (Rs.)": "Other income",
  "Loans distributed (Rs.)": "Loans given",
  "Loan Purpose – Income generation (Rs.)": "for income generation",
  "Loan Purpose – Emergency (Rs.)": "for emergencies",
  "Loan Purpose – Other (Rs.)": "for other purposes",
  "Savings refunded (Rs.)": "Savings refunded",
  "Other expenses (Interest refunded, Community / members support, CLA fee, Admin expenses & other) (Rs.)": "Other expenses",
  "Loan right off (Rs.)": "Write-offs",
  "Cash in Hand – at end of month (mother book) (Rs.)": "Cash in hand at month end",
  "Number of members who attended the last meeting": "At the last meeting",
  "How many women have current goals for the month written in their individual booklets?": "Members with written goals",
};
export const shortMonthly = (l) => MONTHLY_SHORT[l] || String(l).replace(/\s*\(.*?\)/g, "").trim();
export const isMoneyLabel = (label) => /\(Rs\.\)/.test(label);

const COLS = { name: "name", amount_left: "amount left", months_overdue: "months overdue", last_meeting_attended: "last meeting", issue: "issue", support_from_cluster: "support asked" };

/** The short, human name of any field id, e.g. "Interest repaid, W3". */
export const fieldName = (fid, labels = {}) => {
  const p = fid.split(".");
  if (p[0] === "weekly") return `${SHORT[p[1]] || p[1]}, ${p[2] === "Total" ? "total" : p[2]}`;
  if (p[0] === "header") return HEADER_SHORT[p[1]] || (labels[fid] || p[1]).replace(/\s+/g, " ");
  if (p[0] === "page2" && p.length === 4)
    return `${p[1] === "overdue_members" ? "Overdue member" : "Issue"} ${Number(p[2]) + 1}, ${COLS[p[3]] || p[3].replace(/_/g, " ")}`;
  if (p[0] === "page2") return PAGE2_SHORT[p[1]] || labels[fid] || p[1];
  return shortMonthly(fid); // a monthly workbook label (member correction)
};

/** Split a field name into the row and the week, for two-line displays. */
export const fieldParts = (fid, labels) => {
  const p = fid.split(".");
  if (p[0] === "weekly") return { row: SHORT[p[1]] || p[1], col: p[2] === "Total" ? "Month total" : `Week ${p[2].slice(1)}` };
  return { row: fieldName(fid, labels), col: p[0] === "page2" ? "Page 2" : "Top of page 1" };
};

/** What kind of value a field holds, so the editor offers the right keyboard. */
export const fieldType = (fid, template, value) => {
  const p = fid.split(".");
  if (template) {
    if (p[0] === "weekly") return template.weekly.find((r) => r.key === p[1])?.type || "text";
    if (p[0] === "page2" && p.length === 2) return template.page2.find((f) => f.key === p[1])?.type || "text";
  }
  if (p[0] === "page2" && ["amount_left"].includes(p[3])) return "money";
  if (p[0] === "page2" && ["months_overdue"].includes(p[3])) return "int";
  if (fid === "header.total_members") return "int";
  if (fid === "header.month_year") return "month";
  if (typeof value === "boolean") return "yesno";
  if (typeof value === "number") return "money";
  return "text";
};
