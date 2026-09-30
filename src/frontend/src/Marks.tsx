import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { api } from "./api";
import { useAdminEvents } from "./Isolates";
import type { AdminLab, Task } from "./Lab";

type Mark = { task_id: string; revision_id: string; title: string; marks: string | null; pending: boolean; best_submission_id: string | null };
type StudentMarks = { id: string; roll_number: string; name: string; tasks: Mark[]; total: string; pending: boolean; submission_count: number };
type Batch = { id: string; task_id: string; state: string; revision_id: string; created_at: string; total: number; completed: number; delayed: number };

export function Marks({ labId, accountId, taskId }: { labId: string; accountId?: string; taskId?: string }) {
  const [rows, setRows] = useState<StudentMarks[]>([]), [error, setError] = useState("");
  const latest = useRef(0);
  async function refresh() {
    const request = ++latest.current;
    try { const value = await api<StudentMarks[]>(`/admin/labs/${labId}/marks`);
      if (request === latest.current) { setRows(value); setError(""); } }
    catch (e) { if (request === latest.current) setError((e as Error).message); }
  }
  useAdminEvents(refresh);
  useEffect(() => { setRows([]); void refresh(); return () => { latest.current++; }; }, [labId]);
  const selected = rows.filter((row) => !accountId || row.id === accountId);
  const tasks = (rows[0]?.tasks || []).filter((task) => !taskId || task.task_id === taskId);
  return <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">Marks</h2>
    <button onClick={() => { void refresh(); }}>Refresh marks</button>
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Student</th>
      {tasks.map((task) => <th key={task.task_id}>{task.title}</th>)}{!taskId && <><th>Total</th><th>Active submissions</th></>}</tr></thead>
      <tbody>{selected.map((row) => <tr className="border-t" key={row.id}>
        <td><Link to={`/admin/labs/${labId}/students/${row.id}`}>{row.roll_number} · {row.name}</Link></td>
        {row.tasks.filter((task) => !taskId || task.task_id === taskId).map((task) => <td key={task.task_id}>
          {task.best_submission_id ? <Link to={`/admin/labs/${labId}/submissions/${task.best_submission_id}`}>{task.marks}</Link> : task.marks || "Pending"}
          {task.pending && task.marks !== null && <span className="block text-amber-800">Provisional · judging pending</span>}</td>)}
        {!taskId && <><td>{row.total}{row.pending && " (provisional)"}</td><td>{row.submission_count}</td></>}
      </tr>)}</tbody></table>{!selected.length && <p>No enrolled students.</p>}</div>
  </section>;
}

export function Corrections({ lab, task, csrf, refreshLab, onDirty }: { lab: AdminLab; task: Task; csrf: string;
  refreshLab: () => Promise<void>; onDirty: (dirty: boolean) => void }) {
  const [options, setOptions] = useState<{ id: string; number: number }[]>([]), [batches, setBatches] = useState<Batch[]>([]);
  const [revision, setRevision] = useState(""), [reason, setReason] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const latest = useRef(0);
  async function refresh() {
    const request = ++latest.current;
    try { const [values, library] = await Promise.all([api<Batch[]>(`/admin/labs/${lab.id}/corrections`),
        api<{ revisions: { id: string; number: number }[] }>(`/admin/tasks/${task.task_id}`)]);
      if (request === latest.current) { setBatches(values); setOptions(library.revisions); setError(""); } }
    catch (e) { if (request === latest.current) setError((e as Error).message); }
  }
  useAdminEvents(refresh);
  useEffect(() => {
    void refresh();
    return () => { latest.current++; };
  }, [lab.id, task.task_id]);
  useEffect(() => { onDirty(busy || !!revision || !!reason); }, [busy, revision, reason]);
  useEffect(() => () => onDirty(false), []);
  const history = batches.filter((batch) => batch.task_id === task.task_id), active = history.some((batch) => batch.state === 'judging');
  async function correct() {
    const warning = lab.first_released_at ? "Results have already been released. This changes current marks and keeps the lab closed. " : "";
    if (!confirm(`${warning}Rejudge every active submission for this task using the selected revision? Previous official results stay visible until the batch completes.`)) return;
    setBusy(true);
    try { await api(`/admin/labs/${lab.id}/tasks/${task.task_id}/corrections`, { method: 'POST',
      body: JSON.stringify({ version: lab.version, revision_id: revision, reason }) }, csrf);
      setRevision(""); setReason(""); await refreshLab(); await refresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">Task corrections</h2>
    <p>Publish a correction in the task library, then select its revision here.</p>
    <button onClick={() => { void refresh(); }}>Refresh corrections</button>
    <form onSubmit={(e) => { e.preventDefault(); void correct(); }}><fieldset disabled={busy || active || !['Running', 'Ended'].includes(lab.phase)} className="flex flex-wrap items-center gap-3">
      <label>Corrected revision <select required value={revision} onChange={(e) => setRevision(e.target.value)}>
        <option value="">Select revision</option>{options.filter((row) => row.id !== task.revision_id).map((row) => <option key={row.id} value={row.id}>Revision {row.number}</option>)}</select></label>
      <label>Correction reason <input required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      <button>Start correction batch</button>
    </fieldset></form>
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    {history.map((batch) => <p className={batch.delayed ? 'notice notice-warning' : ''} key={batch.id}>{batch.state === 'published' ? 'Published' : 'Judging'} · {batch.completed}/{batch.total} active submissions completed
      {batch.delayed > 0 && ` · ${batch.delayed} delayed: retry from submission pages`} · {new Date(batch.created_at).toLocaleString()}</p>)}
  </section>;
}
