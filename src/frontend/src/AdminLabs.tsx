import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, NavLink, useMatch, useNavigate, useSearchParams } from "react-router";
import { api } from "./api";
import LabClock, { localDate } from "./LabClock";
import Statement from "./Statement";
import { AdminSubmissionDetail, AdminSubmissions, CompilerFeedback } from "./AdminSubmissions";
import { Announcements, type Summary, type AdminLab, type Enrollment, type Student, type Task } from "./Lab";
import { NotFound, useOffset, useUnsaved } from "./navigation";
import Release from "./Release";
import { Marks, Corrections } from "./Marks";
import { AdminScoreboard } from "./Scoreboard";
import TAAssignments, { AdminTADetail } from "./TAAssignments";
import { AdminTAReviews } from "./TAReviews";

export function AdminLabs({ csrf }: { csrf: string }) {
  const [rows, setRows] = useState<Summary[]>([]);
  const [offset, setOffset] = useOffset();
  const route = useMatch("/admin/labs/:labId/*"), listRoute = useMatch("/admin/labs"), navigate = useNavigate();
  const labId = route?.params.labId, parts = (route?.params["*"] || "").split("/").filter(Boolean);
  const section = parts[0] || "overview", studentId = section === "students" ? parts[1] : undefined, revisionId = section === "tasks" ? parts[1] : undefined;
  const submissionId = section === "submissions" ? parts[1] : undefined;
  const taId = section === "tas" ? parts[1] : undefined;
  const [params, setParams] = useSearchParams();
  const rosterSearch = params.get("search") || "";
  const frozenFilter = params.get('frozen') || '', cancelledFilter = params.get('cancelled') || '';
  function rosterFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  }
  const [destination, setDestination] = useState<string | null>(null);
  const currentLab = useRef(labId); currentLab.current = labId;
  const savedLab = useRef<AdminLab | null>(null);
  const [failure, setFailure] = useState(0);
  const [lab, setLab] = useState<AdminLab | null>(null);
  const [options, setOptions] = useState<Task[]>([]), [optionOffset, setOptionOffset] = useState(0), [moreOptions, setMoreOptions] = useState(true);
  const [publishedTask, setPublishedTask] = useState(''), [revisions, setRevisions] = useState<Task[]>([]);
  const [revisionOffset, setRevisionOffset] = useState(0), [moreRevisions, setMoreRevisions] = useState(false), [loadingRevisions, setLoadingRevisions] = useState(false);
  const [students, setStudents] = useState<Student[]>([]), [selectedStudentId, setStudentId] = useState(""), [search, setSearch] = useState("");
  const [selectedRoster, setSelectedRoster] = useState<string[]>([]);
  const [removalPreview, setRemovalPreview] = useState<{ version: number; students: Student[] } | null>(null);
  const [releasedCredential, setReleasedCredential] = useState<(Student & { password: string }) | null>(null);
  const [newTitle, setNewTitle] = useState(""), [title, setTitle] = useState(""), [strict, setStrict] = useState(false);
  const [taskIds, setTaskIds] = useState<string[]>([]), [taskId, setTaskId] = useState("");
  const [taskMarks, setTaskMarks] = useState<Record<string, string>>({}), [newTaskMarks, setNewTaskMarks] = useState('100.00');
  const [taskTAMarks, setTaskTAMarks] = useState<Record<string, string>>({}), [newTaskTAMarks, setNewTaskTAMarks] = useState('0.00');
  const [defaultDates] = useState(() => ({ start: localDate(null, 5), end: localDate(null, 125) }));
  function dateInput(value: string | null, minutes: number): string { return value ? localDate(value) : defaultDates[minutes === 5 ? "start" : "end"]; }
  const [start, setStart] = useState(defaultDates.start), [end, setEnd] = useState(defaultDates.end), [reason, setReason] = useState("");
  const [roll, setRoll] = useState(""), [name, setName] = useState(""), [announcement, setAnnouncement] = useState("");
  const [message, setMessageText] = useState(""), [busy, setBusy] = useState(false);
  const [messageError, setMessageError] = useState(false);
  function setMessage(text: string) { setMessageError(false); setMessageText(text); }
  function showError(text: string) { setMessageError(true); setMessageText(text); }
  const setupOpen = !!lab && (lab.phase === "Draft" || lab.phase === "Scheduled");
  const latestOptions = new Map<string, Task>();
  for (const option of options) {
    if (!latestOptions.has(option.task_id) || latestOptions.get(option.task_id)!.number < option.number) latestOptions.set(option.task_id, option);
  }
  const visibleRoster = studentId ? lab?.students.filter((row) => row.id === studentId) || [] :
    lab?.students.filter((row) => `${row.roll_number} ${row.name}`.toLowerCase().includes(rosterSearch.toLowerCase()) &&
      (!['yes', 'no'].includes(frozenFilter) || !!row.frozen === (frozenFilter === 'yes')) &&
      (!['yes', 'no'].includes(cancelledFilter) || !!row.cancelled === (cancelledFilter === 'yes'))) || [];
  const selectableRoster = setupOpen && !studentId;
  useEffect(() => { setSelectedRoster([]); setRemovalPreview(null); }, [labId, setupOpen]);
  function selectRoster(id: string) {
    setSelectedRoster((old) => old.includes(id) ? old.filter((key) => key !== id) : [...old, id]);
  }
  async function removeRoster(ids: string[], version: number) {
    if (!lab || !ids.length || !confirm(`Remove ${ids.length} student(s) from this lab? Global accounts and other labs are kept.${lab.phase === 'Scheduled' && ids.length === lab.students.length ? ' This removes the schedule and returns the lab to Draft.' : ''}`)) return;
    await perform(async () => {
      await mutate('/students/remove', 'POST', { version, ids });
      setSelectedRoster([]); setRemovalPreview(null); setMessage(`${ids.length} enrollment(s) removed.`);
    });
  }
  async function previewRemoval(file: File) {
    if (!lab) return;
    const id = lab.id, version = lab.version;
    setRemovalPreview(null);
    await perform(async () => {
      if (file.size > 1024 * 1024) throw new Error('CSV exceeds 1 MiB.');
      const preview = await api<{ version: number; students: Student[] }>(`/admin/labs/${id}/students/removal-preview?version=${version}`,
        { method: 'POST', body: file }, csrf);
      if (currentLab.current === id) setRemovalPreview(preview);
    });
  }
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  async function list(page = offset) { setRows(await api<Summary[]>(`/admin/labs?offset=${page}`)); }
  useEffect(() => { if (!labId) void list().catch((e) => showError(e.message)); }, [offset, labId]);
  useEffect(() => { if (destination) { navigate(destination); setDestination(null); } }, [destination]);
  useEffect(() => {
    setLab(null); setMessage(""); setFailure(0);
    if (!labId) return;
    const controller = new AbortController();
    void api<AdminLab>(`/admin/labs/${labId}`, { signal: controller.signal }).then(accept).catch((e) => { if (!controller.signal.aborted) { setFailure(e.status); showError(e.message); } });
    return () => controller.abort();
  }, [labId]);
  useEffect(() => { setReleasedCredential(null); }, [labId, section, studentId]);
  useEffect(() => {
    if (section !== "tasks" || revisionId || !labId) return;
    const controller = new AbortController();
    void api<Task[]>(`/admin/labs/task-options?offset=${optionOffset}`, { signal: controller.signal }).then((next) => {
      if (controller.signal.aborted) return;
      setOptions((old) => [...old, ...next.filter((row) => !old.some((item) => item.revision_id === row.revision_id))]); setMoreOptions(next.length === 100);
    }).catch((e) => { if (!controller.signal.aborted) showError(e.message); });
    return () => controller.abort();
  }, [optionOffset, section, revisionId, labId]);
  useEffect(() => {
    setPublishedTask(''); setTaskId(''); setRevisions([]); setRevisionOffset(0); setOptionOffset(0); setOptions([]);
  }, [labId]);
  useEffect(() => {
    if (!publishedTask) return;
    const controller = new AbortController(); setLoadingRevisions(true);
    void api<Task[]>(`/admin/labs/task-options?task_id=${encodeURIComponent(publishedTask)}&offset=${revisionOffset}`,
      { signal: controller.signal }).then((next) => {
      if (controller.signal.aborted) return;
      setRevisions((old) => revisionOffset ? [...old, ...next] : next);
      setOptions((old) => [...old, ...next.filter((row) => !old.some((item) => item.revision_id === row.revision_id))]);
      setMoreRevisions(next.length === 100);
      if (!revisionOffset) setTaskId(next[0]?.revision_id || '');
    }).catch((e) => { if (!controller.signal.aborted) showError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoadingRevisions(false); });
    return () => controller.abort();
  }, [publishedTask, revisionOffset]);
  useEffect(() => { if (labId && section === "students" && !studentId) void api<Student[]>("/admin/students").then(setStudents).catch((e) => showError(e.message)); }, [labId, section, studentId]);
  function accept(value: AdminLab, reset = false) {
    if (value.id !== currentLab.current) return;
    const previous = savedLab.current, keep = !reset && previous?.id === value.id;
    setLab(value);
    setSelectedRoster((old) => old.filter((id) => value.students.some((row) => row.id === id)));
    setTitle((old) => keep && old !== previous!.title ? old : value.title);
    setStrict((old) => keep && old !== previous!.strict_ip ? old : value.strict_ip);
    setTaskIds((old) => keep && JSON.stringify(old) !== JSON.stringify(previous!.tasks.map((t) => t.revision_id)) ? old : value.tasks.map((t) => t.revision_id));
    setTaskMarks((old) => ({...old, ...Object.fromEntries(value.tasks.map((t) => [t.revision_id, t.maximum_marks || '100.00']))}));
    setTaskTAMarks((old) => ({...old, ...Object.fromEntries(value.tasks.map((t) => [t.revision_id, t.ta_maximum || '0.00']))}));
    setStart((old) => keep && old !== dateInput(previous!.starts_at, 5) ? old : dateInput(value.starts_at, 5));
    setEnd((old) => keep && old !== dateInput(previous!.ends_at, 125) ? old : dateInput(value.ends_at, 125));
    savedLab.current = value;
  }
  async function reload(id = lab?.id) { if (id) accept(await api<AdminLab>(`/admin/labs/${id}`)); if (!labId) await list(); }
  async function perform(action: () => Promise<void>) {
    setBusy(true); setMessage("");
    try { await action(); } catch (e) { showError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function mutate(path: string, method: string, body?: object) {
    accept(await api<AdminLab>(`/admin/labs/${lab!.id}${path}`, { method, ...(body ? { body: JSON.stringify(body) } : {}) }, csrf));
    if (!labId) await list();
  }
  async function create(e: FormEvent) {
    e.preventDefault(); await perform(async () => {
      const result = await api<AdminLab>("/admin/labs", { method: "POST", body: JSON.stringify({ title: newTitle }) }, csrf);
      setNewTitle(""); setDestination(`/admin/labs/${result.id}`);
    });
  }
  async function upload(files: File[], replaces?: string) {
    if (!lab || !files.length) return;
    if (replaces && !confirm("Replace this PDF? Students receive an announcement during a running lab.")) return;
    await perform(async () => {
      let current = lab;
      for (const file of files) {
        if (file.size > 20 * 1024 * 1024) throw new Error(`${file.name} exceeds 20 MiB.`);
        current = await api<AdminLab>(`/admin/labs/${lab.id}/pdfs?version=${current.version}&name=${encodeURIComponent(file.name)}${replaces ? `&replaces=${replaces}` : ""}`,
          { method: "POST", body: file, headers: { "Content-Type": "application/pdf" } }, csrf);
        accept(current);
      }
    });
  }
  async function rosterAction(member: Enrollment, action: "freeze" | "release") {
    if (action === "release" && !confirm(`Release ${member.roll_number}'s browser and reset their password? All their login sessions will end.`)) return;
    const why = prompt(action === "release" ? "Reason for browser release" : `Reason to ${member.frozen ? "unfreeze" : "freeze"} submissions`);
    if (!why?.trim()) return;
    if (action === "release") setReleasedCredential(null);
    await perform(async () => {
      const result = await api<Student & { password: string }>(`/admin/labs/${lab!.id}/students/${member.id}/${action}`, { method: "POST",
        body: JSON.stringify({ reason: why.trim(), ...(action === "freeze" ? { frozen: !member.frozen } : {}) }) }, csrf);
      if (action === "release") setReleasedCredential(result);
      await reload();
    });
  }
  async function cancellation(member: Enrollment) {
    const verb = member.cancelled ? 'Reinstate' : 'Cancel';
    if (!confirm(`${verb} ${member.roll_number}'s lab participation? Existing submissions remain as evidence.`)) return;
    const reason = prompt(`Reason to ${verb.toLowerCase()} participation`);
    if (!reason?.trim()) return;
    await perform(async () => {
      await api(`/admin/labs/${lab!.id}/students/${member.id}/cancellation`, { method: 'PUT',
        body: JSON.stringify({ version: lab!.version, cancelled: !member.cancelled, reason: reason.trim() }) }, csrf);
      await reload();
    });
  }
  function move(index: number, delta: number) {
    const next = [...taskIds]; [next[index], next[index + delta]] = [next[index + delta], next[index]]; setTaskIds(next);
  }
  const member = lab?.students.find((item) => item.id === studentId);
  const task = lab?.tasks.find((item) => item.revision_id === revisionId || item.previous_revision_ids?.includes(revisionId || ''));
  const [feedbackDirty, setFeedbackDirty] = useState(false);
  const [correctionDirty, setCorrectionDirty] = useState(false);
  useEffect(() => {
    if (lab && lab.id === labId) accept(lab, true);
    setRoll(""); setName(""); setReason(""); setAnnouncement("");
  }, [section, studentId, revisionId]);
  const dirty = busy || feedbackDirty || correctionDirty || !!newTitle || (!!lab && (section === 'overview' && (title !== lab.title || strict !== lab.strict_ip ||
    start !== dateInput(lab.starts_at, 5) || end !== dateInput(lab.ends_at, 125) || !!reason || !!announcement) ||
    section === 'tasks' && !revisionId && JSON.stringify(taskIds) !== JSON.stringify(lab.tasks.map((t) => t.revision_id)) ||
    section === 'students' && (!!roll || !!name)));
  useUnsaved(dirty);
  if ((!route && !listRoute) || parts.length > 2 || !['overview', 'students', 'tasks', 'submissions', 'scoreboard', 'tas', 'reviews'].includes(section) ||
      section === 'overview' && parts.length > 0 || section === 'scoreboard' && parts.length !== 1 || [404, 422].includes(failure) || lab && (studentId && !member || revisionId && !task)) return <NotFound />;
  return <div className="space-y-4">
    <h1 className="text-xl font-semibold">{labId ? lab?.title || "Lab" : "Labs"}</h1>
    {!labId && <><form onSubmit={create} className="flex flex-wrap gap-2 rounded border bg-white p-4">
      <label>New lab title <input required maxLength={160} value={newTitle} onChange={(e) => setNewTitle(e.target.value)} /></label><button disabled={busy || !!lab?.archived_at}>Create lab</button>
    </form>
    <section className="overflow-x-auto rounded border bg-white p-4"><table className="w-full text-left text-sm"><thead><tr><th>Lab</th><th>Status</th><th>Start</th><th>Deadline</th></tr></thead>
      <tbody>{rows.map((row) => <tr className="border-t" key={row.id}><td><Link to={`/admin/labs/${row.id}`}>{row.title}</Link></td>
        <td>{row.phase}</td><td>{row.starts_at ? new Date(row.starts_at).toLocaleString() : "—"}</td><td>{row.ends_at ? new Date(row.ends_at).toLocaleString() : "—"}</td></tr>)}</tbody></table>
      <button disabled={busy || !offset} onClick={() => setOffset(offset - 100)}>Previous labs</button>{" "}
      <button disabled={busy || rows.length < 100} onClick={() => setOffset(offset + 100)}>Next labs</button>
    </section>
    </>}
    {labId && !lab && !message && <p role="status">Loading lab…</p>}
    {lab && <>
      <nav aria-label="Lab breadcrumbs"><Link to="/admin/labs">Labs</Link> / <Link to={`/admin/labs/${lab.id}`}>{lab.title}</Link>{studentId && ` / ${member?.roll_number}`}{revisionId && ` / ${task?.config.title}`}{taId && ` / ${lab.tas?.find((ta) => ta.id === taId)?.username || 'TA'}`}</nav>
      <nav aria-label="Lab navigation" className="flex flex-wrap gap-2">{[["", "Overview"], ["students", "Students"], ["tasks", "Tasks"], ["tas", "TAs"], ["reviews", "TA Reviews"], ["submissions", "Submissions"], ["scoreboard", "Scoreboard"]].map(([path, title]) => <NavLink end={!path} className="nav-link" key={path} to={`/admin/labs/${lab.id}${path ? "/" + path : ""}`}>{title}</NavLink>)}</nav>
      <section className="rounded border bg-white p-4"><div className="flex justify-between"><h2 className="font-semibold">{lab.title} · {lab.phase}</h2>
        <button disabled={busy} onClick={() => perform(() => reload())}>Refresh lab</button></div>
        <LabClock serverTime={lab.server_time} start={lab.starts_at} end={lab.ends_at} refresh={() => { void reload().catch((e) => showError(e.message)); }} />
      </section>
      {section === 'scoreboard' && <>
        <section className="rounded border bg-white p-4"><button aria-pressed={!!lab.scoreboard_visible} disabled={busy || !!lab.archived_at}
          onClick={() => perform(async () => {
            await api(`/admin/labs/${lab.id}/scoreboard/visibility`, { method: 'PUT', body: JSON.stringify({ version: lab.version, visible: !lab.scoreboard_visible }) }, csrf);
            await reload();
          })}>Visible to participants: {lab.scoreboard_visible ? 'On' : 'Off'}</button>
          <p className="mt-2 text-sm">Enabling shows live marks and times before results release. Students can open only their own submissions.</p>
        </section>
        <AdminScoreboard lab={lab} refreshLab={() => reload()} />
      </>}
      {section === "overview" && <>
      <Release lab={lab} csrf={csrf} accept={accept} deleted={() => setDestination("/admin/labs")} />
      <section className="rounded border bg-white p-4"><button aria-pressed={!!lab.early_feedback_visible} disabled={busy || !!lab.archived_at}
        onClick={() => { if (!lab.early_feedback_visible && !confirm('Show passed/total counts and marks before release for partial-scoring tasks?')) return;
          void perform(() => mutate('/early-feedback/visibility', 'PUT', { version: lab.version, visible: !lab.early_feedback_visible }));
        }}>Early results feedback: {lab.early_feedback_visible ? 'On' : 'Off'}</button>
        <p className="mt-2 text-sm">Students see only their own official counts. Pending rejudges mark counts provisional; source and testcases stay hidden until release.</p>
      </section>
      <form onSubmit={(e) => { e.preventDefault(); void perform(() => mutate("", "PUT", { version: lab.version, title, strict_ip: strict })); }} className="rounded border bg-white p-4">
        <fieldset disabled={busy || !setupOpen} className="space-y-2"><legend className="font-semibold">Lab settings</legend>
          <label className="block">Lab title <input required maxLength={160} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
          <label className="block"><input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} /> Require original client IP</label>
          <button>Save lab settings</button>
        </fieldset>
      </form>
      </>}
      {section === "tasks" && !revisionId && <>
      <section className="rounded border bg-white p-4"><h2 className="font-semibold">Ordered tasks</h2>
        <fieldset disabled={busy || !setupOpen} className="space-y-2">
          <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Order</th><th>Task</th><th>Revision</th><th>Automatic maximum</th><th>TA maximum</th><th>Actions</th></tr></thead>
            <tbody>{taskIds.map((id, index) => { const item = options.find((o) => o.revision_id === id) || lab.tasks.find((t) => t.revision_id === id);
              return <tr className="border-t" key={id}><td>{index + 1}</td><td><Link to={`/admin/labs/${lab.id}/tasks/${id}`}>{item?.config.title || id}</Link></td>
                <td>{item?.number}</td><td>{taskMarks[id]}</td><td>{taskTAMarks[id] || '0.00'}</td><td>
                <button disabled={!index} onClick={() => move(index, -1)} aria-label={`Move task ${index + 1} up`}>↑</button>
                <button disabled={index === taskIds.length - 1} onClick={() => move(index, 1)} aria-label={`Move task ${index + 1} down`}>↓</button>
                <button onClick={() => setTaskIds(taskIds.filter((value) => value !== id))}>Remove task {index + 1}</button></td></tr>; })}</tbody></table></div>
          <label>Published task <select value={publishedTask} onChange={(e) => { setPublishedTask(e.target.value); setTaskId(''); setRevisions([]); setRevisionOffset(0); }}><option value="">Select task</option>
            {[...latestOptions.values()].map((option) =>
              <option key={option.task_id} value={option.task_id}>{option.config.title}</option>)}</select></label>{" "}
          <label>Published revision <select disabled={!publishedTask || loadingRevisions} value={taskId} onChange={(e) => setTaskId(e.target.value)}><option value="">Select revision</option>
            {revisions.map((option, index) => <option key={option.revision_id} value={option.revision_id}>Revision {option.number}{index === 0 ? ' · Latest' : ''}</option>)}</select></label>{" "}
          {moreRevisions && <button disabled={loadingRevisions} onClick={() => setRevisionOffset(revisionOffset + 100)}>Load older revisions</button>}
          <label>Maximum marks <input type="number" min="0.01" max="10000" step="0.01" value={newTaskMarks} onChange={(e) => setNewTaskMarks(e.target.value)} /></label>{" "}
          <label>TA maximum <input type="number" min="0" max="10000" step="0.01" value={newTaskTAMarks} onChange={(e) => setNewTaskTAMarks(e.target.value)} /></label>{" "}
          <button disabled={!taskId || loadingRevisions || taskIds.some((id) => (options.find((option) => option.revision_id === id) || lab.tasks.find((item) => item.revision_id === id))?.task_id === publishedTask) || !newTaskMarks || Number(newTaskMarks) <= 0 || Number(newTaskMarks) > 10000 || !newTaskTAMarks || Number(newTaskTAMarks) < 0 || Number(newTaskTAMarks) > 10000} onClick={() => { setTaskIds([...taskIds, taskId]); setTaskMarks({...taskMarks, [taskId]: newTaskMarks}); setTaskTAMarks({...taskTAMarks, [taskId]: newTaskTAMarks}); setTaskId(""); setPublishedTask(''); setRevisions([]); }}>Add task</button>{" "}
          <button onClick={() => perform(() => mutate("/tasks", "PUT", { version: lab.version, assignments: taskIds.map((revision_id) => ({revision_id, maximum_marks: taskMarks[revision_id], ta_maximum: taskTAMarks[revision_id]})) }))}>Save task order</button>
        </fieldset>
        {moreOptions && <button onClick={() => setOptionOffset(optionOffset + 100)}>Load more tasks</button>}
      </section>
      </>}
      {section === "overview" && <>
      <section className="rounded border bg-white p-4"><h2 className="font-semibold">Schedule ({zone})</h2>
        {setupOpen ? <form onSubmit={(e) => { e.preventDefault(); void perform(() => mutate("/schedule", "POST", {
          version: lab.version, starts_at: new Date(start).toISOString(), ends_at: new Date(end).toISOString(),
        })); }}><fieldset disabled={busy || !!lab?.archived_at} className="flex flex-wrap gap-3">
          <label>Starts at <input type="datetime-local" required value={start} onChange={(e) => setStart(e.target.value)} /></label>
          <label>Ends at <input type="datetime-local" required value={end} onChange={(e) => setEnd(e.target.value)} /></label>
          <button>{lab.phase === "Draft" ? "Schedule lab" : "Reschedule lab"}</button>
          <button type="button" onClick={() => perform(() => mutate("/schedule", "POST", { version: lab.version, ends_at: new Date(end).toISOString() }))}>Start now</button>
        </fieldset></form> : !lab.first_released_at && <form onSubmit={(e) => { e.preventDefault();
          if (confirm(`${lab.phase === "Ended" ? "Reopen" : "Extend"} this lab for all students?`)) void perform(async () => {
            await mutate("/deadline", "POST", { version: lab.version, action: lab.phase === "Ended" ? "reopen" : "extend",
              ends_at: new Date(end).toISOString(), reason }); setReason("");
          }); }}><fieldset disabled={busy || !!lab?.archived_at} className="flex flex-wrap gap-3">
            <label>New deadline <input type="datetime-local" required value={end} onChange={(e) => setEnd(e.target.value)} /></label>
            <label>Deadline reason <input required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
            <button>{lab.phase === "Ended" ? "Reopen lab" : "Extend lab"}</button>
          </fieldset></form>}
        {lab.phase === "Running" && <button disabled={busy || !!lab?.archived_at} onClick={() => {
          if (!confirm("Stop this lab now? New submissions will close. Accepted submissions continue judging.")) return;
          const why = prompt("Reason for stopping the lab"); if (!why?.trim()) return;
          void perform(() => mutate("/stop", "POST", { version: lab.version, reason: why.trim() }));
        }}>Stop now</button>}
      </section>
      <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">Lab PDFs</h2>
        <fieldset disabled={busy || lab.phase === "Ended" || !!lab.first_released_at}><label>Upload lab PDFs (up to 10, 20 MiB each)
          <input className="mt-1 block" type="file" accept=".pdf,application/pdf" multiple onChange={(e) => { void upload(Array.from(e.target.files || [])); e.target.value = ""; }} /></label></fieldset>
        <ul className="space-y-2">{lab.pdfs.map((pdf) => <li className="flex flex-wrap items-center gap-2" key={pdf.id}>
          <a download href={`/api/admin/labs/${lab.id}/pdfs/${pdf.id}`}>{pdf.name}</a> <span>{Math.ceil(pdf.size / 1024)} KiB · {pdf.active ? "Current" : "Previous version"}</span>
          {pdf.active && <><label>Replace {pdf.name}<input type="file" accept=".pdf,application/pdf" disabled={busy || lab.phase === "Ended" || !!lab.first_released_at}
            onChange={(e) => { if (e.target.files?.[0]) void upload([e.target.files[0]], pdf.id); e.target.value = ""; }} /></label>
            {setupOpen && <button disabled={busy || !!lab?.archived_at} onClick={() => { if (confirm(`Remove ${pdf.name} from this lab?`)) void perform(() => mutate(`/pdfs/${pdf.id}?version=${lab.version}`, "DELETE")); }}>Remove PDF</button>}</>}
        </li>)}</ul>
      </section>
      <CompilerFeedback labId={lab.id} csrf={csrf} feedback={lab.compiler_feedback} refreshLab={() => reload()} onDirty={setFeedbackDirty} />
      </>}
      {section === "students" && <>
      {releasedCredential && <section className="rounded border bg-white p-4" aria-label="New student credential">
        <div className="flex justify-between"><h2 className="font-semibold">New credential for {releasedCredential.roll_number}</h2>
          <div className="flex gap-3"><button onClick={() => print()}>Print</button><button onClick={() => setReleasedCredential(null)}>Hide</button></div></div>
        <p>{releasedCredential.name} · Password: <strong className="font-mono">{releasedCredential.password}</strong></p>
        <p className="text-sm">Give this password to the student. Their old password and sessions no longer work.</p>
      </section>}
      <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">{studentId ? `${member?.roll_number} · ${member?.name}` : `Enrollment (${lab.students.length})`}</h2>
        {!studentId && <>
        <form onSubmit={(e) => { e.preventDefault(); void perform(async () => setStudents(await api<Student[]>(`/admin/students?search=${encodeURIComponent(search)}`))); }} className="flex flex-wrap gap-2">
          <label>Find student <input value={search} onChange={(e) => setSearch(e.target.value)} maxLength={64} /></label><button disabled={busy || !!lab?.archived_at}>Search students</button>
        </form>
        <fieldset disabled={busy || !!lab?.first_released_at || !!lab?.archived_at} className="flex flex-wrap gap-2"><label>Existing student <select value={selectedStudentId} onChange={(e) => setStudentId(e.target.value)}>
          <option value="">Select student</option>{students.filter((s) => !lab.students.some((m) => m.id === s.id)).map((s) => <option key={s.id} value={s.id}>{s.roll_number} · {s.name}</option>)}</select></label>
          <button disabled={!selectedStudentId} onClick={() => perform(async () => { await mutate("/students", "POST", { version: lab.version, ids: [selectedStudentId] }); setStudentId(""); })}>Enroll selected student</button>
        </fieldset>
        <form onSubmit={(e) => { e.preventDefault(); void perform(async () => {
          await mutate("/students/manual", "POST", { version: lab.version, roll_number: roll, name }); setRoll(""); setName("");
        }); }}><fieldset disabled={busy || !!lab?.first_released_at || !!lab?.archived_at} className="flex flex-wrap gap-2">
          <label>Student roll number <input required maxLength={64} value={roll} onChange={(e) => setRoll(e.target.value)} /></label>
          <label>Student name <input required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></label><button>Find or create and enroll</button>
        </fieldset></form>
        <label>Import roster CSV (roll_number,name)<input type="file" accept=".csv,text/csv" disabled={busy || !!lab?.first_released_at || !!lab?.archived_at} className="mt-1 block" onChange={(e) => {
          const file = e.target.files?.[0]; e.target.value = "";
          if (file) void perform(async () => {
            const result = await api<{ created: string[]; existing: string[]; name_mismatches: string[]; enrolled: string[]; already_enrolled: string[]; skipped: { roll_number: string; lab_id: string; lab_title: string; phase: string }[] }>(`/admin/labs/${lab.id}/students/import?version=${lab.version}`, { method: "POST", body: file }, csrf);
            await reload(); setMessage(`${result.enrolled.length} enrolled; ${result.already_enrolled.length} already enrolled; ${result.skipped.length} skipped. Name mismatches: ${result.name_mismatches.join(", ") || "none"}. ${result.skipped.map((row) => `${row.roll_number}: ${row.lab_title} (${row.phase})`).join('; ')}`);
          });
        }} /></label>
        {setupOpen && <section className="space-y-2 rounded border p-3" aria-label="Remove enrollments">
          <p role="status">{selectedRoster.length} selected{selectedRoster.length > 1000 && ' · Select at most 1,000 students.'}</p>
          <button disabled={busy || !selectedRoster.length || selectedRoster.length > 1000} onClick={() => { void removeRoster(selectedRoster, lab.version); }}>Remove selected</button>
          <label className="block">Remove roster CSV (roll_number; optional name)<input type="file" accept=".csv,text/csv" disabled={busy} onChange={(e) => {
            const file = e.target.files?.[0]; e.target.value = ''; if (file) void previewRemoval(file);
          }} /></label>
          {removalPreview && <div aria-label="Removal preview">
            <p>{removalPreview.students.length} enrollment(s) matched. Names come from current accounts.</p>
            <ul className="max-h-48 overflow-y-auto">{removalPreview.students.map((row) => <li key={row.id}>{row.roll_number} · {row.name}</li>)}</ul>
            {removalPreview.version !== lab.version && <p role="alert">Lab changed. Upload the CSV again before confirming.</p>}
            <button disabled={busy || removalPreview.version !== lab.version} onClick={() => { void removeRoster(removalPreview.students.map((row) => row.id), removalPreview.version); }}>Confirm CSV removal</button>
            <button disabled={busy} onClick={() => setRemovalPreview(null)}>Discard preview</button>
          </div>}
        </section>}
        <div className="flex flex-wrap gap-3"><label>Filter roster <input value={rosterSearch} onChange={(e) => rosterFilter('search', e.target.value)} /></label>
          <label>Frozen <select value={frozenFilter} onChange={(e) => rosterFilter('frozen', e.target.value)}><option value="">All</option><option value="yes">Yes</option><option value="no">No</option></select></label>
          <label>Cancelled <select value={cancelledFilter} onChange={(e) => rosterFilter('cancelled', e.target.value)}><option value="">All</option><option value="yes">Yes</option><option value="no">No</option></select></label></div>
        </>}
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr>{selectableRoster && <th><input type="checkbox" aria-label="Select all visible students" disabled={busy || !visibleRoster.length}
            checked={visibleRoster.length > 0 && visibleRoster.every((row) => selectedRoster.includes(row.id))}
            onChange={(e) => setSelectedRoster((old) => e.target.checked ? [...new Set([...old, ...visibleRoster.map((row) => row.id)])] : old.filter((id) => !visibleRoster.some((row) => row.id === id)))} /></th>}<th>Roll number</th><th>Name</th><th>Browser / IP</th><th>Submissions</th><th>Actions</th></tr></thead>
          <tbody>{visibleRoster.map((member) => <tr className={`border-t ${selectableRoster ? 'cursor-pointer focus-visible:outline' : ''}`} data-frozen={member.frozen || undefined} data-cancelled={member.cancelled || undefined} key={member.id}
            tabIndex={selectableRoster ? 0 : undefined} aria-selected={selectableRoster ? selectedRoster.includes(member.id) : undefined}
            onClick={(e) => { if (selectableRoster && !busy && !(e.target as HTMLElement).closest('a,button,input,select,label')) selectRoster(member.id); }}
            onKeyDown={(e) => { if (selectableRoster && !busy && e.target === e.currentTarget && ['Enter', ' '].includes(e.key)) { e.preventDefault(); selectRoster(member.id); } }}>{selectableRoster && <td><input type="checkbox" aria-label={`Select ${member.roll_number}`} disabled={busy}
              checked={selectedRoster.includes(member.id)} onChange={() => selectRoster(member.id)} /></td>}<td><Link to={`/admin/labs/${lab.id}/students/${member.id}`}>{member.roll_number}</Link></td><td>{member.name}</td>
            <td>{member.bound_at ? `Bound · ${member.last_ip}` : "Not bound"}{member.ip_changed && <span className="block">IP changed (original {member.bound_ip})</span>}</td>
            <td><span className={member.cancelled ? 'notice-danger rounded px-2 py-1' : member.frozen ? "notice-warning rounded px-2 py-1" : ""}>{member.cancelled ? `Cancelled by ${member.cancelled_by_name || "admin"} · ${member.cancel_reason}` : member.frozen ? `Frozen by ${member.frozen_by_name || "admin"} · ${member.freeze_reason}` : "Enabled during lab"}</span></td><td><div className="flex flex-wrap gap-2">
              <button disabled={busy || !!lab?.archived_at} onClick={() => rosterAction(member, "freeze")}>{member.frozen ? "Unfreeze" : "Freeze"} {member.roll_number}</button>
              <button disabled={busy || !!lab?.archived_at} onClick={() => { void cancellation(member); }}>{member.cancelled ? 'Reinstate' : 'Cancel'} {member.roll_number}</button>
              <button disabled={busy || !member.bound_at} onClick={() => rosterAction(member, "release")}>Release browser {member.roll_number}</button>
              {setupOpen && <button disabled={busy || !!lab?.archived_at} onClick={() => { if (confirm(`Remove ${member.roll_number} from enrollment?${lab.phase === 'Scheduled' && lab.students.length === 1 ? ' This removes the schedule and returns the lab to Draft.' : ''}`)) void perform(async () => { await mutate(`/students/${member.id}?version=${lab.version}`, "DELETE"); if (studentId) setDestination(`/admin/labs/${lab.id}/students`); }); }}>Remove student</button>}
            </div></td></tr>)}</tbody></table></div>
      </section>
      </>}
      {section === "overview" && <>
      <form onSubmit={(e) => { e.preventDefault(); void perform(async () => { await mutate("/announcements", "POST", { body: announcement }); setAnnouncement(""); }); }} className="rounded border bg-white p-4">
        <label className="block">Message to lab<textarea required maxLength={4000} rows={3} value={announcement} onChange={(e) => setAnnouncement(e.target.value)} className="mt-1 block w-full" /></label>
        <button disabled={busy || !!lab?.archived_at}>Post announcement</button>
      </form>
      <Announcements messages={lab.announcements} />
      </>}
      {section === "tas" && (taId ? <AdminTADetail labId={lab.id} taId={taId} /> : <TAAssignments lab={lab} csrf={csrf} onSave={accept} />)}
      {section === "reviews" && <AdminTAReviews labId={lab.id} csrf={csrf} archived={!!lab.archived_at} tas={lab.tas || []} />}
      {revisionId && task && <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">{task.config.title} · revision {task.number}</h2>
        <p>{task.maximum_marks} marks · CPU {task.config.cpu_seconds}s · Wall {task.config.wall_seconds}s · Memory {task.config.memory_mib} MiB</p>
        {!lab.archived_at && <form key={`${task.task_id}-${task.maximum_marks}`} onSubmit={(event) => { event.preventDefault(); const form = event.currentTarget; const maximum_marks = (form.elements.namedItem('maximum_marks') as HTMLInputElement).value; const reason = (form.elements.namedItem('reason') as HTMLInputElement).value; void perform(() => mutate(`/tasks/${task.task_id}/maximum`, 'PUT', {version: lab.version, maximum_marks, reason})); }} className="flex flex-wrap gap-2">
          <label>Maximum marks <input name="maximum_marks" type="number" min="0.01" max="10000" step="0.01" defaultValue={task.maximum_marks || ''} required /></label>
          <label>Reason <input name="reason" maxLength={500} required /></label><button disabled={busy}>Change marks</button>
        </form>}
        <p>TA maximum: {task.ta_maximum || "0.00"}</p>
        {!lab.archived_at && <form key={`${task.task_id}-${task.ta_maximum}`} onSubmit={(event) => { event.preventDefault();
          const form = event.currentTarget; const ta_maximum = (form.elements.namedItem('ta_maximum') as HTMLInputElement).value;
          const reason = (form.elements.namedItem('reason') as HTMLInputElement).value;
          void perform(() => mutate(`/tasks/${task.task_id}/ta-maximum`, 'PUT', { version: lab.version, ta_maximum, reason }));
        }} className="flex flex-wrap gap-2">
          <label>TA maximum <input name="ta_maximum" type="number" min={lab.first_released_at ? "0.01" : "0"}
            max="10000" step="0.01" defaultValue={task.ta_maximum || "0.00"} required /></label>
          <label>Reason <input name="reason" maxLength={500} required /></label><button disabled={busy}>Change TA marks</button>
        </form>}
        <Statement text={task.config.statement} /><p><Link to={`/admin/tasks/${task.task_id}?revision=${task.revision_id}`}>View library revision and cases</Link></p>
      </section>}
      {(section === 'overview' || studentId || task) && <Marks labId={lab.id} accountId={studentId} taskId={task?.task_id} />}
      {task && !lab.archived_at && <Corrections key={task.task_id} lab={lab} task={task} csrf={csrf} refreshLab={() => reload()} onDirty={setCorrectionDirty} />}
      {submissionId && <AdminSubmissionDetail key={submissionId} labId={lab.id} submissionId={submissionId} csrf={csrf} released={!!lab.first_released_at} archived={!!lab.archived_at} />}
      {(!submissionId && section === 'submissions' || studentId || revisionId) && <AdminSubmissions key={`${lab.id}/${studentId || revisionId || 'all'}`} labId={lab.id} csrf={csrf}
        tasks={lab.tasks.map((t) => ({ revision_id: t.revision_id, title: t.config.title }))} students={lab.students} accountId={studentId} revisionId={revisionId} />}
    </>}
    {message && <p role={messageError ? "alert" : "status"} className={`notice ${messageError ? "notice-danger" : "notice-warning"}`}>{message}</p>}
  </div>;
}
