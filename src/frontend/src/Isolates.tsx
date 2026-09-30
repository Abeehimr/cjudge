import { useEffect, useRef, useState } from "react";
import { api } from "./api";

export function useAdminEvents(refresh: () => Promise<void>) {
  const callback = useRef(refresh); callback.current = refresh;
  const [connection, setConnection] = useState("");
  useEffect(() => {
    let source: EventSource, timer: ReturnType<typeof setTimeout> | undefined, stopped = false, busy = false, again = false;
    async function load() {
      if (busy) { again = true; return; }
      busy = true;
      try { do { again = false; if (!stopped) await callback.current(); } while (again && !stopped); }
      finally { busy = false; }
    }
    function connect() {
      source = new EventSource("/api/admin/isolates/events");
      source.onopen = () => setConnection("Live updates connected");
      source.onerror = () => setConnection("Updates reconnecting…");
      source.addEventListener("refresh", () => { void load(); });
      source.addEventListener("denied", () => { stopped = true; source.close(); setConnection("Login expired. Sign in again."); window.dispatchEvent(new Event("cjudge-session-expired")); });
      source.addEventListener("reconnect", () => { source.close(); setConnection("Updates reconnecting…"); timer = setTimeout(connect, 3000); });
    }
    connect();
    return () => { stopped = true; source.close(); if (timer) clearTimeout(timer); };
  }, []);
  return connection;
}

type Worker = { slot: number; state: string; healthy: boolean; heartbeat_at: string | null; started_at: string | null;
  lease_until: string | null; submission_id: string | null; completed: number; fault: string | null };
type Snapshot = { configured: number; healthy: number; working: number; server_time: string; workers: Worker[] };

export default function Isolates() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null), [error, setError] = useState("");
  async function refresh() {
    try { setSnapshot(await api<Snapshot>("/admin/isolates")); setError(""); }
    catch (e) { setError((e as Error).message); }
  }
  const connection = useAdminEvents(refresh);
  useEffect(() => { void refresh(); }, []);
  useEffect(() => {
    if (!snapshot) return;
    const serverTime = Date.parse(snapshot.server_time), started = performance.now();
    const deadlines = snapshot.workers.filter((row) => row.state !== "Offline").map((row) => {
      const heartbeat = row.heartbeat_at ? Date.parse(row.heartbeat_at) + 90000 : serverTime;
      return row.state === "Judging" && row.lease_until ? Math.min(heartbeat, Date.parse(row.lease_until)) : heartbeat;
    });
    if (!deadlines.length) return;
    const timer = setTimeout(() => {
      const now = serverTime + performance.now() - started;
      setSnapshot((old) => old !== snapshot ? old : { ...snapshot, server_time: new Date(now).toISOString(), workers: snapshot.workers.map((row) => {
        if (row.heartbeat_at && (Date.parse(row.heartbeat_at) + 90000 <= now ||
            row.state === "Judging" && row.lease_until && Date.parse(row.lease_until) <= now))
          return { ...row, state: "Offline", healthy: false, submission_id: null };
        return row;
      }) });
    }, Math.max(0, Math.min(...deadlines) - serverTime) + 20);
    return () => clearTimeout(timer);
  }, [snapshot]);
  return <section className="space-y-3 rounded border bg-white p-4">
    <h1 className="text-xl font-semibold">Isolates</h1>
    <p>{connection}</p><button onClick={() => { void refresh(); }}>Refresh isolates</button>
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    {snapshot && <><p>{snapshot.configured} configured · {snapshot.workers.filter((row) => row.healthy).length} healthy · {snapshot.workers.filter((row) => row.state === "Judging").length} working</p>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr>
        <th>Instance</th><th>Status</th><th>Submission</th><th>Last heartbeat</th><th>Completed since restart</th><th>Fault</th>
      </tr></thead><tbody>{snapshot.workers.map((row) => <tr key={row.slot} className="border-t">
        <td>{row.slot + 1}</td><td><span className={row.state === "Faulted" || row.state === "Offline" ? "notice-danger rounded px-2" : ""}>{row.state}</span></td>
        <td>{row.submission_id || "—"}</td><td>{row.heartbeat_at ? new Date(row.heartbeat_at).toLocaleString() : "Unavailable"}</td>
        <td>{row.completed}</td><td>{row.fault || "—"}</td>
      </tr>)}</tbody></table></div>
      <p className="text-sm">Set CJUDGE_SANDBOX_INSTANCES and CJUDGE_JUDGE_MEMORY_LIMIT in .env, then recreate the worker service.</p>
    </>}
  </section>;
}
