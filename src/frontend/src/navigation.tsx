import { useEffect, useRef } from "react";
import { Link, useBlocker, useSearchParams } from "react-router";

export function useOffset(): [number, (offset: number) => void] {
  const [params, setParams] = useSearchParams();
  const raw = Number(params.get("offset") || 0);
  const offset = Number.isSafeInteger(raw) && raw >= 0 ? raw : 0;
  return [offset, (value) => setParams((current) => {
    const next = new URLSearchParams(current);
    if (value > 0) next.set("offset", String(value)); else next.delete("offset");
    return next;
  })];
}

export function useUnsaved(dirty: boolean, watchSearch = false) {
  const unsaved = useRef(dirty); unsaved.current = dirty;
  const blocker = useBlocker(({ currentLocation, nextLocation }) => unsaved.current &&
    (currentLocation.pathname !== nextLocation.pathname || watchSearch && currentLocation.search !== nextLocation.search));
  useEffect(() => {
    if (blocker.state === "blocked") {
      if (window.confirm("Leave this page with unsaved changes or selected files?")) blocker.proceed();
      else blocker.reset();
    }
  }, [blocker]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
}

export function NotFound() {
  return <section><h1 className="text-xl font-semibold">Page not found</h1><Link to="/">Return to labs</Link></section>;
}
