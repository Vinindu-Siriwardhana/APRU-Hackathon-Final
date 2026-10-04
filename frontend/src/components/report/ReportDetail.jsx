import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, pageUrl } from "../../api.js";
import { fieldName, fieldType, monthName, officerError, relTime, statusOf } from "../../format.js";
import { go } from "../../route.js";
import Icon from "../Icon.jsx";
import Menu from "../Menu.jsx";
import PhotoViewer from "../PhotoViewer.jsx";
import { ForceSheet, NewGroupSheet, RejectSheet } from "./ActionSheets.jsx";
import Inspector from "./Inspector.jsx";
import IssueList from "./IssueList.jsx";
import { EDITED, errorsOf, reviewOrder, sortIssues, suggestionFor } from "./ranking.js";
import { Conversation, MonthlyList, PageTwo } from "./Sections.jsx";
import StatusCard from "./StatusCard.jsx";
import WeeklyTable, { hasW5 } from "./WeeklyTable.jsx";

/** Below this detail-pane width the photo and the figures stack in one column. */
const ONE_COLUMN = 860;
const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export default function ReportDetail({ id, filter, template, notify, refresh }) {
  const [sub, setSub] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [cleared, setCleared] = useState(null);
  const [sheet, setSheet] = useState(null);
  const [scrolled, setScrolled] = useState(false);
  const first = useRef(true);
  const inflight = useRef(0);
  const root = useRef(null);
  const head = useRef(null);
  const photo = useRef(null);
  const sendBtn = useRef(null);
  const subRef = useRef(null);
  subRef.current = sub;

  const opener = useRef(null);
  const select = useCallback((fid, opts = {}) => {
    const a = document.activeElement;
    if (fid && a && a !== document.body && !a.closest?.(".inspector")) opener.current = a;
    setSelected(fid);
    if (!fid) return;
    const box = subRef.current?.record?.fields?.[fid]?.box;
    if (box) setPage(box.page);
    const pane = root.current?.closest(".detail-pane");
    if (opts.scroll && pane && pane.clientWidth < ONE_COLUMN && photo.current) {
      photo.current.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
    }
  }, []);

  const load = useCallback(async () => {
    const started = inflight.current;
    try {
      const s = await api.get(id);
      if (inflight.current !== started) return; // an action finished meanwhile: its result is newer
      setSub(s);
      setLoadError(null);
      if (first.current && s.validation) {
        first.current = false;
        // a member's correction is decided from its card; otherwise open on the likeliest misreading
        const onlyMember = errorsOf(s).every((i) => i.rule === "member_correction");
        if (s.status === "needs_review" && !onlyMember) {
          const f = reviewOrder(s)[0];
          if (f) {
            setSelected(f);
            const box = s.record?.fields?.[f]?.box;
            if (box) setPage(box.page);
          }
        }
      }
    } catch (e) {
      // a failed poll never replaces a loaded report; the app-wide banner says we're retrying
      setSub((cur) => {
        if (!cur) setLoadError(e);
        return cur;
      });
    }
  }, [id]);

  useEffect(() => {
    // while an action runs, its own result is what we show: no poll in between
    if (!busy) load();
    const t = setInterval(() => !document.hidden && !busy && load(), 3000);
    return () => clearInterval(t);
  }, [load, busy]);

  // sticky offsets: the header's height and the scrolling pane's height, as CSS variables
  useLayoutEffect(() => {
    const el = root.current;
    const pane = el?.closest(".detail-pane");
    if (!el || !pane) return;
    const set = () => {
      el.style.setProperty("--head-h", `${head.current?.offsetHeight || 0}px`);
      el.style.setProperty("--pane-h", `${pane.clientHeight}px`);
    };
    set();
    const ro = new ResizeObserver(set);
    ro.observe(pane);
    if (head.current) ro.observe(head.current);
    const onScroll = () => setScrolled(pane.scrollTop > 4);
    pane.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      ro.disconnect();
      pane.removeEventListener("scroll", onScroll);
    };
  }, [!!sub]);

  useEffect(() => {
    if (!cleared) return;
    const t = setTimeout(() => setCleared(null), 4200);
    return () => clearTimeout(t);
  }, [cleared]);

  const act = async (fn, ok) => {
    setBusy(true);
    inflight.current += 1;
    try {
      const r = await fn();
      const next = r?.submission || (r?.record || r?.status ? r : null);
      if (next?.id) setSub(next);
      else await load();
      if (ok) notify(ok, "green");
      refresh();
      return next || r || true;
    } catch (e) {
      notify(officerError(e.message), "red");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const saveField = async (fid, value) => {
    const before = errorsOf(sub).length;
    const r = await act(() => api.setField(id, fid, value));
    if (!r?.validation) return;
    const after = errorsOf(r).length;
    if (after < before) setCleared({ n: before - after, at: Date.now() });
    subRef.current = r;
    const next = reviewOrder(r).find((f) => f !== fid);
    if (next && r.status === "needs_review") select(next);
    else {
      setSelected(null);
      if (!after) setTimeout(() => sendBtn.current?.focus(), 50);
    }
  };

  // If she already said OK (and only the workbook write failed, e.g. Excel had the file open),
  // approving writes straight to the workbook instead of sending the summary again.
  const confirmed = !!sub?.member_confirmed;
  const send = async (opts) => {
    const r = await act(() => api.approve(id, opts), null);
    setSheet(null);
    if (!r) return;
    const now = r.status || "awaiting_member";
    if (now === "written") notify("Written to the workbook. Her receipt is on its way", "green");
    else if (now === "awaiting_member") notify("Sent to the member on WhatsApp", "green");
    else notify("The workbook still couldn't be written: see the message in the report", "red");
    go(`inbox/${now}/${id}`);
    // the header's own buttons change: put focus on the report title so the next Tab is in the report
    setTimeout(() => document.getElementById("report-title")?.focus({ preventScroll: true }), 80);
  };

  const [reading, setReading] = useState(false);
  const readNow = async () => {
    setReading(true);
    const r = await act(() => api.processNow(id), null);
    setReading(false);
    if (r?.status === "needs_review") go(`inbox/needs_review/${id}`);
    else if (r?.status) go(`inbox/${r.status}/${id}`);
  };
  const resend = async () => {
    const r = await act(() => api.resend(id), null);
    if (!r) return;
    if (r.failed) notify(officerError(r.delivery_error || "WhatsApp still couldn’t deliver it. Try again later."), "red");
    else notify(r.resent === 1 ? "Message delivered" : `${r.resent} messages delivered`, "green");
  };
  const menuButton = () => root.current?.querySelector(".detail-actions .menu > button") || document.getElementById("report-title");

  // Closing the inspector puts focus back on the value's own cell (or the chip that opened it),
  // so the next Tab continues where the officer was instead of restarting at the sidebar.
  const close = useCallback(() => {
    const fid = selected;
    const had = root.current?.querySelector(".inspector")?.contains(document.activeElement);
    setSelected(null);
    if (!fid || (!had && document.activeElement !== document.body)) return;
    requestAnimationFrame(() => {
      const cells = [...(root.current?.querySelectorAll(`[data-fid="${CSS.escape(fid)}"]`) || [])];
      const cell = cells.find((c) => c === opener.current) || cells[0];
      (cell || head.current?.querySelector("h1"))?.focus();
    });
  }, [selected]);

  // keyboard: Esc closes the inspector; Alt+↓ / Alt+↑ (also J / K outside a text field) move
  // between flagged values. Alt works while typing in the value field, where a letter would not.
  const order = sub ? reviewOrder(sub) : [];
  const flaggedList = sub?.status === "needs_review" ? [...new Set([...order, ...Object.keys(sub.validation?.flagged || {})])].filter((f) => sub.record?.fields?.[f]) : [];
  useEffect(() => {
    const move = (d) => {
      const i = flaggedList.indexOf(selected);
      const n = d > 0 ? (i + 1) % flaggedList.length : (i <= 0 ? flaggedList.length - 1 : i - 1);
      select(flaggedList[n], { scroll: true });
    };
    const onKey = (e) => {
      if (document.querySelector("dialog[open]") || e.metaKey || e.ctrlKey) return;
      if (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowUp") && flaggedList.length) {
        e.preventDefault();
        move(e.key === "ArrowDown" ? 1 : -1);
        return;
      }
      if (e.altKey) return;
      if (e.key === "Escape" && selected) {
        e.preventDefault();
        close();
        return;
      }
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      const k = e.key.toLowerCase();
      if ((k === "j" || k === "k") && flaggedList.length) {
        e.preventDefault();
        move(k === "j" ? 1 : -1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, flaggedList.join(","), select, close]);

  if (!sub) {
    if (loadError) {
      const gone = loadError.status === 404;
      return (
        <div className="empty empty-detail" role="alert">
          <Icon name={gone ? "tray" : "warn"} size={36} stroke={1.3} />
          <h2>{gone ? "This report isn’t here any more" : "Couldn’t open this report"}</h2>
          <p>{gone ? "It may have been cleared when the demo restarted." : loadError.message}</p>
          {gone ? <a className="btn btn-quiet" href={`#/inbox/${filter}`}>Back to the list</a> : <button className="btn btn-quiet" onClick={load}>Try again</button>}
        </div>
      );
    }
    return <DetailSkeleton />;
  }

  const fields = sub.record?.fields || {};
  const issues = sub.validation?.issues || [];
  const errors = sortIssues(issues.filter((i) => i.severity === "error"), order);
  // a failed workbook write is shown as an issue but is retried by approving again, so it doesn't block the button
  const blocking = errors.filter((i) => i.rule !== "write_failed");
  const notes = issues.filter((i) => i.severity !== "error");
  const flagged = sub.validation?.flagged || {};
  const st = statusOf({ status: sub.status, errors: errors.length });
  const name = fields["header.shg_name"]?.value || "New report";
  const month = fields["header.month_year"]?.value;
  const gn = fields["header.village_gn"]?.value;
  const review = sub.status === "needs_review";
  const pages = Object.keys(sub.pages || {}).map(Number).sort();
  const fv = selected ? fields[selected] : null;
  const onlyPage1 = sub.actions ? !!sub.actions.process_now : sub.status === "collecting" && sub.pages?.[1] && !sub.pages?.[2];
  const showW5 = hasW5(fields);
  const open = ["needs_review", "awaiting_member", "written"].includes(sub.status);
  const recorded = errors.some((i) => i.rule === "month_already_recorded");
  const can = (k, fallback) => (sub.actions && k in sub.actions ? !!sub.actions[k] : fallback);

  // "Send anyway" can't bypass these: each needs its own decision (the server refuses with 409)
  const NO_FORCE = {
    unknown_shg: "Decide first whether this is a new group.",
    opening_inconsistent: "Enter the group’s totals from the mother book first.",
    month_out_of_range: "The month doesn’t fit the workbook: correct the month first.",
    month_unexpected: "Check the month on the photo first: keep it as written or correct it.",
  };
  const forceBlock = errors.map((i) => NO_FORCE[i.rule]).find(Boolean);
  const failedNoRetry = sub.status === "failed" && !can("retry", true);
  const menu = [
    review && can("approve", true) && errors.length > 0 && { label: "Send anyway…", icon: "send", disabled: !!forceBlock, note: forceBlock, onClick: () => setSheet("force") },
    !failedNoRetry && can("reject", ["needs_review", "collecting", "failed"].includes(sub.status)) && { label: "Ask for a new photo…", icon: "photo", onClick: () => setSheet("reject") },
    can("opening", false) && { label: "Change its opening totals…", icon: "book", onClick: () => setSheet("newgroup-book") },
  ];
  const monthLabel = month ? monthName(month) : null;

  return (
    <article className="detail" ref={root}>
      <header className={`detail-head ${scrolled ? "is-scrolled" : ""}`} ref={head}>
        <a className="back" href={`#/inbox/${filter}`} aria-label="Back to the list" title="Back to the list">
          <Icon name="back" size={22} />
        </a>
        <div className="detail-titles">
          <h1 className="detail-title" id="report-title" tabIndex={-1}>{name}</h1>
          <p className="detail-sub">
            {[month && monthName(month), gn].filter(Boolean).join(", ") || `Received ${relTime(sub.created)}`}
          </p>
        </div>
        <div className="detail-actions">
          <span className={`tag tone-${st.tone}`}>{st.label}</span>
          {review && (
            <button ref={sendBtn} className="btn btn-primary" disabled={busy || blocking.length > 0} onClick={() => send()}
              title={blocking.length ? "Resolve the checks first, or use Send anyway"
                : confirmed ? "She already confirmed: write this month to the workbook" : "Send the summary to the member on WhatsApp"}>
              <Icon name={confirmed ? "download" : "send"} size={15} stroke={2.2} /> {confirmed ? "Write to workbook" : "Send to member"}
            </button>
          )}
          {onlyPage1 && (
            <button className="btn btn-primary" disabled={busy} aria-busy={reading || undefined} onClick={readNow}
              title="Page 2 hasn’t come: read page 1 on its own">
              {reading ? <><span className="spinner" aria-hidden /> Reading page 1…</> : "Read page 1 now"}
            </button>
          )}
          {sub.status === "failed" && (failedNoRetry
            ? <button className="btn btn-primary" disabled={busy} onClick={() => setSheet("reject-unclear")}><Icon name="photo" size={15} /> Ask for a new photo</button>
            : can("retry", true) && <button className="btn btn-primary" disabled={busy} aria-busy={busy || undefined} onClick={() => act(() => api.retry(id), "Reading the photos again")}>
                {busy ? <><span className="spinner" aria-hidden /> Reading…</> : "Try again"}
              </button>)}
          <Menu items={menu} />
        </div>
      </header>

      <div className="detail-grid">
        <div className="photo-col" ref={photo}>
          <PhotoViewer
            pages={pages}
            page={page}
            onPage={setPage}
            src={(p) => pageUrl(id, p)}
            box={fv?.box?.page === page ? fv.box : null}
            label={selected ? fieldName(selected, sub.labels) : null}
            onClear={close}
          />
        </div>

        <div className="info-col">
          <StatusCard sub={sub} errors={errors} cleared={cleared} reading={reading} />
          {sub.undelivered > 0 && (
            <div className="statusline tone-red delivery-line" role="status">
              <span>
                <Icon name="warn" size={14} /> {sub.undelivered === 1 ? "One WhatsApp message wasn’t delivered" : `${sub.undelivered} WhatsApp messages weren’t delivered`}
                {undeliveredWhy(sub.log) ? `: ${undeliveredWhy(sub.log)}` : "."}
              </span>
              {can("resend", true) && <button className="btn btn-small btn-primary" disabled={busy} onClick={resend}>Resend</button>}
            </div>
          )}
          {sub.record && <Impact sub={sub} errors={errors} />}

          {fv && (
            <Inspector
              key={selected}
              sid={id}
              fid={selected}
              fv={fv}
              type={fieldType(selected, template, fv.value)}
              labels={sub.labels}
              issues={issues.filter((i) => (i.fields || []).includes(selected))}
              suggestion={review ? suggestionFor(sub, selected) : null}
              reportStatus={sub.status}
              editable={review}
              busy={busy}
              canNav={flaggedList.length > 1}
              onSave={(v) => saveField(selected, v)}
              onClose={close}
            />
          )}

          {open && <IssueList sid={id} sub={sub} errors={errors} notes={notes} order={order} selected={selected} onSelect={select} act={act} showW5={showW5}
            onNewGroup={(mode) => setSheet(mode === "book" ? "newgroup-book" : "newgroup-start")} />}

          {sub.monthly && template && ["needs_review", "awaiting_member"].includes(sub.status) && (
            <MonthlyList template={template} sub={sub} flagged={flagged} selected={selected} onSelect={select} />
          )}

          {template && sub.record && (
            <section className="group" aria-labelledby="weekly-h">
              <h2 className="group-title" id="weekly-h">Weekly figures on the form</h2>
              <WeeklyTable template={template} fields={fields} flagged={flagged} selected={selected} onSelect={select} review={review} />
            </section>
          )}

          {template && sub.record && <PageTwo template={template} fields={fields} flagged={flagged} selected={selected} onSelect={select} review={review} />}

          <Conversation sid={id} log={sub.log} lang={sub.lang} onResend={can("resend", true) ? resend : null} busy={busy} />
        </div>
      </div>

      <ForceSheet open={sheet === "force"} onClose={() => setSheet(null)} errors={errors.length} busy={busy} recorded={recorded} returnFocus={menuButton}
        onConfirm={(reason) => send({ force: true, reason, overwrite: recorded })} />
      <RejectSheet open={sheet === "reject" || sheet === "reject-unclear"} initialCode={sheet === "reject-unclear" ? "unclear" : ""} onClose={() => setSheet(null)} busy={busy} returnFocus={menuButton}
        onConfirm={async (code, note) => {
          const r = await act(() => api.reject(id, code, note), "Asked her for a new photo");
          if (r) {
            setSheet(null);
            setTimeout(() => document.getElementById("report-title")?.focus({ preventScroll: true }), 80);
          }
        }} />
      <NewGroupSheet open={sheet === "newgroup-start" || sheet === "newgroup-book"} initialMode={sheet === "newgroup-book" ? "book" : "start"}
        onClose={() => setSheet(null)} busy={busy} returnFocus={menuButton}
        rows={template?.opening_rows} suggestion={sub.opening_suggestion} current={sub.opening} name={name !== "New report" ? name : null} monthLabel={monthLabel}
        onConfirm={async (choice) => {
          const r = await act(() => api.newGroup(id, choice), choice.startedThisMonth ? "Saved: the group started this month" : "Saved: its totals from the mother book");
          if (r) setSheet(null);
        }} />
    </article>
  );
}

/** Why WhatsApp refused the newest undelivered message, in the backend's officer wording. */
function undeliveredWhy(log) {
  const m = [...(log || [])].reverse().find((e) => e.from === "bot" && e.delivered === false);
  return m?.delivery_error ? String(m.delivery_error).replace(/\.$/, "") + "." : null;
}

/** What the system did on this report, in one line: the impact, visible. */
function Impact({ sub, errors }) {
  const fields = Object.values(sub.record?.fields || {});
  const read = fields.filter((f) => f.value !== null && f.value !== undefined && f.value !== "").length;
  // a mistake caught = a value someone changed, or where the two readings disagreed and a person settled it
  const disagreed = (passes) => (passes?.length > 1 && new Set(passes.map(String)).size > 1);
  const caught = fields.filter((f) => EDITED.includes(f.status) || disagreed(f.passes) ||
    (f.history || []).some((h) => h.event === "officer" && (String(h.old) !== String(h.new) || disagreed(h.readings)))).length;
  const parts = [`${read} values read`];
  if (!["needs_review", "awaiting_member", "written"].includes(sub.status)) return <p className="impact"><Icon name="spark" size={14} /><span>{parts[0]}</span></p>;
  if (sub.status === "needs_review" && errors.length) parts.push(`${errors.length} ${errors.length === 1 ? "check" : "checks"} to resolve`);
  else parts.push(`${caught} reading ${caught === 1 ? "mistake" : "mistakes"} caught before the workbook`);
  if (sub.status === "written" && sub.write_report) parts.push(`${sub.write_report.writes.length} workbook cells filled`);
  else if (sub.status === "awaiting_member") parts.push("written to the workbook when she says OK");
  return (
    <p className="impact">
      <Icon name="spark" size={14} />
      <span>{parts.join(" · ")}</span>
    </p>
  );
}

function DetailSkeleton() {
  return (
    <div className="detail skeleton" aria-busy="true" aria-label="Loading the report">
      <div className="sk sk-title" />
      <div className="sk sk-sub" />
      <div className="detail-grid">
        <div className="sk sk-photo" />
        <div className="info-col">
          <div className="sk sk-line" />
          <div className="sk sk-card" />
          <div className="sk sk-card short" />
        </div>
      </div>
    </div>
  );
}
