import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "./api";
import { useOffset } from "./navigation";

type Submission = { id: string; revision_id: string; filename: string; accepted_at: string; status: string;
  compiler_feedback: string | null; compiler_truncated: boolean; best_for_review?: boolean };
type Admission = { allowed: boolean; reason: string; code: string; pending: number; retry_at: string | null; server_time: string };
type Task = { revision_id: string; title: string };
export type UploadDraft = { file: File | null; pending: { file: File; revision: string; key: string } | null };

function History({ rows, tasks, labId, visible }: { rows: Submission[]; tasks: Task[]; labId: string; visible?: boolean }) {
  return <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr>
    <th>Accepted</th><th>Task</th><th>File</th><th>Status / compiler feedback</th>
  </tr></thead><tbody>{rows.map((row) => <tr key={row.id} className="border-t align-top" data-best={visible && row.best_for_review || undefined}>
    <td>{new Date(row.accepted_at).toLocaleString()}</td><td><Link to={`/labs/${labId}/tasks/${row.revision_id}`}>{tasks.find((task) => task.revision_id === row.revision_id)?.title || row.revision_id}</Link></td>
    <td>{visible ? <Link to={`/labs/${labId}/submissions/${row.id}`}>{row.filename}</Link> : row.filename}{visible && row.best_for_review && <span className="block text-green-800">Best for review</span>}</td><td><span className="submission-status" data-status={row.status}>{row.status}</span>{row.compiler_feedback && <pre className="max-w-xl overflow-x-auto whitespace-pre-wrap">{row.compiler_feedback}</pre>}
      {row.compiler_truncated && <p>Compiler feedback truncated.</p>}</td>
  </tr>)}</tbody></table>{!rows.length && <p>No submissions.</p>}</div>;
}

export function StudentSubmissions({ labId, tasks, admission, csrf, refresh, revisionId, draft, setDraft, visible }: {
  labId: string; tasks: Task[]; admission?: Admission; csrf: string; refresh: () => Promise<void>; revisionId?: string;
  visible?: boolean; draft: UploadDraft; setDraft: (draft: UploadDraft) => void;
}) {
  const [rows, setRows] = useState<Submission[]>([]), [offset, setOffset] = useOffset();
  const [params, setParams] = useSearchParams();
  const revision = revisionId || params.get("task") || "";
  const { file, pending } = draft;
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [message, setMessage] = useState("");
  const input = useRef<HTMLInputElement>(null);
  async function history(signal?: AbortSignal) {
    const query = new URLSearchParams({ offset: String(offset) }); if (revision) query.set("revision_id", revision);
    try { const next = await api<Submission[]>(`/labs/${labId}/submissions?${query}`, { signal }); if (!signal?.aborted) setRows(next); }
    catch (e) { if (!signal?.aborted) setError((e as Error).message); }
  }
  useEffect(() => {
    const controller = new AbortController(); setRows([]); void history(controller.signal);
    return () => controller.abort();
  }, [labId, offset, revision, admission?.server_time]);
  useEffect(() => {
    if (!admission?.retry_at) return;
    const delay = Date.parse(admission.retry_at) - Date.parse(admission.server_time);
    const timer = setTimeout(() => { void refresh(); }, Math.max(0, delay) + 50);
    return () => clearTimeout(timer);
  }, [admission?.retry_at, admission?.server_time]);
  async function submit(event?: FormEvent) {
    event?.preventDefault(); if (busy || !pending && !file || !revisionId) return;
    const upload = pending || { file: file!, revision: revisionId, key: crypto.randomUUID() };
    if (!pending && (!/^[A-Za-z0-9_][A-Za-z0-9_.-]{0,157}\.c$/.test(upload.file.name) || !upload.file.size || upload.file.size > 65536)) {
      setError("Select a nonempty .c file up to 64 KiB with a plain filename."); return;
    }
    setDraft({ file, pending: upload }); setBusy(true); setError(""); setMessage("");
    try {
      const accepted = await api<Submission>(`/labs/${labId}/submissions?revision_id=${encodeURIComponent(upload.revision)}&filename=${encodeURIComponent(upload.file.name)}`,
        { method: "POST", body: upload.file, headers: { "Content-Type": "application/octet-stream", "Idempotency-Key": upload.key } }, csrf);
      setDraft({ file: null, pending: null }); if (input.current) input.current.value = "";
      setMessage(`Accepted ${accepted.filename} at ${new Date(accepted.accepted_at).toLocaleTimeString()}.`);
      setOffset(0); await history(); await refresh();
    } catch (e) {
      const failure = e as Error & { status?: number }; setError(failure.message);
      if (failure.status && failure.status < 500) setDraft({ file, pending: null });
    } finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded border bg-white p-4">
    {revisionId && <><h2 className="font-semibold">Submit C source</h2>
      <form onSubmit={submit}><fieldset disabled={busy || !!pending} className="flex flex-wrap items-center gap-3">
        <label>C file (64 KiB maximum)<input ref={input} type="file" accept=".c" onChange={(e) => setDraft({ file: e.target.files?.[0] || null, pending: null })} /></label>
        {file && <span>Selected: {file.name}</span>}<button disabled={!admission?.allowed || !file}>Submit</button>
      </fieldset></form>
      {admission && <p>{admission.pending} pending · {admission.allowed ? "Uploads enabled" : admission.reason}{admission.retry_at && ` · Retry at ${new Date(admission.retry_at).toLocaleTimeString()}`}</p>}
      {pending && <div className="notice notice-warning"><p>Acceptance not confirmed. Retry the same upload to recover its record, including after the deadline.</p>
        <button disabled={busy} onClick={() => { void submit(); }}>Retry upload</button></div>}
    </>}
    {error && <p role="alert" className="notice notice-danger">{error}</p>}{message && <p role="status" className="notice notice-warning">{message}</p>}
    <h2 className="font-semibold">Submission history</h2>
    {!revisionId && <label>Filter by task <select value={revision} onChange={(e) => setParams(e.target.value ? { task: e.target.value } : {})}>
      <option value="">All tasks</option>{tasks.map((task) => <option key={task.revision_id} value={task.revision_id}>{task.title}</option>)}
    </select></label>}
    <History rows={rows} tasks={tasks} labId={labId} visible={visible} />
    <div className="flex flex-wrap gap-2"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>Newer submissions</button>
      <button disabled={rows.length < 100} onClick={() => setOffset(offset + 100)}>Older submissions</button><button onClick={() => { void history(); void refresh(); }}>Refresh submissions</button></div>
  </section>;
}
