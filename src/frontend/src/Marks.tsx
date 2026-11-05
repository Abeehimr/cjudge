import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { api } from "./api";
import { useAdminEvents } from "./Isolates";
import type { AdminLab, Task } from "./Lab";

type Mark = { task_id: string; revision_id: string; title: string; marks: string | null; pending: boolean; best_submission_id: string | null;
  maximum_marks?: string; ta_maximum?: string; ta_marks?: string | null };
export type StudentMarks = { id: string; roll_number: string; name: string; cancelled: boolean; tasks: Mark[]; total: string | null; pending: boolean; submission_count: number;
  ta_total?: string | null; combined_total?: string | null;
  ta_review?: { owner_name: string | null; reviewer_name: string | null; finalized: boolean; needs_recheck: boolean; provisional: boolean } };
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
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    <button onClick={() => { void refresh(); }}>Refresh marks</button>
    {!accountId && !taskId && <a download href={`/api/admin/labs/${labId}/marks.csv`}>Download final CSV</a>}
    <MarksTable rows={selected} tasks={tasks} labId={labId} taskId={taskId} />
  </section>;
}

export function MarksTable({ rows, tasks, labId, taskId, taStudentId }: {
  rows: StudentMarks[]; tasks: Mark[]; labId: string; taskId?: string; taStudentId?: string;
}) {
  const studentPath = taStudentId ? `/ta/labs/${labId}/students/${taStudentId}` : `/admin/labs/${labId}/students`;
  const hasTA = tasks.some((task) => Number(task.ta_maximum || 0) > 0);
  return <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Student</th>
      {tasks.map((task) => <th key={task.task_id}>{task.title}</th>)}{hasTA && <th>Review</th>}
      {!taskId && <>{hasTA && <th>Subtotal</th>}<th>Total</th><th>Active submissions</th></>}</tr></thead>
      {rows.map((row) => <tbody key={row.id} className="border-t">
        <tr data-cancelled={row.cancelled || undefined}>
          <td rowSpan={hasTA ? 2 : 1}>{taStudentId ? `${row.roll_number} · ${row.name}` : <Link to={`${studentPath}/${row.id}`}>{row.roll_number} · {row.name}</Link>}{row.cancelled && ' · Cancelled'}</td>
          {row.tasks.filter((task) => !taskId || task.task_id === taskId).map((task) => <td className="whitespace-nowrap" key={task.task_id}>
            {row.cancelled ? '—' : <>
              {task.best_submission_id ? <Link to={taStudentId ? `${studentPath}/submissions/${task.best_submission_id}` : `/admin/labs/${labId}/submissions/${task.best_submission_id}`}>{task.marks}</Link> : task.marks ?? "Pending"}
              {task.maximum_marks && <><strong> / </strong>{task.maximum_marks}</>}
              {task.pending && <span className="block text-amber-800">Provisional · judging pending</span>}
            </>}</td>)}
          {hasTA && <td rowSpan={2}>{row.ta_review?.finalized && row.ta_review.reviewer_name ? row.ta_review.reviewer_name
            : row.ta_review?.owner_name ? `Assigned to: ${row.ta_review.owner_name}` : 'Unassigned'}
            {!row.cancelled && row.ta_review?.provisional && <span className="block text-amber-800">Provisional review</span>}
            {row.ta_review?.needs_recheck && <span className="block text-amber-800">Needs recheck</span>}</td>}
          {!taskId && <>
            {hasTA && <td>{row.cancelled ? '—' : row.total}</td>}
            <td rowSpan={hasTA ? 2 : 1}>{row.cancelled ? '—' : hasTA ? <>
              <strong>{row.combined_total}</strong>
              {(row.pending || row.ta_review?.provisional || row.ta_review?.needs_recheck) && <span className="block text-amber-800">Provisional</span>}
            </> : <>{row.total}{row.pending && " (provisional)"}</>}</td>
            <td rowSpan={hasTA ? 2 : 1}>{row.submission_count}</td>
          </>}
        </tr>
        {hasTA && <tr className="border-t border-slate-100 bg-slate-50" data-cancelled={row.cancelled || undefined}>
          {row.tasks.filter((task) => !taskId || task.task_id === taskId).map((task) => <td className="whitespace-nowrap" key={task.task_id}>
            {row.cancelled || Number(task.ta_maximum || 0) <= 0 ? '—' : <>{task.ta_marks ?? 'Not marked'}<strong> / </strong>{task.ta_maximum}</>}
          </td>)}
          {!taskId && <td>{row.cancelled ? '—' : row.ta_total}</td>}
        </tr>}
      </tbody>)}</table>{!rows.length && <p>No enrolled students.</p>}</div>;

}

export function Corrections({ lab, task, csrf, refreshLab, onDirty, onSaved }: { lab: AdminLab; task: Task; csrf: string;
  refreshLab: () => Promise<void>; onDirty: (dirty: boolean) => void; onSaved: (lab: AdminLab) => void }) {
  const [options, setOptions] = useState<{ id: string; number: number }[]>([]), [batches, setBatches] = useState<Batch[]>([]);
  const [revision, setRevision] = useState(""), [reason, setReason] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const latest = useRef(0);
  async function refresh() {
    const request = ++latest.current;
    try { const [values, library] = await Promise.all([api<Batch[]>(`/admin/labs/${lab.id}/corrections`),
        api<{ revisions: { id: string; number: number }[] }>(`/admin/tasks/${task.task_id}`)]);
      if (request === latest.current) { setBatches(values); setOptions(library.revisions); } }
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
  const beforeStart = ['Draft', 'Scheduled'].includes(lab.phase);
  const editable = !lab.archived_at && ['Draft', 'Scheduled', 'Running', 'Ended', 'Results released'].includes(lab.phase);
  async function correct() {
    if (busy || active || !editable || !revision || revision === task.revision_id || !beforeStart && !reason.trim()) return;
    const warning = lab.first_released_at ? "Results have already been released. This changes current marks and keeps the lab closed. " : "";
    if (!beforeStart && !confirm(`${warning}Rejudge every active submission for this task using the selected revision? Previous official results stay visible until the batch completes.`)) return;
    setBusy(true); setError("");
    try {
      let updated: AdminLab;
      if (beforeStart) {
        updated = await api<AdminLab>(`/admin/labs/${lab.id}/tasks`, { method: 'PUT', body: JSON.stringify({
          version: lab.version, assignments: lab.tasks.map((item) => ({
            revision_id: item.task_id === task.task_id ? revision : item.revision_id,
            maximum_marks: item.maximum_marks, ta_maximum: item.ta_maximum,
          })),
        }) }, csrf);
      } else {
        let acknowledge = false;
        if (lab.reveal_results) {
          const warnings = await api<{ title: string }[]>(`/admin/labs/${lab.id}/release-warnings?revision_id=${encodeURIComponent(revision)}`);
          if (warnings.length) {
            acknowledge = confirm(`This correction reveals tests reused by scheduled labs: ${warnings.map((row) => row.title).join(", ")}. Continue?`);
            if (!acknowledge) return;
          }
        }
        await api(`/admin/labs/${lab.id}/tasks/${task.task_id}/corrections`, { method: 'POST',
          body: JSON.stringify({ version: lab.version, revision_id: revision, reason, acknowledge_reuse: acknowledge }) }, csrf);
        updated = await api<AdminLab>(`/admin/labs/${lab.id}`);
      }
      setRevision(""); setReason(""); onSaved(updated); await refresh(); }
    catch (e) {
      let message = (e as Error).message;
      if ((e as Error & { status?: number }).status === 409) {
        try { await refreshLab(); await refresh(); }
        catch (refreshError) { message += ` · ${(refreshError as Error).message}`; }
      }
      setError(message);
    }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">Task revision</h2>
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    <p>Assigned revision: <strong>Revision {task.number}</strong></p>
    <p>{lab.archived_at ? 'Archived lab: revision changes are locked.' : beforeStart
      ? 'Before start, change the assigned revision without rejudging. Task order and marks are preserved.'
      : 'After start, changing revision requires a reason and rejudges all active submissions.'} Publish revisions in the task library before selecting them here.</p>
    <button disabled={busy} onClick={() => { setError(""); void refresh(); }}>Refresh revisions</button>
    <form onSubmit={(e) => { e.preventDefault(); void correct(); }}><fieldset disabled={busy || active || !editable} className="flex flex-wrap items-center gap-3">
      <label>Published revision <select required value={revision} onChange={(e) => setRevision(e.target.value)}>
        <option value="">Select revision</option>{options.filter((row) => row.id !== task.revision_id).map((row) => <option key={row.id} value={row.id}>Revision {row.number}</option>)}</select></label>
      {!beforeStart && <label>Correction reason <input required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></label>}
      <button disabled={!revision || revision === task.revision_id || !beforeStart && !reason.trim()}>{beforeStart ? 'Change revision' : 'Change revision and rejudge'}</button>
    </fieldset></form>
    {history.map((batch) => <p className={batch.delayed ? 'notice notice-warning' : ''} key={batch.id}>{batch.state === 'published' ? 'Published' : 'Judging'} · {batch.completed}/{batch.total} active submissions completed
      {batch.delayed > 0 && ` · ${batch.delayed} delayed: retry from submission pages`} · {new Date(batch.created_at).toLocaleString()}</p>)}
  </section>;
}
