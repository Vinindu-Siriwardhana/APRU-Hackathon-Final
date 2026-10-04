import { useCallback, useEffect, useRef, useState } from "react";
import { api, sampleUrl, store } from "./api.js";
import { officerError } from "./format.js";

/**
 * The simulated member's phone. Its state lives at the top of the app (not inside the
 * Member's phone screen) and the conversation itself lives on the server, so the chat
 * survives navigation, a reload and presenter mode showing the same phone twice.
 * Only the sender id and language are kept in sessionStorage.
 */
const newSender = () => `sim:phone-${Math.random().toString(36).slice(2, 7)}`;
const POLL_MS = 1750;

export function usePhone({ onActivity, notify }) {
  const [sender, setSender] = useState(() => store.get("phone.sender", null, true));
  const [lang, setLangState] = useState(() => store.get("phone.lang", "en", true));
  const [convo, setConvo] = useState({ messages: [], latest: null });
  const [pending, setPending] = useState(null);
  const [sending, setSending] = useState(false);
  const [showEnglish, setShowEnglishState] = useState(() => store.get("phone.english", true));
  const [seen, setSeen] = useState(() => store.get("phone.seen", 0, true));
  const activity = useRef(onActivity);
  activity.current = onActivity;
  const lastCount = useRef(0);

  const load = useCallback(async (who = sender) => {
    if (!who) return;
    try {
      const c = await api.conversation(who);
      if (!c || !Array.isArray(c.messages)) return;
      setConvo({ messages: c.messages, latest: c.latest || null });
      if (c.lang && c.messages.length) setLangState(c.lang);
      // a new bot message (e.g. the summary after "Send to member"): refresh the inbox too
      if (c.messages.length !== lastCount.current) {
        lastCount.current = c.messages.length;
        activity.current?.();
      }
    } catch {
      /* the connection banner reports outages; keep what's on screen */
    }
  }, [sender]);

  useEffect(() => {
    if (!sender) return;
    load();
    const t = setInterval(() => !document.hidden && load(), POLL_MS);
    return () => clearInterval(t);
  }, [sender, load]);

  const setLang = (l) => {
    setLangState(l);
    store.set("phone.lang", l, true);
  };
  const setShowEnglish = (v) => {
    setShowEnglishState(v);
    store.set("phone.english", v);
  };

  const send = async ({ image, text }) => {
    if (sending) return;
    let who = sender;
    if (!who) {
      who = newSender();
      setSender(who);
      store.set("phone.sender", who, true);
      store.set("phone.lang", lang, true);
    }
    setPending(image ? { from: "me", image, at: new Date().toISOString() } : { from: "me", text, at: new Date().toISOString() });
    setSending(true);
    try {
      const form = new FormData();
      form.append("sender", who);
      form.append("lang", lang);
      if (image) {
        const blob = await (await fetch(sampleUrl(image))).blob();
        form.append("image", blob, image);
      } else form.append("text", text);
      await api.send(form);
      await load(who);
      activity.current?.();
    } catch (e) {
      notify?.(officerError(e.message), "red");
    } finally {
      setPending(null);
      setSending(false);
    }
  };

  /** Forget this phone's conversation and start over with a new member. */
  const reset = () => {
    setSender(null);
    setConvo({ messages: [], latest: null });
    setPending(null);
    lastCount.current = 0;
    setSeen(0);
    store.set("phone.sender", null, true);
    store.set("phone.seen", null, true);
  };

  const messages = pending ? [...convo.messages, pending] : convo.messages;
  const botCount = convo.messages.filter((m) => m.from === "bot").length;
  const markSeen = useCallback(() => {
    setSeen(botCount);
    store.set("phone.seen", botCount, true);
  }, [botCount]);

  return {
    sender, lang, setLang, messages, latest: convo.latest, sending, send, reset,
    started: convo.messages.length > 0 || !!pending,
    showEnglish, setShowEnglish,
    unread: Math.max(0, botCount - seen), markSeen,
  };
}
