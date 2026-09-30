import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useMatch } from "react-router";
import { api } from "./api";
import SubmissionDetail from "./SubmissionDetail";
import LabClock from "./LabClock";
import Statement from "./Statement";
import { StudentSubmissions, type UploadDraft } from "./Submissions";
import { Announcements, type Summary, type PublicLab } from "./Lab";
import { NotFound, useUnsaved } from "./navigation";

export function StudentLabs({ csrf }: { csrf: string }) {
  const route = useMatch('/labs/:labId/*'), listRoute = useMatch('/labs');
  const labId = route?.params.labId, parts = (route?.params['*'] || '').split('/').filter(Boolean);
  const section = parts[0] || 'overview', revisionId = section === 'tasks' ? parts[1] : undefined;
  const submissionId = section === "submissions" ? parts[1] : undefined;
  const [rows, setRows] = useState<Summary[]>([]), [detail, setDetail] = useState<PublicLab | null>(null);
  const [message, setMessage] = useState(''), [failure, setFailure] = useState(0), [busy, setBusy] = useState(false);
  const [connection, setConnection] = useState('');
  const [drafts, setDrafts] = useState<Record<string, UploadDraft>>({});
  const currentLab = useRef(labId); currentLab.current = labId;
  const selected = rows.find((row) => row.id === labId);
  async function list(signal?: AbortSignal) {
    try { const next = await api<Summary[]>('/labs', { signal }); if (!signal?.aborted) setRows(next); }
    catch (e) { if (!signal?.aborted) setMessage((e as Error).message); }
  }
  async function refresh(signal?: AbortSignal) {
    const id = labId;
    if (!id) { await list(signal); return; }
    try {
      const value = await api<PublicLab>(`/labs/${id}`, { signal });
      if (!signal?.aborted && currentLab.current === id) { setDetail(value); setMessage(''); setFailure(0); }
    } catch (e) {
      if (signal?.aborted || currentLab.current !== id) return;
      const error = e as Error & { status: number };
      setMessage(error.message); setFailure(error.status);
      if ([401, 403, 404, 423].includes(error.status)) setDetail(null);
      if ([403, 423].includes(error.status)) await list(signal);
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    setDetail(null); setMessage(''); setFailure(0); setDrafts({});
    void list(controller.signal); if (labId) void refresh(controller.signal);
    return () => controller.abort();
  }, [labId]);
  async function enter() {
    if (!labId) return;
    const id = labId; setBusy(true); setMessage('');
    try {
      const value = await api<PublicLab>(`/labs/${id}/enter`, { method: 'POST' }, csrf);
      if (currentLab.current === id) { setDetail(value); setFailure(0); }
    } catch (e) { if (currentLab.current === id) setMessage((e as Error).message); }
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
        const error = e as Error & { status: number }; setMessage(error.message); setFailure(error.status);
        if ([401, 403, 404, 423].includes(error.status)) { source.close(); setDetail(null); }
      } finally { fetching = false; }
    }
    function connect() {
      source = new EventSource(`/api/labs/${id}/events`);
      source.onopen = () => setConnection('Live updates connected');
      source.onerror = () => setConnection('Updates reconnecting…');
      source.addEventListener('refresh', () => { void load(); });
      source.addEventListener('denied', () => { controller.abort(); source.close(); setDetail(null); setFailure(423); setMessage('Lab access changed. Sign in or enter again.'); });
      source.addEventListener('reconnect', () => { source.close(); setConnection('Updates reconnecting…'); retry = setTimeout(connect, 3000); });
    }
    connect();
    return () => { controller.abort(); source.close(); if (retry) clearTimeout(retry); setConnection(''); };
  }, [detail?.id]);
  useUnsaved(busy || Object.values(drafts).some((draft) => !!draft.file || !!draft.pending));
  const task = detail?.tasks.find((item) => item.revision_id === revisionId || item.previous_revision_ids?.includes(revisionId || ''));
  if ((!route && !listRoute) || parts.length > 2 || !['overview', 'tasks', 'submissions'].includes(section) ||
      section === 'overview' && parts.length > 0 || section === 'tasks' && !revisionId || section === 'submissions' && parts.length > 2 || [404, 422].includes(failure) || detail && revisionId && !task) return <NotFound />;
  return <div className="space-y-4">
    {!labId ? <><h1 className="text-xl font-semibold">Assigned labs</h1>
      {rows.length ? <div className="overflow-x-auto rounded border bg-white p-4"><table className="w-full text-left"><thead><tr><th>Lab</th><th>Status</th><th>Start</th><th>Deadline</th></tr></thead>
        <tbody>{rows.map((row) => <tr className="border-t" key={row.id}><td><Link to={`/labs/${row.id}`}>{row.title}</Link></td>
          <td>{row.phase}</td><td>{new Date(row.starts_at!).toLocaleString()}</td><td>{new Date(row.ends_at!).toLocaleString()}</td></tr>)}</tbody></table></div>
        : <p>No labs assigned yet.</p>}</> : <>
      <nav aria-label="Lab breadcrumbs"><Link to="/labs">Labs</Link> / <Link to={`/labs/${labId}`}>{detail?.title || selected?.title || 'Lab'}</Link>{task && ` / ${task.title}`}</nav>
      {detail && <nav aria-label="Lab navigation" className="flex flex-wrap gap-2"><NavLink end className="nav-link" to={`/labs/${labId}`}>Overview</NavLink>
        <NavLink className="nav-link" to={`/labs/${labId}/submissions`}>Submissions</NavLink></nav>}
      <section className="space-y-2 rounded border bg-white p-4"><h1 className="text-xl font-semibold">{detail?.title || selected?.title || 'Lab'}{detail && ` · ${detail.phase}`}</h1>
        {(detail || selected) && <LabClock serverTime={(detail || selected)!.server_time} start={(detail || selected)!.starts_at} end={(detail || selected)!.ends_at} refresh={() => { void refresh(); }} />}
        {!detail && failure > 0 && selected && <><p>Entering binds this browser to the lab. A lost binding requires admin release.</p>
          <button disabled={busy || selected.phase === 'Scheduled'} onClick={enter}>Enter lab</button></>}
        {!detail && !failure && <p role="status">Loading lab…</p>}
        <button disabled={busy} onClick={() => { void refresh(); }}>Refresh lab</button>{connection && <p className="text-sm">{connection}</p>}
      </section>
      {detail && <>
        {submissionId && <SubmissionDetail key={submissionId} labId={detail.id} submissionId={submissionId} visible={!!detail.results_visible} refreshKey={detail.server_time} />}
        {Object.entries(drafts).filter(([id, draft]) => id !== revisionId && draft.pending).map(([id]) => <aside key={id} className="notice notice-warning">
          Upload acceptance unconfirmed. <Link to={`/labs/${labId}/tasks/${id}`}>Return to {detail.tasks.find((item) => item.revision_id === id)?.title || 'task'} to retry</Link>.
        </aside>)}
        {detail.frozen && <p role="status" className="notice notice-danger">Submissions paused by administrator. You can still read lab materials.</p>}
        {section !== 'overview' && detail.announcements.length > 0 && <aside className="notice notice-warning"><strong>Latest announcement · {detail.announcements[detail.announcements.length - 1].audience || "Everyone"}</strong>
          <p className="whitespace-pre-wrap">{detail.announcements[detail.announcements.length - 1].body}</p><Link to={`/labs/${labId}`}>All announcements</Link></aside>}
        {(section === 'overview' || task) && <section className="rounded border bg-white p-4"><h2 className="font-semibold">Lab PDFs</h2>
          {detail.pdfs.length ? <ul>{detail.pdfs.map((pdf) => <li key={pdf.id}><a download href={`/api/labs/${detail.id}/pdfs/${pdf.id}`}>{pdf.name}</a></li>)}</ul>
            : <p>Read the task statement.</p>}
        </section>}
        {section === 'overview' && <><Announcements messages={detail.announcements} />
          <section className="rounded border bg-white p-4"><h2 className="font-semibold">Tasks</h2><ul>{detail.tasks.map((item) => <li className="border-t py-3" key={item.revision_id}>
            <Link to={`/labs/${detail.id}/tasks/${item.revision_id}`}>{item.position}. {item.title}</Link> · {item.maximum_marks} marks
          </li>)}</ul></section></>}
        {task && <section className="space-y-3 rounded border bg-white p-4"><h2 className="text-lg font-semibold">{task.position}. {task.title} · {task.maximum_marks} marks</h2>
          {task.revision_id !== revisionId && <p className="notice notice-warning">Task corrected. New uploads use the current revision; unconfirmed uploads retain their original retry key.</p>}
          <p>CPU {task.cpu_seconds}s · Wall {task.wall_seconds}s · Memory {task.memory_mib} MiB · Stack {task.stack_mib} MiB</p>
          <Statement text={task.statement} />
          <nav aria-label="Task navigation" className="flex flex-wrap gap-3">{detail.tasks.map((item) => <NavLink key={item.revision_id} className="nav-link" to={`/labs/${detail.id}/tasks/${item.revision_id}`}>{item.position}. {item.title}</NavLink>)}</nav>
        </section>}
        {(task || section === 'submissions' && !submissionId) && <StudentSubmissions visible={!!detail.results_visible} key={revisionId || 'history'} labId={detail.id} tasks={detail.tasks} admission={detail.admission} csrf={csrf} refresh={refresh}
          revisionId={task?.revision_id} draft={drafts[revisionId || ''] || { file: null, pending: null }} setDraft={(draft) => setDrafts((old) => ({ ...old, [revisionId || '']: draft }))} />}
      </>}
    </>}
    {message && <p role="alert" className="notice notice-danger">{message}</p>}
  </div>;
}
