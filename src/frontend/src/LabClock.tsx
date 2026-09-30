import { useEffect, useRef, useState } from "react";

export function localDate(value: string | null, minutes = 0): string {
  const date = value ? new Date(value) : new Date(Date.now() + minutes * 60000);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export default function LabClock({ serverTime, start, end, refresh }: {
  serverTime: string; start: string | null; end: string | null; refresh: () => void;
}) {
  const [now, setNow] = useState(Date.parse(serverTime));
  const onRefresh = useRef(refresh);
  onRefresh.current = refresh;
  useEffect(() => {
    const anchor = performance.now(), timestamp = Date.parse(serverTime);
    let previous = start && timestamp < Date.parse(start) ? "scheduled" : end && timestamp < Date.parse(end) ? "running" : "ended";
    const tick = () => {
      const value = timestamp + performance.now() - anchor;
      setNow(value);
      const state = start && value < Date.parse(start) ? "scheduled" : end && value < Date.parse(end) ? "running" : "ended";
      if (state !== previous) { previous = state; onRefresh.current(); }
    };
    tick();
    const timer = setInterval(tick, 1000);
    const visible = () => { if (document.visibilityState === "visible") onRefresh.current(); };
    document.addEventListener("visibilitychange", visible);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", visible); };
  }, [serverTime, start, end]);
  if (!start || !end) return <p>Draft — not scheduled.</p>;
  if (now >= Date.parse(end)) return <p role="timer">Lab ended.</p>;
  const before = now < Date.parse(start);
  const remaining = Math.max(0, Math.ceil((Date.parse(before ? start : end) - now) / 1000));
  return <p role="timer">{before ? "Starts in" : "Time remaining"}: {Math.floor(remaining / 3600)}:
    {String(Math.floor(remaining / 60) % 60).padStart(2, "0")}:{String(remaining % 60).padStart(2, "0")}</p>;
}
