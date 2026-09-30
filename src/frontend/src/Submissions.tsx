import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "./api";
import { useAdminEvents } from "./Isolates";

type Submission = { id: string; revision_id: string; filename: string; accepted_at: string; status: string;
  compiler_feedback: string | null; compiler_truncated: boolean };
type AdminSubmission = Submission & { account_id: string; roll_number: string; name: string; attempt_count: number; fault: string | null;
  client_ip: string; client_mac: string | null; passed: number | null; total: number | null };
type Admission = { allowed: boolean; reason: string; code: string; pending: number; retry_at: string | null; server_time: string };
type PendingUpload = { file: File; revision: string; key: string };

function History({ rows, tasks }: { rows: Submission[]; tasks: { revision_id: string; title: string }[] }) {
  return <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr>
    <th>Accepted</th><th>Task</th><th>File</th><th>Status / compiler feedback</th>
  </tr></thead><tbody>{rows.map((row) => <tr key={row.id} className="border-t align-top">
    <td>{new Date(row.accepted_at).toLocaleString()}</td><td>{tasks.find((task) => task.revision_id === row.revision_id)?.title || row.revision_id}</td>
    <td>{row.filename}</td><td>{row.status}{row.compiler_feedback && <pre className="max-w-xl overflow-x-auto whitespace-pre-wrap">{row.compiler_feedback}</pre>}
      {row.compiler_truncated && <p>Compiler feedback truncated.</p>}</td>
  </tr>)}</tbody></table>{!rows.length && <p>No submissions.</p>}</div>;
}

export function StudentSubmissions({ labId, tasks, admission, csrf, refresh }: { labId: string;
  tasks: { revision_id: string; title: string }[]; admission?: Admission; csrf: string; refresh: () => Promise<void> }) {
  const [rows, setRows] = useState<Submission[]>([]), [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(tasks[0]?.revision_id || ""), [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState<PendingUpload | null>(null), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [message, setMessage] = useState("");
  const input = useRef<HTMLInputElement>(null);
  async function history() {
    try { setRows(await api<Submission[]>(`/labs/${labId}/submissions?offset=${offset}`)); }
    catch (e) { setError((e as Error).message); }
  }
  useEffect(() => { void history(); }, [labId, offset, admission?.server_time]);
  useEffect(() => {
    if (!admission?.retry_at) return;
    const delay = Date.parse(admission.retry_at) - Date.parse(admission.server_time);
    const timer = setTimeout(() => { void refresh(); }, Math.max(0, delay) + 50);
    return () => clearTimeout(timer);
  }, [admission?.retry_at, admission?.server_time]);
  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (busy || !pending && !file) return;
    const upload = pending || { file: file!, revision, key: crypto.randomUUID() };
    if (!pending && (!/^[A-Za-z0-9_][A-Za-z0-9_.-]{0,157}\.c$/.test(upload.file.name) || !upload.file.size || upload.file.size > 65536)) {
      setError("Select a nonempty .c file up to 64 KiB with a plain filename."); return;
    }
    setPending(upload); setBusy(true); setError(""); setMessage("");
    try {
      const accepted = await api<Submission>(`/labs/${labId}/submissions?revision_id=${encodeURIComponent(upload.revision)}&filename=${encodeURIComponent(upload.file.name)}`,
        { method: "POST", body: upload.file, headers: { "Content-Type": "application/octet-stream", "Idempotency-Key": upload.key } }, csrf);
      setPending(null); setFile(null); if (input.current) input.current.value = "";
      setMessage(`Accepted ${accepted.filename} at ${new Date(accepted.accepted_at).toLocaleTimeString()}.`);
      setOffset(0); await history(); await refresh();
    } catch (e) {
      const failure = e as Error & { status?: number };
      setError(failure.message);
      if (failure.status && failure.status < 500) setPending(null);
    } finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded border bg-white p-4">
    <h2 className="font-semibold">Submit C source</h2>
    <form onSubmit={submit}><fieldset disabled={busy || !!pending} className="flex flex-wrap items-center gap-3">
      <label>Task <select value={revision} onChange={(e) => setRevision(e.target.value)}>{tasks.map((task) => <option key={task.revision_id} value={task.revision_id}>{task.title}</option>)}</select></label>
      <label>C file (64 KiB maximum)<input ref={input} type="file" accept=".c" onChange={(e) => setFile(e.target.files?.[0] || null)} /></label>
      <button disabled={!admission?.allowed || !file || !revision}>Submit</button>
    </fieldset></form>
    {admission && <p>{admission.pending} pending · {admission.allowed ? "Uploads enabled" : admission.reason}{admission.retry_at && ` · Retry at ${new Date(admission.retry_at).toLocaleTimeString()}`}</p>}
    {pending && <div className="notice notice-warning"><p>Acceptance not confirmed. Retry the same upload to recover its record, including after the deadline.</p>
      <button disabled={busy} onClick={() => { void submit(); }}>Retry upload</button></div>}
    {error && <p role="alert" className="notice notice-danger">{error}</p>}{message && <p role="status" className="notice notice-warning">{message}</p>}
    <h2 className="font-semibold">Submission history</h2><History rows={rows} tasks={tasks} />
    <div className="flex gap-2"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>Newer submissions</button>
      <button disabled={rows.length < 100} onClick={() => setOffset(offset + 100)}>Older submissions</button><button onClick={() => { void history(); void refresh(); }}>Refresh submissions</button></div>
  </section>;
}

export function AdminSubmissions({ labId, csrf, feedback }: { labId: string; csrf: string; feedback?: string }) {
  const [rows, setRows] = useState<AdminSubmission[]>([]), [offset, setOffset] = useState(0), [error, setError] = useState("");
  const [mode, setMode] = useState(feedback || "short");
  async function refresh() {
    try { setRows(await api<AdminSubmission[]>(`/admin/labs/${labId}/submissions?offset=${offset}`)); setError(""); }
    catch (e) { setError((e as Error).message); }
  }
  useAdminEvents(refresh);
  useEffect(() => { void refresh(); }, [labId, offset]);
  async function retry(row: AdminSubmission) {
    const reason = prompt("Reason to retry delayed judging"); if (!reason?.trim()) return;
    try { await api(`/admin/labs/${labId}/submissions/${row.id}/retry`, { method: "POST", body: JSON.stringify({ reason }) }, csrf); await refresh(); }
    catch (e) { setError((e as Error).message); }
  }
  async function saveFeedback() {
    try { await api(`/admin/labs/${labId}/compiler-feedback`, { method: "PUT", body: JSON.stringify({ mode }) }, csrf); setError(""); }
    catch (e) { setError((e as Error).message); }
  }
  return <section className="space-y-3 rounded border bg-white p-4">
    <h2 className="font-semibold">Submissions and judging faults</h2>
    <label>Student compiler feedback <select value={mode} onChange={(e) => setMode(e.target.value)}><option value="short">First 20 lines</option><option value="full">Full retained feedback</option><option value="none">Verdict only</option></select></label>{" "}
    <button onClick={() => { void saveFeedback(); }}>Save compiler feedback</button>{" "}<button onClick={() => { void refresh(); }}>Refresh queue</button>
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Accepted</th><th>Student</th><th>Source</th><th>Status</th><th>Attempts</th><th>IP / MAC</th><th>Fault</th></tr></thead>
      <tbody>{rows.map((row) => <tr className="border-t align-top" key={row.id}><td>{new Date(row.accepted_at).toLocaleString()}</td><td>{row.roll_number} · {row.name}</td>
        <td><a download href={`/api/admin/labs/${labId}/submissions/${row.id}/source`}>{row.filename}</a></td><td>{row.status}
          {row.compiler_feedback && <details><summary>Compiler feedback</summary><pre className="max-w-xl overflow-x-auto whitespace-pre-wrap">{row.compiler_feedback}</pre></details>}</td>
        <td>{row.attempt_count}</td><td>{row.client_ip}<br />{row.client_mac || "MAC unavailable"}</td><td>{row.fault || "—"}
          {row.status === "Judging delayed" && <button onClick={() => { void retry(row); }}>Retry judging</button>}</td></tr>)}</tbody>
    </table>{!rows.length && <p>No submissions.</p>}</div>
    <div className="flex gap-2"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>Newer submissions</button>
      <button disabled={rows.length < 100} onClick={() => setOffset(offset + 100)}>Older submissions</button></div>
  </section>;
}
