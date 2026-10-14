import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { api } from "./api";
import { useAdminEvents } from "./Isolates";
import { useUnsaved } from "./navigation";

export type TAReview = { student_id: string; cancelled: boolean; owner_id: string | null; owner_name: string | null;
  reviewer_name: string | null; version: number; finalized: boolean; needs_recheck: boolean;
  total: string | null; provisional: boolean;
  tasks: { task_id: string; title: string; maximum: string; marks: string | null; done: boolean;
    automatic_marks: string | null; automatic_maximum: string; automatic_pending: boolean; suggested_marks: string | null }[] };

export function StudentTAReview({ labId, studentId, csrf, accountId, released, archived, refreshKey }: {
  labId: string; studentId: string; csrf: string; accountId: string; released: boolean; archived: boolean; refreshKey: number;
}) {
  const [review, setReview] = useState<TAReview | null>(null), [drafts, setDrafts] = useState<Record<string, string>>({});
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const latest = useRef(0);
  async function refresh() {
    const request = ++latest.current;
    try {
      const value = await api<TAReview>(`/ta/labs/${labId}/students/${studentId}/ta-review`);
      if (request === latest.current) { setReview(value); setDrafts({}); setError(""); }
    } catch (e) { if (request === latest.current) setError((e as Error).message); }
  }
  useEffect(() => { setReview(null); setDrafts({}); return () => { latest.current++; }; }, [labId, studentId]);
  useEffect(() => {
    if (Object.keys(drafts).length) { setError("Live update available. Save or reload before continuing."); return; }
    void refresh();
  }, [labId, studentId, refreshKey]);
  useUnsaved(Object.keys(drafts).length > 0);
  async function change(suffix: string, method = "POST", body: object = {}) {
    if (!review) return;
    setBusy(true); setError("");
    try {
      const value = await api<TAReview>(`/ta/labs/${labId}/students/${studentId}/ta-review/${suffix}`,
        { method, body: JSON.stringify({ version: review.version, ...body }) }, csrf);
      setReview(value); setDrafts({});
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  if (!review) return <section className="rounded border bg-white p-4"><h2 className="font-semibold">TA review</h2>{error && <p role="alert">{error}</p>}</section>;
  const editable = released && !archived && !review.cancelled;
  const owned = review.owner_id === accountId;
  const entries = review.tasks.map((task) => ({ task_id: task.task_id,
    marks: drafts[task.task_id] ?? task.marks ?? (owned ? task.suggested_marks : null) ?? "",
    changed: !task.done || drafts[task.task_id] !== undefined && drafts[task.task_id] !== task.marks
  })).filter((item) => item.marks !== "" && item.changed).map(({ task_id, marks }) => ({ task_id, marks }));
  return <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">TA review</h2>
    {error && <p role="alert" className="notice notice-danger">{error} <button onClick={() => { void refresh(); }}>Reload review</button></p>}
    <p>{review.cancelled ? "Cancelled" : review.finalized ? "Finalized" : review.owner_id ? "In progress" : "Unclaimed"}
      {review.owner_name && ` · Owner: ${review.owner_name}`}{review.reviewer_name && ` · Reviewer: ${review.reviewer_name}`}
      {review.needs_recheck && " · Needs recheck"} · TA total {review.total ?? "—"}{review.provisional && " (provisional)"}</p>
    {review.tasks.map((task) => { const value = drafts[task.task_id] ?? task.marks ?? (owned ? task.suggested_marks : null) ?? "";
      return <div key={task.task_id} className="flex flex-wrap items-center gap-2 border-t py-2">
        <strong>{task.title}</strong><label>Marks <input aria-label={`${task.title} TA marks`} type="number" min="0" max={task.maximum}
          step="0.01" value={value} disabled={!editable || !owned || review.finalized || busy}
          onChange={(event) => setDrafts({ ...drafts, [task.task_id]: event.target.value })} /></label>
        <span>/ {task.maximum}</span><span>Judge: {task.automatic_marks ?? "—"} / {task.automatic_maximum}{task.automatic_pending && " (pending)"}</span>
        {task.done ? <span>Saved</span> : task.suggested_marks !== null && value !== "" ? <span>Suggested, unsaved</span> : <span>Unmarked</span>}
      </div>; })}
    {editable && review.tasks.length > 0 && <div className="flex flex-wrap gap-2">
      {!review.owner_id && !review.finalized && <button disabled={busy} onClick={() => { void change("claim"); }}>Claim student</button>}
      {owned && !review.finalized && <><button disabled={busy || entries.length === 0} onClick={() => { void change("marks", "PUT", { marks: entries }); }}>Save marks</button>
        <button disabled={busy || Object.keys(drafts).length > 0 || review.tasks.some((task) => !task.done)}
        onClick={() => { void change("finalize"); }}>Finalize</button>
        <button disabled={busy} onClick={() => { void change("release"); }}>Release claim</button></>}
      {review.finalized && review.owner_id === accountId && <button disabled={busy} onClick={() => { void change("reopen"); }}>Reopen review</button>}
    </div>}
    {!released && <p>TA marking starts after first result release.</p>}
  </section>;
}

type Overview = { total: number; remaining: number; students: { id: string; roll_number: string; name: string;
  cancelled: boolean; automatic_total: string | null; ta_total: string | null; combined_total: string | null; review: TAReview }[] };

export function AdminTAReviews({ labId, csrf, archived, tas }: { labId: string; csrf: string; archived: boolean;
  tas: { id: string; username: string; active: boolean }[] }) {
  const [data, setData] = useState<Overview | null>(null), [error, setError] = useState("");
  const [filter, setFilter] = useState("all"), [busy, setBusy] = useState(false);
  async function refresh() {
    try { setData(await api<Overview>(`/admin/labs/${labId}/ta-reviews`)); setError(""); }
    catch (e) { setError((e as Error).message); }
  }
  useAdminEvents(refresh);
  useEffect(() => { setData(null); void refresh(); }, [labId]);
  async function act(student: Overview['students'][number], action: string) {
    const reason = prompt(`Reason to ${action} review`);
    if (!reason?.trim()) return;
    let owner_id: string | null = null;
    if (action === "release") {
      const target = prompt(`Transfer to TA username, or leave blank to release claim. Available: ${tas.filter((ta) => ta.active).map((ta) => ta.username).join(", ")}`)?.trim();
      if (target === undefined) return;
      owner_id = target ? tas.find((ta) => ta.active && ta.username.toLowerCase() === target.toLowerCase())?.id || null : null;
      if (target && !owner_id) { setError("Select an active assigned TA username."); return; }
    }
    setBusy(true);
    try { await api(`/admin/labs/${labId}/ta-reviews/${student.id}/${action}`,
      { method: "POST", body: JSON.stringify({ version: student.review.version, reason, owner_id }) }, csrf); await refresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">TA reviews</h2>
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    <p>{data?.remaining ?? "—"} remaining / {data?.total ?? "—"} active students</p>
    <label>Status <select value={filter} onChange={(event) => setFilter(event.target.value)}>
      <option value="all">All</option><option value="remaining">Remaining</option><option value="recheck">Needs recheck</option>
    </select></label> <button onClick={() => { void refresh(); }}>Refresh</button>
    {data && <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr>
      <th>Student</th><th>Automatic</th><th>TA</th><th>Combined</th><th>Review</th><th>Actions</th></tr></thead>
      <tbody>{data.students.filter((student) => filter === "all" || filter === "remaining" && !student.review.finalized && !student.cancelled ||
        filter === "recheck" && student.review.needs_recheck).map((student) => <tr key={student.id} className="border-t" data-cancelled={student.cancelled || undefined}>
        <td><Link to={`/admin/labs/${labId}/students/${student.id}`}>{student.roll_number} · {student.name}</Link></td>
        <td>{student.automatic_total ?? "—"}</td><td>{student.ta_total ?? "—"}</td><td>{student.combined_total ?? "—"}</td>
        <td>{student.cancelled ? "Cancelled" : student.review.finalized ? "Finalized" : student.review.owner_name || "Unclaimed"}
          {student.review.needs_recheck && " · Needs recheck"}{student.review.provisional && " · Provisional"}</td>
        <td>{!archived && !student.cancelled && <div className="flex flex-wrap gap-1">
          {student.review.owner_id && !student.review.finalized && <button disabled={busy} onClick={() => { void act(student, "release"); }}>Release / transfer</button>}
          {student.review.finalized && <button disabled={busy} onClick={() => { void act(student, "reopen"); }}>Reopen</button>}
          {student.review.needs_recheck && <button disabled={busy} onClick={() => { void act(student, "acknowledge"); }}>Acknowledge</button>}
        </div>}</td></tr>)}</tbody></table></div>}
  </section>;
}
