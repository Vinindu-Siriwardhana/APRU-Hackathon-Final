import { useEffect, useState } from "react";

/** Hash routes: #/inbox/<filter>/<id>, #/groups/<name>, #/phone, #/guide/<tab>. */
const parse = () => (window.location.hash.replace(/^#\/?/, "") || "inbox/needs_review").split("/");

export function useHashRoute() {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export const go = (path) => (window.location.hash = `/${path}`);
