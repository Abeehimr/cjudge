import { useEffect, useState } from "react";
import { api } from "./api";
import LabClock from "./LabClock";
import Statement from "./Statement";
import { StudentSubmissions } from "./Submissions";
import { Announcements, type Summary, type PublicLab } from "./Lab";

export function StudentLabs({ csrf }: { csrf: string }) {
  const [rows, setRows] = useState<Summary[]>([]), [selected, setSelected] = useState<Summary | null>(null);
  const [detail, setDetail] = useState<PublicLab | null>(null), [message, setMessageText] = useState(""), [busy, setBusy] = useState(false);
  const [messageError, setMessageError] = useState(false);
  function setMessage(text: string) { setMessageError(false); setMessageText(text); }
  function showError(text: string) { setMessageError(true); setMessageText(text); }
  const [connection, setConnection] = useState("");
  async function list() {
    const next = await api<Summary[]>("/labs"); setRows(next);
    setSelected((old) => old ? next.find((row) => row.id === old.id) || null : null);
  }
  useEffect(() => { void list().catch((e) => showError(e.message)); }, []);
  async function refresh() {
    if (detail) {
      try { setDetail(await api<PublicLab>(`/labs/${detail.id}`)); } catch (e) {
        showError((e as Error).message);
        if ([401, 403, 423].includes((e as Error & { status: number }).status)) setDetail(null);
      }
    } else await list().catch((e) => showError(e.message));
  }
  async function enter() {
    if (!selected) return;
    setBusy(true); setMessage("");
    try { setDetail(await api<PublicLab>(`/labs/${selected.id}/enter`, { method: "POST" }, csrf)); }
    catch (e) { showError((e as Error).message); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    if (!detail) return;
    const id = detail.id, controller = new AbortController();
    let source: EventSource, retry: ReturnType<typeof setTimeout> | undefined, fetching = false, again = false;
    async function load() {
      if (fetching) { again = true; return; }
      fetching = true;
      try {
        do {
          again = false;
          const value = await api<PublicLab>(`/labs/${id}`, { signal: controller.signal });
          if (!controller.signal.aborted) setDetail(value);
        } while (again && !controller.signal.aborted);
      } catch (e) {
        if (controller.signal.aborted) return;
        showError((e as Error).message);
        if ([401, 403, 423].includes((e as Error & { status: number }).status)) { source.close(); setDetail(null); }
      } finally { fetching = false; }
    }
    function connect() {
      source = new EventSource(`/api/labs/${id}/events`);
      source.onopen = () => setConnection("Live updates connected");
      source.onerror = () => setConnection("Updates reconnecting…");
      source.addEventListener("refresh", () => { void load(); });
      source.addEventListener("denied", () => { controller.abort(); source.close(); setDetail(null); showError("Lab access changed. Sign in or enter again."); });
      source.addEventListener("reconnect", () => { source.close(); setConnection("Updates reconnecting…"); retry = setTimeout(connect, 3000); });
    }
    connect();
    return () => { controller.abort(); source.close(); if (retry) clearTimeout(retry); setConnection(""); };
  }, [detail?.id]);
  return <div className="space-y-4">
    <h2 className="text-lg font-semibold">Assigned labs</h2>
    {rows.length ? <div className="overflow-x-auto rounded border bg-white p-4"><table className="w-full text-left"><thead><tr><th>Lab</th><th>Status</th><th>Start</th><th>Deadline</th></tr></thead>
      <tbody>{rows.map((row) => <tr className="border-t" key={row.id}><td><button disabled={busy} onClick={() => { setSelected(row); setDetail(null); setMessage(""); }}>{row.title}</button></td>
        <td>{row.phase}</td><td>{new Date(row.starts_at!).toLocaleString()}</td><td>{new Date(row.ends_at!).toLocaleString()}</td></tr>)}</tbody></table></div>
      : <p>No labs assigned yet.</p>}
    {selected && <section className="space-y-2 rounded border bg-white p-4"><h2 className="font-semibold">{selected.title}</h2>
      <LabClock serverTime={detail?.server_time || selected.server_time} start={detail?.starts_at || selected.starts_at} end={detail?.ends_at || selected.ends_at} refresh={() => { void refresh(); }} />
      {!detail && <><p>Entering binds this browser to the lab. A lost binding requires admin release.</p>
        <button disabled={busy || selected.phase === "Scheduled"} onClick={enter}>Enter lab</button></>}
      <button disabled={busy} onClick={() => { void refresh(); }}>Refresh</button>{connection && <p className="text-sm">{connection}</p>}
    </section>}
    {detail && <>
      {detail.frozen && <p role="status" className="notice notice-danger">Submissions paused by administrator. You can still read lab materials.</p>}
      <section id="lab-pdfs" className="rounded border bg-white p-4"><h2 className="font-semibold">Lab PDFs</h2>
        {detail.pdfs.length ? <ul className="space-y-2">{detail.pdfs.map((pdf) => <li key={pdf.id}><a download href={`/api/labs/${detail.id}/pdfs/${pdf.id}`}>{pdf.name}</a></li>)}</ul>
          : <p>Read the task statements below.</p>}
      </section>
      <Announcements messages={detail.announcements} />
      <section className="space-y-4 rounded border bg-white p-4"><h2 className="font-semibold">Tasks</h2>
        {detail.tasks.map((task) => <article className="space-y-2 border-t pt-3" key={task.revision_id}>
          <h3 className="font-semibold">{task.position}. {task.title} · {task.maximum_marks} marks</h3>
          <p className="text-sm">CPU {task.cpu_seconds}s · Wall {task.wall_seconds}s · Memory {task.memory_mib} MiB</p>
          <Statement text={task.statement} />
        </article>)}
      </section>
      <StudentSubmissions key={detail.id} labId={detail.id} tasks={detail.tasks} admission={detail.admission} csrf={csrf} refresh={refresh} />
    </>}
    {message && <p role={messageError ? "alert" : "status"} className={`notice ${messageError ? "notice-danger" : "notice-warning"}`}>{message}</p>}
  </div>;
}
