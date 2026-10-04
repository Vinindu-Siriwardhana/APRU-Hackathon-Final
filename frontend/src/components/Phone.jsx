import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, sampleUrl } from "../api.js";
import { LANGS, STATUS, clock, monthName } from "../format.js";
import Icon from "./Icon.jsx";

const BAD = {
  bad_blurry: "Blurry", bad_dark: "Too dark", bad_shadow: "Shadow", bad_cropped: "Cut off",
  bad_glare: "Glare", bad_steep_angle: "Steep angle",
};

const describe = (name) => {
  const m = name.match(/^(.*?)(?:_scan)?_p(\d)\.(?:jpg|png)$/);
  if (!m) return { title: name, sub: "" };
  const [, base, page] = m;
  if (BAD[base]) return { title: BAD[base], sub: `Page ${page}`, bad: true };
  const [group, month] = base.split("_");
  return { title: group[0].toUpperCase() + group.slice(1), sub: `${monthName(month, true)}, page ${page}` };
};

/** Quick replies a member would type. The label explains the cryptic one. */
const QUICK = [
  { label: "OK", text: "OK" },
  { label: "Correct item 5 → 12000", text: "5 12000" },
];

/** The WhatsApp chat on a phone. Used on Member's phone and docked beside the officer view. */
export function PhoneDevice({ phone, docked = false }) {
  const scroller = useRef(null);
  const [text, setText] = useState("");
  const { messages, sending, lang, showEnglish } = phone;

  useLayoutEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, sending]);

  // images load after the bubble is laid out: keep the newest message in view
  const keepBottom = () => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  return (
    <div className={`phone ${docked ? "is-docked" : ""}`}>
      <div className="phone-screen">
        <div className="phone-island" aria-hidden />
        <header className="chat-head">
          <div className="chat-avatar" aria-hidden><Icon name="checkmark" size={14} stroke={2.4} /></div>
          <div className="chat-who">
            <div className="chat-name">Palmera SHG Reports</div>
            <div className="chat-sub">{sending ? "typing…" : "Business account"}</div>
          </div>
          <span className="chat-lang" title="The member’s language">{LANGS[lang]}</span>
        </header>
        <div className="chat" ref={scroller} role="log" aria-live="polite" aria-label="WhatsApp conversation">
          {messages.length === 0 && (
            <p className="chat-hint">
              {docked ? "No conversation yet. Send a form photo from Member’s phone." : "Pick a form photo to send it from this phone."}
            </p>
          )}
          {messages.map((m, i) => (
            <Bubble key={`${m.at}-${i}`} m={m} lang={lang} showEnglish={showEnglish} onImage={keepBottom} />
          ))}
          {sending && (
            <div className="msg is-bot is-typing" role="status" aria-label="The bot is typing">
              <i /><i /><i />
            </div>
          )}
        </div>
        <div className="quick" role="group" aria-label="Quick replies">
          {QUICK.map((q) => {
            // OK and "5 12000" only mean something while she has a summary to confirm
            const live = phone.latest?.status === "awaiting_member";
            return (
              <button key={q.text} onClick={() => phone.send({ text: q.text })} disabled={sending || !live}
                title={live ? `Sends “${q.text}”` : "For when she has a summary to confirm"}>
                {q.label}
              </button>
            );
          })}
        </div>
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) {
              phone.send({ text: text.trim() });
              setText("");
            }
          }}
        >
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Message" aria-label="Message to send" />
          <button aria-label="Send message" disabled={!text.trim() || sending}><Icon name="send" size={16} stroke={2.2} /></button>
        </form>
      </div>
    </div>
  );
}

function Bubble({ m, lang, showEnglish, onImage }) {
  const mine = m.from === "me" || m.from === "member";
  const img = typeof m.image === "string" && m.image ? sampleUrl(m.image) : null;
  const english = showEnglish && m.text_en && lang !== "en" && m.text_en !== m.text;
  return (
    <div className={`msg ${mine ? "is-me" : "is-bot"} ${img ? "has-image" : ""}`}>
      {img ? (
        <img src={img} alt={`Form photo: ${describe(m.image).title}, ${describe(m.image).sub}`} onLoad={onImage} />
      ) : m.image ? (
        <span className="msg-photo"><Icon name="photo" size={15} /> Photo</span>
      ) : (
        <span className="msg-text" lang={lang && lang !== "en" && (!mine || /[^\x00-\x7F]/.test(m.text || "")) ? lang : "en"}>{m.text}</span>
      )}
      {english && <span className="msg-en" lang="en">{m.text_en}</span>}
      <span className="msg-time">{clock(m.at)}</span>
    </div>
  );
}

/** The demo's Member's phone screen: the phone, plus the photos a member could send. */
export default function PhonePage({ phone, guide = null }) {
  const [samples, setSamples] = useState([]);
  const stage = useRef(null);
  // on a narrow screen the photos sit below the phone: bring the chat back into view to see the reply
  const sendPhoto = (s) => {
    phone.send({ image: s });
    const top = stage.current?.getBoundingClientRect().top;
    if (window.matchMedia?.("(max-width: 980px)").matches && top < 0) stage.current.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  useEffect(() => {
    api.samples().then(setSamples).catch(() => {});
  }, []);
  useEffect(() => phone.markSeen(), [phone.messages.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const good = samples.filter((s) => !s.startsWith("bad_") && !s.includes("_scan_"));
  const bad = samples.filter((s) => s.startsWith("bad_"));
  const latest = phone.latest;
  const st = latest && STATUS[latest.status];

  const tray = (list, label) => (
    <div className="tray" role="list" aria-label={label}>
      {list.map((s) => {
        const d = describe(s);
        return (
          <div key={s} role="listitem" className="thumb-item">
            <button className={`thumb ${d.bad ? "is-bad" : ""}`} onClick={() => sendPhoto(s)} disabled={phone.sending}
              aria-label={`Send photo: ${d.title}${d.sub ? `, ${d.sub}` : ""}`}>
              <img src={sampleUrl(s)} alt="" loading="lazy" />
              <span className="thumb-title">{d.title}</span>
              {d.sub && <span className="thumb-sub">{d.sub}</span>}
            </button>
          </div>
        );
      })}
    </div>
  );

  return (
    <div className="phone-view">
      <section className="phone-side">
        <header className="phone-head">
          <h1 className="pane-title">Member’s phone</h1>
          <p className="pane-sub">What an SHG member sees on WhatsApp: she sends the photos, then confirms the numbers.</p>
        </header>
        {guide && <div className="side-block side-guide">{guide}</div>}

        <div className="side-block side-lang">
          <h2 className="side-heading" id="lang-h">Her language</h2>
          <div className="segmented" role="radiogroup" aria-labelledby="lang-h">
            {Object.entries(LANGS).map(([k, v]) => (
              <button key={k} role="radio" aria-checked={phone.lang === k} className={phone.lang === k ? "is-on" : ""}
                onClick={() => phone.setLang(k)} disabled={phone.started}>
                {v}
              </button>
            ))}
          </div>
          <p className="muted small">
            {phone.started ? "The conversation keeps its language. Start a new conversation to change it." : "Choose it before the first photo."}
          </p>
          <label className="switch">
            <input type="checkbox" checked={phone.showEnglish} onChange={(e) => phone.setShowEnglish(e.target.checked)} />
            <span className="switch-track" aria-hidden />
            Show English under her messages
          </label>
        </div>

        <div className="side-block">
          <h2 className="side-heading">Send a form photo</h2>
          {tray(good, "Form photos")}
          <h2 className="side-heading">Or a photo with a problem</h2>
          <p className="muted small">The bot asks for a retake and says why.</p>
          {tray(bad, "Photos with a problem")}
        </div>

        <div className="side-foot">
          {latest && st && (
            <p className={`statusline tone-${st.tone}`}>
              This report is now “{st.label}”. <a href={`#/inbox/all/${latest.id}`}>Open it</a>
            </p>
          )}
          <button className="btn btn-quiet" onClick={phone.reset} disabled={!phone.started || phone.sending}>
            New conversation
          </button>
        </div>
      </section>

      <section className="phone-stage" aria-label="Simulated phone" ref={stage}>
        <PhoneDevice phone={phone} />
      </section>
    </div>
  );
}
