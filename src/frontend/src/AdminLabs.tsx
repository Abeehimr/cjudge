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

export function AdminLabs({ csrf }: { csrf: string }) {
  const [rows, setRows] = useState<Summary[]>([]);
  const [offset, setOffset] = useOffset();
  const route = useMatch("/admin/labs/:labId/*"), listRoute = useMatch("/admin/labs"), navigate = useNavigate();
  const labId = route?.params.labId, parts = (route?.params["*"] || "").split("/").filter(Boolean);
  const section = parts[0] || "overview", studentId = section === "students" ? parts[1] : undefined, revisionId = section === "tasks" ? parts[1] : undefined;
  const submissionId = section === "submissions" ? parts[1] : undefined;
  const [params, setParams] = useSearchParams();
  const rosterSearch = params.get("search") || "";
  const [destination, setDestination] = useState<string | null>(null);
  const currentLab = useRef(labId); currentLab.current = labId;
  const savedLab = useRef<AdminLab | null>(null);
  const [failure, setFailure] = useState(0);
  const [lab, setLab] = useState<AdminLab | null>(null);
  const [options, setOptions] = useState<Task[]>([]), [optionOffset, setOptionOffset] = useState(0), [moreOptions, setMoreOptions] = useState(true);
  const [students, setStudents] = useState<Student[]>([]), [selectedStudentId, setStudentId] = useState(""), [search, setSearch] = useState("");
  const [releasedCredential, setReleasedCredential] = useState<(Student & { password: string }) | null>(null);
  const [newTitle, setNewTitle] = useState(""), [title, setTitle] = useState(""), [strict, setStrict] = useState(false);
  const [taskIds, setTaskIds] = useState<string[]>([]), [taskId, setTaskId] = useState("");
  const [defaultDates] = useState(() => ({ start: localDate(null, 5), end: localDate(null, 125) }));
  function dateInput(value: string | null, minutes: number): string { return value ? localDate(value) : defaultDates[minutes === 5 ? "start" : "end"]; }
  const [start, setStart] = useState(defaultDates.start), [end, setEnd] = useState(defaultDates.end), [reason, setReason] = useState("");
  const [roll, setRoll] = useState(""), [name, setName] = useState(""), [announcement, setAnnouncement] = useState("");
  const [message, setMessageText] = useState(""), [busy, setBusy] = useState(false);
  const [messageError, setMessageError] = useState(false);
  function setMessage(text: string) { setMessageError(false); setMessageText(text); }
  function showError(text: string) { setMessageError(true); setMessageText(text); }
  const setupOpen = !!lab && (lab.phase === "Draft" || lab.phase === "Scheduled");
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
    void api<Task[]>(`/admin/labs/task-options?offset=${optionOffset}`).then((next) => {
      setOptions((old) => optionOffset ? [...old, ...next.filter((row) => !old.some((item) => item.revision_id === row.revision_id))] : next); setMoreOptions(next.length === 100);
    }).catch((e) => showError(e.message));
  }, [optionOffset, section, revisionId, labId]);
  useEffect(() => { if (labId && section === "students" && !studentId) void api<Student[]>("/admin/students").then(setStudents).catch((e) => showError(e.message)); }, [labId, section, studentId]);
  function accept(value: AdminLab, reset = false) {
    if (value.id !== currentLab.current) return;
    const previous = savedLab.current, keep = !reset && previous?.id === value.id;
    setLab(value);
    setTitle((old) => keep && old !== previous!.title ? old : value.title);
    setStrict((old) => keep && old !== previous!.strict_ip ? old : value.strict_ip);
    setTaskIds((old) => keep && JSON.stringify(old) !== JSON.stringify(previous!.tasks.map((t) => t.revision_id)) ? old : value.tasks.map((t) => t.revision_id));
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
  if ((!route && !listRoute) || parts.length > 2 || !['overview', 'students', 'tasks', 'submissions', 'scoreboard'].includes(section) ||
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
      <nav aria-label="Lab breadcrumbs"><Link to="/admin/labs">Labs</Link> / <Link to={`/admin/labs/${lab.id}`}>{lab.title}</Link>{studentId && ` / ${member?.roll_number}`}{revisionId && ` / ${task?.config.title}`}</nav>
      <nav aria-label="Lab navigation" className="flex flex-wrap gap-2">{[["", "Overview"], ["students", "Students"], ["tasks", "Tasks"], ["submissions", "Submissions"], ["scoreboard", "Scoreboard"]].map(([path, title]) => <NavLink end={!path} className="nav-link" key={path} to={`/admin/labs/${lab.id}${path ? "/" + path : ""}`}>{title}</NavLink>)}</nav>
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
        onClick={() => { if (!lab.early_feedback_visible && !confirm('Show passed/total counts before release for partial-scoring tasks?')) return;
          void perform(() => mutate('/early-feedback/visibility', 'PUT', { version: lab.version, visible: !lab.early_feedback_visible }));
        }}>Early passed/total feedback: {lab.early_feedback_visible ? 'On' : 'Off'}</button>
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
          <ol>{taskIds.map((id, index) => { const item = options.find((o) => o.revision_id === id) || lab.tasks.find((t) => t.revision_id === id);
            return <li className="flex flex-wrap items-center gap-2 border-t py-2" key={id}>{index + 1}. <Link to={`/admin/labs/${lab.id}/tasks/${id}`}>{item?.config.title || id}</Link> · revision {item?.number}
              <button disabled={!index} onClick={() => move(index, -1)} aria-label={`Move task ${index + 1} up`}>↑</button>
              <button disabled={index === taskIds.length - 1} onClick={() => move(index, 1)} aria-label={`Move task ${index + 1} down`}>↓</button>
              <button onClick={() => setTaskIds(taskIds.filter((value) => value !== id))}>Remove task {index + 1}</button></li>; })}</ol>
          <label>Published task revision <select value={taskId} onChange={(e) => setTaskId(e.target.value)}><option value="">Select revision</option>
            {options.map((option) => <option key={option.revision_id} value={option.revision_id}>{option.config.title} · revision {option.number}</option>)}</select></label>{" "}
          <button disabled={!taskId || taskIds.includes(taskId)} onClick={() => { setTaskIds([...taskIds, taskId]); setTaskId(""); }}>Add task</button>{" "}
          <button onClick={() => perform(() => mutate("/tasks", "PUT", { version: lab.version, revision_ids: taskIds }))}>Save task order</button>
        </fieldset>
        {moreOptions && <button onClick={() => setOptionOffset(optionOffset + 100)}>Load more task revisions</button>}
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
        <fieldset disabled={busy || !!lab?.archived_at} className="flex flex-wrap gap-2"><label>Existing student <select value={selectedStudentId} onChange={(e) => setStudentId(e.target.value)}>
          <option value="">Select student</option>{students.filter((s) => !lab.students.some((m) => m.id === s.id)).map((s) => <option key={s.id} value={s.id}>{s.roll_number} · {s.name}</option>)}</select></label>
          <button disabled={!selectedStudentId} onClick={() => perform(async () => { await mutate("/students", "POST", { version: lab.version, ids: [selectedStudentId] }); setStudentId(""); })}>Enroll selected student</button>
        </fieldset>
        <form onSubmit={(e) => { e.preventDefault(); void perform(async () => {
          await mutate("/students/manual", "POST", { version: lab.version, roll_number: roll, name }); setRoll(""); setName("");
        }); }}><fieldset disabled={busy || !!lab?.archived_at} className="flex flex-wrap gap-2">
          <label>Student roll number <input required maxLength={64} value={roll} onChange={(e) => setRoll(e.target.value)} /></label>
          <label>Student name <input required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></label><button>Find or create and enroll</button>
        </fieldset></form>
        <label>Import roster CSV (roll_number,name)<input type="file" accept=".csv,text/csv" disabled={busy || !!lab?.archived_at} className="mt-1 block" onChange={(e) => {
          const file = e.target.files?.[0]; e.target.value = "";
          if (file) void perform(async () => {
            const result = await api<{ created: string[]; existing: string[]; name_mismatches: string[] }>(`/admin/labs/${lab.id}/students/import?version=${lab.version}`, { method: "POST", body: file }, csrf);
            await reload(); setMessage(`${result.created.length} created; ${result.existing.length} existing. Name mismatches: ${result.name_mismatches.join(", ") || "none"}.`);
          });
        }} /></label>
        <label className="block">Filter roster <input value={rosterSearch} onChange={(e) => setParams(e.target.value ? { search: e.target.value } : {}, { replace: true })} /></label>
        </>}
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Roll number</th><th>Name</th><th>Browser / IP</th><th>Submissions</th><th>Actions</th></tr></thead>
          <tbody>{(studentId ? [member!] : lab.students.filter((item) => `${item.roll_number} ${item.name}`.toLowerCase().includes(rosterSearch.toLowerCase()))).map((member) => <tr className="border-t" data-frozen={member.frozen || undefined} key={member.id}><td><Link to={`/admin/labs/${lab.id}/students/${member.id}`}>{member.roll_number}</Link></td><td>{member.name}</td>
            <td>{member.bound_at ? `Bound · ${member.last_ip}` : "Not bound"}{member.ip_changed && <span className="block">IP changed (original {member.bound_ip})</span>}</td>
            <td><span className={member.frozen ? "notice-warning rounded px-2 py-1" : ""}>{member.frozen ? `Frozen · ${member.freeze_reason}` : "Enabled during lab"}</span></td><td><div className="flex flex-wrap gap-2">
              <button disabled={busy || !!lab?.archived_at} onClick={() => rosterAction(member, "freeze")}>{member.frozen ? "Unfreeze" : "Freeze"} {member.roll_number}</button>
              <button disabled={busy || !member.bound_at} onClick={() => rosterAction(member, "release")}>Release browser {member.roll_number}</button>
              {setupOpen && <button disabled={busy || !!lab?.archived_at} onClick={() => { if (confirm(`Remove ${member.roll_number} from enrollment?`)) void perform(async () => { await mutate(`/students/${member.id}?version=${lab.version}`, "DELETE"); if (studentId) setDestination(`/admin/labs/${lab.id}/students`); }); }}>Remove student</button>}
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
      {revisionId && task && <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">{task.config.title} · revision {task.number}</h2>
        <p>{task.config.maximum_marks} marks · CPU {task.config.cpu_seconds}s · Wall {task.config.wall_seconds}s · Memory {task.config.memory_mib} MiB</p>
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
