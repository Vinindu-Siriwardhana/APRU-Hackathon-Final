import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, pageUrl } from "../../api.js";
import { fieldName, fieldType, monthName, relTime, statusOf } from "../../format.js";
import { go } from "../../route.js";
import Icon from "../Icon.jsx";
import Menu from "../Menu.jsx";
import PhotoViewer from "../PhotoViewer.jsx";
import { ForceSheet, RejectSheet } from "./ActionSheets.jsx";
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

  const select = useCallback((fid, opts = {}) => {
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
    load();
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
      notify(e.message, "red");
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
  };

  // keyboard: Esc closes the inspector, J / K move between flagged values
  const order = sub ? reviewOrder(sub) : [];
  const flaggedList = sub?.status === "needs_review" ? [...new Set([...order, ...Object.keys(sub.validation?.flagged || {})])].filter((f) => sub.record?.fields?.[f]) : [];
  useEffect(() => {
    const onKey = (e) => {
      if (document.querySelector("dialog[open]") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "Escape" && selected) {
        setSelected(null);
        return;
      }
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      const k = e.key.toLowerCase();
      if ((k === "j" || k === "k") && flaggedList.length) {
        e.preventDefault();
        const i = flaggedList.indexOf(selected);
        const n = k === "j" ? (i + 1) % flaggedList.length : (i <= 0 ? flaggedList.length - 1 : i - 1);
        select(flaggedList[n], { scroll: true });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, flaggedList.join(","), select]);

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

  const menu = [
    review && can("approve", true) && errors.length > 0 && { label: "Send anyway…", icon: "send", onClick: () => setSheet("force") },
    can("reject", ["needs_review", "collecting", "failed"].includes(sub.status)) && { label: "Ask for a new photo…", icon: "photo", onClick: () => setSheet("reject") },
  ];

  return (
    <article className="detail" ref={root}>
      <header className={`detail-head ${scrolled ? "is-scrolled" : ""}`} ref={head}>
        <a className="back" href={`#/inbox/${filter}`} aria-label="Back to the list" title="Back to the list">
          <Icon name="back" size={22} />
        </a>
        <div className="detail-titles">
          <h1 className="detail-title">{name}</h1>
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
            <button className="btn btn-primary" disabled={busy} onClick={async () => {
              const r = await act(() => api.processNow(id), "Reading page 1");
              if (r?.status === "needs_review") go(`inbox/needs_review/${id}`);
            }}>
              Read page 1 now
            </button>
          )}
          {can("retry", sub.status === "failed") && (
            <button className="btn btn-primary" disabled={busy} onClick={() => act(() => api.retry(id), "Reading the photos again")}>Try again</button>
          )}
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
            onClear={() => setSelected(null)}
          />
        </div>

        <div className="info-col">
          <StatusCard sub={sub} errors={errors} cleared={cleared} busy={busy} onRetry={() => act(() => api.retry(id), "Reading the photos again")} />
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
              onSave={(v) => saveField(selected, v)}
              onClose={() => setSelected(null)}
            />
          )}

          {open && <IssueList sid={id} sub={sub} errors={errors} notes={notes} order={order} selected={selected} onSelect={select} act={act} showW5={showW5} />}

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

          <Conversation sid={id} log={sub.log} lang={sub.lang} />
        </div>
      </div>

      <ForceSheet open={sheet === "force"} onClose={() => setSheet(null)} errors={errors.length} busy={busy} recorded={recorded}
        onConfirm={(reason) => send({ force: true, reason, overwrite: recorded })} />
      <RejectSheet open={sheet === "reject"} onClose={() => setSheet(null)} busy={busy}
        onConfirm={async (code, note) => {
          const r = await act(() => api.reject(id, code, note), "Asked her for a new photo");
          if (r) setSheet(null);
        }} />
    </article>
  );
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
