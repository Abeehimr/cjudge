import { useEffect, useState } from "react";
import { Link, useMatch, useNavigate, useSearchParams } from "react-router";
import { api } from "./api";
import SubmissionDetail from "./SubmissionDetail";
import { NotFound } from "./navigation";

type Lab = { id: string; title: string; phase: string; starts_at: string | null; ends_at: string | null;
  server_time: string; results_visible: boolean; archived: boolean };
type Student = { id: string; roll_number: string; name: string; frozen: boolean; freeze_reason: string | null;
  frozen_by_name: string | null; cancelled: boolean; cancel_reason: string | null; cancelled_by_name: string | null;
  bound: boolean; ip_changed: boolean; submission_count: number; last_submission_at: string | null };
type Submission = { id: string; filename: string; accepted_at: string; status: string; best_for_review: boolean;
  deleted_at: string | null; delete_reason: string | null; early_feedback?: { passed: number; total: number; marks: string; maximum_marks: string } | null };

export default function TALabs({ csrf }: { csrf: string }) {
  const route = useMatch("/ta/labs/:labId/*"), listRoute = useMatch("/ta/labs"), navigate = useNavigate();
  const labId = route?.params.labId, parts = (route?.params["*"] || "").split("/").filter(Boolean);
  const studentId = parts[0] === "students" ? parts[1] : undefined;
  const submissionId = parts[2] === "submissions" ? parts[3] : undefined;
  const [params, setParams] = useSearchParams(), search = params.get("search") || "";
  const [query, setQuery] = useState(search), [labs, setLabs] = useState<Lab[]>([]), [lab, setLab] = useState<Lab | null>(null);
  const [students, setStudents] = useState<Student[]>([]), [student, setStudent] = useState<Student | null>(null);
  const [history, setHistory] = useState<Submission[]>([]), [offset, setOffset] = useState(0);
  const [credential, setCredential] = useState<string | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    setCredential(null); setError(""); setLab(null); setStudent(null); setStudents([]); setHistory([]); setOffset(0);
  }, [labId, studentId]);
  useEffect(() => {
    const controller = new AbortController();
    void api<Lab[]>("/ta/labs", { signal: controller.signal }).then(setLabs).catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [refresh]);
  useEffect(() => {
    if (!labId) return;
    const controller = new AbortController();
    void api<Lab>(`/ta/labs/${labId}`, { signal: controller.signal }).then(setLab).catch((e) => {
      if (controller.signal.aborted) return;
      const failure = e as Error & { status?: number };
      if (failure.status === 403 || failure.status === 404) { setCredential(null); navigate("/ta/labs", { replace: true }); }
      else setError(failure.message);
    });
    return () => controller.abort();
  }, [labId, refresh]);
  useEffect(() => {
    if (!labId || !search.trim() || studentId) { setStudents([]); return; }
    const controller = new AbortController();
    void api<Student[]>(`/ta/labs/${labId}/students?search=${encodeURIComponent(search.trim())}`,
      { signal: controller.signal }).then(setStudents).catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [labId, studentId, search, refresh]);
  useEffect(() => {
    if (!labId || !studentId) return;
    const controller = new AbortController();
    void api<Student>(`/ta/labs/${labId}/students/${studentId}`, { signal: controller.signal })
      .then(setStudent).catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [labId, studentId, refresh]);
  useEffect(() => {
    if (!labId || !studentId || !lab?.results_visible) { setHistory([]); return; }
    const controller = new AbortController();
    void api<Submission[]>(`/ta/labs/${labId}/students/${studentId}/submissions?offset=${offset}`,
      { signal: controller.signal }).then(setHistory).catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [labId, studentId, lab?.results_visible, offset, refresh]);
  useEffect(() => {
    const path = labId ? `/api/ta/labs/${labId}/events` : "/api/ta/events";
    const source = new EventSource(path);
    source.addEventListener("refresh", () => setRefresh((value) => value + 1));
    source.addEventListener("access-lost", () => { setCredential(null); source.close(); navigate("/ta/labs", { replace: true }); });
    source.addEventListener("denied", () => { setCredential(null); source.close(); window.dispatchEvent(new Event("cjudge-session-expired")); });
    return () => source.close();
  }, [labId, navigate]);
  useEffect(() => { setCredential(null); }, [submissionId]);
  async function act(path: string, method: string, body: object, password = false) {
    setBusy(true); setError(""); setCredential(null);
    try {
      const value = await api<{ password?: string }>(`/ta/labs/${labId}/students/${studentId}/${path}`,
        { method, body: JSON.stringify(body) }, csrf);
      if (password) setCredential(value.password || null);
      setRefresh((count) => count + 1);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function reason(label: string): string | null {
    const value = prompt(`Reason to ${label}`);
    return value?.trim() || null;
  }
  if ((!route && !listRoute) || parts.length && (parts[0] !== "students" || !studentId || parts.length !== 2 && !(parts.length === 4 && parts[2] === "submissions"))) return <NotFound />;
  return <div className="space-y-4">
    <nav aria-label="TA breadcrumbs"><Link to="/ta/labs">Assigned labs</Link>{labId && <> / <Link to={`/ta/labs/${labId}`}>{lab?.title || "Lab"}</Link></>}
      {studentId && <> / <Link to={`/ta/labs/${labId}/students/${studentId}`}>{student?.roll_number || "Student"}</Link></>}</nav>
    {!labId ? <><h1 className="text-xl font-semibold">Assigned labs</h1>
      <ul className="space-y-2">{labs.map((item) => <li className="rounded border bg-white p-4" key={item.id}>
        <Link to={`/ta/labs/${item.id}`}>{item.title}</Link> · {item.phase}{item.archived && " · Read only"}</li>)}</ul>
      {!labs.length && <p>No labs assigned.</p>}</> : <>
      <h1 className="text-xl font-semibold">{lab?.title || "Lab"}</h1>
      {lab && <p>{lab.phase}{lab.archived && " · Read only"} · Results {lab.results_visible ? "released" : "hidden"}</p>}
      {!studentId && <section className="space-y-3 rounded border bg-white p-4">
        <h2 className="font-semibold">Find a student</h2>
        <form className="flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); setParams(query.trim() ? { search: query.trim() } : {}); }}>
          <label>Roll number or name <input value={query} maxLength={64} onChange={(e) => setQuery(e.target.value)} /></label>
          <button>Search</button></form>
        {search && <><p>{students.length} match{students.length === 1 ? "" : "es"}{students.length === 50 && " (first 50)"}</p>
          <ul className="divide-y">{students.map((item) => <li key={item.id} className="py-3"><Link to={`/ta/labs/${labId}/students/${item.id}`}>{item.roll_number} · {item.name}</Link>
            <span className="block text-sm">{item.submission_count} submissions · {item.bound ? "Browser bound" : "Browser unbound"}{item.cancelled ? " · Cancelled" : item.frozen ? " · Frozen" : ""}</span></li>)}</ul></>}</section>}
      {studentId && student && <section className="space-y-3 rounded border bg-white p-4">
        <h2 className="font-semibold">{student.roll_number} · {student.name}</h2>
        <p>{student.bound ? "Browser bound" : "Browser unbound"}{student.ip_changed && " · IP changed"} · {student.submission_count} submissions
          {student.last_submission_at && ` · Latest ${new Date(student.last_submission_at).toLocaleString()}`}</p>
        {student.frozen && <p className="notice notice-warning">Frozen by {student.frozen_by_name || "admin"} · {student.freeze_reason}</p>}
        {student.cancelled && <p className="notice notice-danger">Cancelled by {student.cancelled_by_name || "admin"} · {student.cancel_reason}</p>}
        {!lab?.archived && <div className="flex flex-wrap gap-2">
          <button disabled={busy} onClick={() => { const why = reason(student.frozen ? "unfreeze" : "freeze"); if (why) void act("freeze", "POST", { frozen: !student.frozen, reason: why }); }}>{student.frozen ? "Unfreeze" : "Freeze"}</button>
          <button disabled={busy} onClick={() => { const why = reason(student.cancelled ? "reinstate" : "cancel"); if (why) void act("cancellation", "PUT", { cancelled: !student.cancelled, reason: why }); }}>{student.cancelled ? "Reinstate" : "Cancel"}</button>
          <button disabled={busy || !student.bound} onClick={() => { if (!confirm(`Release ${student.roll_number}'s browser and reset their password?`)) return;
            const why = reason("release browser"); if (why) void act("release", "POST", { reason: why }, true); }}>Release browser</button>
          <button disabled={busy} onClick={() => { if (confirm(`Show ${student.roll_number}'s current password? Keep it private.`)) void act("password", "POST", { confirm: true }, true); }}>Show password</button>
        </div>}
        {credential && <div className="notice notice-warning" aria-label="Selected student password">
          <p>Current password for {student.roll_number}: <strong className="font-mono">{credential}</strong></p>
          <button onClick={() => setCredential(null)}>Hide password</button></div>}
      </section>}
      {studentId && lab?.results_visible && <section className="space-y-3 rounded border bg-white p-4">
        <h2 className="font-semibold">Released submissions</h2>
        <ul className="divide-y">{history.map((row) => <li key={row.id} className="py-3" data-best={row.best_for_review || undefined} data-deleted={!!row.deleted_at || undefined}>
          <Link to={`/ta/labs/${labId}/students/${studentId}/submissions/${row.id}`}>{row.filename}</Link> · {new Date(row.accepted_at).toLocaleString()}
          <span className="submission-status ml-2" data-status={row.status}>{row.status}</span>
          {row.best_for_review && <span className="block text-green-800">Best for review</span>}
          {row.deleted_at && <span className="block text-red-800">Deleted · {row.delete_reason}</span>}
          {row.early_feedback && <span className="block">{row.early_feedback.passed}/{row.early_feedback.total} cases · Marks {row.early_feedback.marks} <strong>/</strong> {row.early_feedback.maximum_marks}</span>}
        </li>)}</ul>
        {!history.length && <p>No submissions.</p>}
        <div className="flex gap-2"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>Newer</button>
          <button disabled={history.length < 100} onClick={() => setOffset(offset + 100)}>Older</button></div>
      </section>}
      {submissionId && lab && <SubmissionDetail labId={labId} submissionId={submissionId} visible={lab.results_visible}
        refreshKey={lab.server_time} basePath={`/ta/labs/${labId}/students/${studentId}/submissions`} />}
    </>}
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
  </div>;
}
