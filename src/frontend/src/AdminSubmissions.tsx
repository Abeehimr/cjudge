import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "./api";
import { useAdminEvents } from "./Isolates";
import { useOffset, useUnsaved } from "./navigation";

type Submission = { id: string; revision_id: string; filename: string; accepted_at: string; status: string;
  compiler_feedback: string | null; compiler_truncated: boolean; best_for_review?: boolean };
type AdminSubmission = Submission & { account_id: string; roll_number: string; name: string; attempt_count: number; fault: string | null;
  client_ip: string; client_mac: string | null; passed: number | null; total: number | null; marks: string | null;
  deleted_at: string | null; delete_reason: string | null; rejudge_status: string | null; ip_changed: boolean; mac_changed: boolean };
type SubmissionDetail = AdminSubmission & { size: number; source: string; score_numerator: string | null; score_denominator: string | null;
  official_run_id: string | null; run_id: string | null; result_revision_id: string | null;
  history: { id: string; revision_id: string; verdict: string; finished_at: string }[];
  attempts: { id: string; started_at: string; outcome: string | null; fault: string | null }[];
  cases: { number: number; verdict: string; cpu_seconds: number; wall_seconds: number; memory_kib: number;
    stdin: string; expected: string; stdin_truncated: boolean; expected_truncated: boolean; stdout: string; stderr: string; stdout_truncated: boolean; stderr_truncated: boolean }[] };
type Task = { revision_id: string; title: string };
type Student = { id: string; roll_number: string; name: string };
export function CompilerFeedback({ labId, csrf, feedback, refreshLab, onDirty }: { labId: string; csrf: string; feedback?: string;
  refreshLab: () => Promise<void>; onDirty?: (dirty: boolean) => void }) {
  const [mode, setMode] = useState(feedback || "short"), [error, setError] = useState("");
  useEffect(() => { onDirty?.(mode !== (feedback || "short")); }, [mode, feedback]);
  useEffect(() => () => onDirty?.(false), []);
  async function save() {
    try { await api(`/admin/labs/${labId}/compiler-feedback`, { method: "PUT", body: JSON.stringify({ mode }) }, csrf); await refreshLab(); setError(""); }
    catch (e) { setError((e as Error).message); }
  }
  return <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">Compiler feedback</h2>
    <label>Student compiler feedback <select value={mode} onChange={(e) => setMode(e.target.value)}><option value="short">First 20 lines</option><option value="full">Full retained feedback</option><option value="none">Verdict only</option></select></label>{" "}
    <button onClick={() => { void save(); }}>Save compiler feedback</button>{error && <p role="alert" className="notice notice-danger">{error}</p>}
  </section>;
}

export function AdminSubmissions({ labId, csrf, tasks, students, accountId, revisionId }: { labId: string; csrf: string;
  tasks: Task[]; students: Student[]; accountId?: string; revisionId?: string }) {
  const [rows, setRows] = useState<AdminSubmission[]>([]), [offset, setOffset] = useOffset(), [error, setError] = useState("");
  const [params, setParams] = useSearchParams();
  const account = accountId || params.get("student") || "", revision = revisionId || params.get("task") || "";
  const order = params.get('order') === 'latest' ? 'latest' : params.get('order') === 'best' || accountId || revisionId ? 'best' : 'latest';
  const latest = useRef(0);
  async function refresh() {
    const request = ++latest.current;
    const query = new URLSearchParams({ offset: String(offset) }); if (account) query.set("account_id", account); if (revision) query.set("revision_id", revision);
    if (order === 'best') query.set('order', 'best');
    try { const next = await api<AdminSubmission[]>(`/admin/labs/${labId}/submissions?${query}`);
      if (request === latest.current) { setRows(next); setError(""); } }
    catch (e) { if (request === latest.current) setError((e as Error).message); }
  }
  const connection = useAdminEvents(refresh);
  useEffect(() => { setRows([]); void refresh(); return () => { latest.current++; }; }, [labId, offset, account, revision, order]);
  function filter(key: string, value: string) {
    setParams((current) => { const next = new URLSearchParams(current); next.delete("offset"); if (value) next.set(key, value); else next.delete(key); return next; });
  }
  async function retry(row: AdminSubmission) {
    const reason = prompt("Reason to retry delayed judging"); if (!reason?.trim()) return;
    try { await api(`/admin/labs/${labId}/submissions/${row.id}/retry`, { method: "POST", body: JSON.stringify({ reason }) }, csrf); await refresh(); }
    catch (e) { setError((e as Error).message); }
  }
  return <section className="space-y-3 rounded border bg-white p-4">
    <h2 className="font-semibold">Submissions</h2><p>{connection}</p>
    <div className="flex flex-wrap items-center gap-3">
      {!accountId && <label>Filter by student <select value={account} onChange={(e) => filter("student", e.target.value)}><option value="">All students</option>
        {students.map((student) => <option key={student.id} value={student.id}>{student.roll_number} · {student.name}</option>)}</select></label>}
      {!revisionId && <label>Filter by task <select value={revision} onChange={(e) => filter("task", e.target.value)}><option value="">All tasks</option>
        {tasks.map((task) => <option key={task.revision_id} value={task.revision_id}>{task.title}</option>)}</select></label>}
      <button onClick={() => { void refresh(); }}>Refresh submissions</button>
      <label>Attempt order <select value={order} onChange={(e) => filter('order', e.target.value)}><option value="latest">Newest first</option><option value="best">Best first · pending and deleted last</option></select></label>
    </div>
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Accepted</th><th>Student</th><th>Task</th><th>Source</th><th>Status</th><th>Attempts</th><th>IP / MAC</th><th>Fault</th></tr></thead>
      <tbody>{rows.map((row) => <tr className="border-t align-top" data-best={row.best_for_review || undefined} key={row.id}><td>{new Date(row.accepted_at).toLocaleString()}</td>
        <td><Link to={`/admin/labs/${labId}/students/${row.account_id}`}>{row.roll_number} · {row.name}</Link></td>
        <td><Link to={`/admin/labs/${labId}/tasks/${row.revision_id}`}>{tasks.find((task) => task.revision_id === row.revision_id)?.title || row.revision_id}</Link></td>
        <td><Link to={`/admin/labs/${labId}/submissions/${row.id}`}>{row.filename}</Link>{row.best_for_review && <span className="block text-green-800">Best for review</span>}</td><td><span className="submission-status" data-status={row.status}>{row.status}</span>
          {row.deleted_at && <p className="text-red-800">Deleted · {row.delete_reason}</p>}
          {row.marks != null && <p>{row.marks} marks · {row.passed}/{row.total} cases</p>}
          {row.rejudge_status && <p className="text-amber-800">Rejudge: {row.rejudge_status}</p>}
          {row.compiler_feedback && <details><summary>Compiler feedback</summary><pre className="max-w-xl overflow-x-auto whitespace-pre-wrap">{row.compiler_feedback}</pre></details>}
          {row.compiler_truncated && <p>Compiler feedback truncated.</p>}</td>
        <td>{row.attempt_count}</td><td>{row.client_ip}<br />{row.client_mac || "MAC unavailable"}{(row.ip_changed || row.mac_changed) && <p className="text-amber-800">Possible PC switch · {row.ip_changed && 'IP changed'}{row.ip_changed && row.mac_changed && ', '}{row.mac_changed && 'MAC changed'}</p>}</td><td>{row.fault || "—"}
          {(row.status === "Judging delayed" || row.rejudge_status === 'delayed') && <button onClick={() => { void retry(row); }}>Retry judging</button>}</td></tr>)}</tbody>
    </table>{!rows.length && <p>No submissions.</p>}</div>
    <div className="flex gap-2"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>Newer submissions</button>
      <button disabled={rows.length < 100} onClick={() => setOffset(offset + 100)}>Older submissions</button></div>
  </section>;
}

export function AdminSubmissionDetail({ labId, submissionId, csrf, released, archived }: { labId: string; submissionId: string; csrf: string; released?: boolean; archived?: boolean }) {
  const [row, setRow] = useState<SubmissionDetail | null>(null), [error, setError] = useState("");
  const [params, setParams] = useSearchParams(), [busy, setBusy] = useState(false);
  const run = params.get('run') || '';
  useUnsaved(busy, true);
  const latest = useRef(0);
  async function refresh() {
    const request = ++latest.current;
    try { const value = await api<SubmissionDetail>(`/admin/labs/${labId}/submissions/${submissionId}${run ? '?run_id=' + encodeURIComponent(run) : ''}`);
      if (request === latest.current) { setRow(value); setError(""); } }
    catch (e) { if (request === latest.current) { setRow(null); setError((e as Error).message); } }
  }
  const connection = useAdminEvents(refresh);
  useEffect(() => { setRow(null); void refresh(); return () => { latest.current++; }; }, [labId, submissionId, run]);
  async function action(kind: 'review' | 'rejudge' | 'retry') {
    if (!row || busy) return;
    const verb = kind === 'review' ? row.deleted_at ? 'Restore' : 'Delete' : kind === 'retry' ? 'Retry judging' : 'Rejudge';
    if (!confirm(`${released ? 'Results have already been released; current marks may change. ' : ''}${verb} this submission? Evidence and previous results are retained.`)) return;
    const reason = prompt(`Reason to ${verb.toLowerCase()}`); if (!reason?.trim()) return;
    setBusy(true);
    try { await api(`/admin/labs/${labId}/submissions/${submissionId}/${kind}`, { method: kind === 'review' ? 'PUT' : 'POST',
      body: JSON.stringify({ reason: reason.trim(), ...(kind === 'review' ? { deleted: !row.deleted_at } : kind === 'rejudge' ? { expected_run_id: row.official_run_id } : {}) }) }, csrf);
      await refresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded border bg-white p-4">
    <h2 className="font-semibold">Submission {submissionId}</h2>
    <p>{connection}</p><button onClick={() => { void refresh(); }}>Refresh submission</button>
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    {!row && !error && <p role="status">Loading submission…</p>}
    {row && <>
      <div className="flex flex-wrap gap-3"><button disabled={busy || archived} onClick={() => { void action('review'); }}>{row.deleted_at ? 'Restore submission' : 'Delete submission'}</button>
        <button disabled={busy || archived || !!row.deleted_at || !!row.rejudge_status || !row.official_run_id} onClick={() => { void action('rejudge'); }}>Rejudge submission</button>
        {(row.status === 'Judging delayed' || row.rejudge_status === 'delayed') && <button disabled={busy || archived} onClick={() => { void action('retry'); }}>Retry judging</button>}</div>
      {row.deleted_at && <p className="notice notice-danger">Deleted from marks and student history · {row.delete_reason}</p>}
      {row.rejudge_status && <p className="notice notice-warning">Rejudge: {row.rejudge_status}. Previous official results remain visible until replacement.</p>}
      {(row.ip_changed || row.mac_changed) && <p className="notice notice-warning">Possible PC switch: {row.ip_changed && 'IP changed'}{row.ip_changed && row.mac_changed && ', '}{row.mac_changed && 'MAC changed'}. Address differences are not proof.</p>}
      <p><Link to={`/admin/labs/${labId}/students/${row.account_id}`}>{row.roll_number} · {row.name}</Link>{" · "}
        <Link to={`/admin/labs/${labId}/tasks/${row.revision_id}`}>Task</Link></p>
      <p><span className="submission-status" data-status={row.status}>{row.status}</span> · Accepted {new Date(row.accepted_at).toLocaleString()} · {row.attempt_count} judging attempts</p>
      <p>IP: {row.client_ip} · MAC: {row.client_mac || "Unavailable"}</p>
      {row.passed !== null && <p>Cases passed: {row.passed}/{row.total} · Marks: {row.marks}</p>}
      <label>Judge result <select value={run} disabled={busy} onChange={(e) => setParams(e.target.value ? { run: e.target.value } : {})}>
        <option value="">Official result</option>{(row.history || []).map((item) => <option key={item.id} value={item.id}>{item.verdict} · {new Date(item.finished_at).toLocaleString()} · {item.id === row.official_run_id ? 'Official' : 'Retained run'}</option>)}</select></label>
      {run && <p className="notice notice-warning">Viewing retained run; marks use the official result.</p>}
      {row.result_revision_id && <p>Result revision: {row.result_revision_id}</p>}
      <details><summary>Judging attempts</summary><ul>{(row.attempts || []).map((item) => <li key={item.id}>{new Date(item.started_at).toLocaleString()} · {item.outcome || 'Judging'}{item.fault && ` · ${item.fault}`}</li>)}</ul></details>
      {row.fault && <p className="notice notice-danger">{row.fault}</p>}
      <h3 className="font-semibold">Source: {row.filename} ({row.size} bytes)</h3>
      <a download href={`/api/admin/labs/${labId}/submissions/${row.id}/source`}>Download original source</a>
      <pre className="overflow-x-auto rounded border bg-slate-50 p-3"><code>{row.source}</code></pre>
      {row.compiler_feedback && <><h3 className="font-semibold">Compiler feedback</h3><pre className="overflow-x-auto whitespace-pre-wrap">{row.compiler_feedback}</pre></>}
      {row.compiler_truncated && <p>Compiler feedback truncated.</p>}
      <h3 className="font-semibold">Case results</h3>
      {!row.cases.length && <p>No case results available.</p>}
      {row.cases.map((item) => <details className="rounded border p-3" key={item.number}>
        <summary>Case {item.number}: {item.verdict} · CPU {item.cpu_seconds}s · Wall {item.wall_seconds}s · Memory {item.memory_kib} KiB</summary>
        <h4>Standard input{item.stdin_truncated ? " (truncated)" : ""}</h4><pre className="overflow-x-auto whitespace-pre-wrap">{item.stdin || "(empty)"}</pre>
        <h4>Expected output{item.expected_truncated ? " (truncated)" : ""}</h4><pre className="overflow-x-auto whitespace-pre-wrap">{item.expected || "(empty)"}</pre>
        <h4>Standard output{item.stdout_truncated ? " (truncated)" : ""}</h4><pre className="overflow-x-auto whitespace-pre-wrap">{item.stdout || "(empty)"}</pre>
        <h4>Standard error{item.stderr_truncated ? " (truncated)" : ""}</h4><pre className="overflow-x-auto whitespace-pre-wrap">{item.stderr || "(empty)"}</pre>
      </details>)}
    </>}
  </section>;
}
