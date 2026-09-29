import { useEffect, useState, type FormEvent } from "react";

import { api } from "./api";
import TaskLibrary from "./TaskLibrary";

type Session = { id: string; role: "admin" | "student"; roll_number: string | null; name: string; csrf_token: string };
type Student = { id: string; roll_number: string; name: string };
type Credential = Student & { password: string };
type ImportResult = { created: string[]; existing: string[]; name_mismatches: string[] };

export default function App() {
  const [dark, setDark] = useState(() => {
    try { return localStorage.getItem("cjudge-theme") === "dark"; } catch { return false; }
  });
  const [page, setPage] = useState<"students" | "tasks">("students");
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [role, setRole] = useState<"student" | "admin">("student");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [students, setStudents] = useState<Student[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [roll, setRoll] = useState("");
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    try { localStorage.setItem("cjudge-theme", dark ? "dark" : "light"); } catch { /* Storage may be disabled. */ }
  }, [dark]);

  useEffect(() => {
    const controller = new AbortController();
    api<Session>("/auth/session", { signal: controller.signal })
      .then(setSession).catch(() => {}).finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (session?.role === "admin") api<Student[]>("/admin/students")
      .then(setStudents).catch((error) => setMessage(error.message));
  }, [session]);

  async function login(event: FormEvent) {
    event.preventDefault(); setMessage("");
    try {
      const account = await api<Session>(`/auth/${role}/login`, {
        method: "POST", body: JSON.stringify({ identifier, password }),
      });
      setPassword(""); setIdentifier(""); setSession(account);
    } catch (error) { setMessage((error as Error).message); }
  }

  async function logout() {
    if (!session) return;
    try {
      await api<void>("/auth/logout", { method: "POST" }, session.csrf_token);
      setSession(null); setPage("students"); setStudents([]); setSelected([]); setCredentials([]); setMessage("");
    } catch (error) { setMessage((error as Error).message); }
  }

  async function addStudent(event: FormEvent) {
    event.preventDefault();
    try {
      const student = await api<Student>("/admin/students", {
        method: "POST", body: JSON.stringify({ roll_number: roll, name }),
      }, session!.csrf_token);
      setStudents((rows) => [...rows, student].sort((a, b) => a.roll_number.localeCompare(b.roll_number)));
      setRoll(""); setName(""); setMessage(`${student.roll_number} created. Select account to show credentials.`);
    } catch (error) { setMessage((error as Error).message); }
  }

  async function importFile(file?: File) {
    if (!file) return;
    setCredentials([]);
    try {
      const result = await api<ImportResult>("/admin/students/import", { method: "POST", body: file }, session!.csrf_token);
      setStudents(await api<Student[]>("/admin/students"));
      setMessage(`${result.created.length} created; ${result.existing.length} existing. Name mismatches: ${result.name_mismatches.join(", ") || "none"}.`);
    } catch (error) { setMessage((error as Error).message); }
  }

  async function showCredentials() {
    try {
      setCredentials(await api<Credential[]>("/admin/students/credentials", {
        method: "POST", body: JSON.stringify({ ids: selected }),
      }, session!.csrf_token));
      setMessage("");
    } catch (error) { setMessage((error as Error).message); }
  }

  async function resetStudent(student: Student) {
    if (!confirm(`Reset password for ${student.roll_number}? Existing sessions will end.`)) return;
    try {
      setCredentials([await api<Credential>(`/admin/students/${student.id}/reset`, { method: "POST" }, session!.csrf_token)]);
      setMessage("Password reset. Print or save new credential now.");
    } catch (error) { setMessage((error as Error).message); }
  }

  async function renameStudent(student: Student) {
    const updatedName = prompt(`Name for ${student.roll_number}`, student.name);
    if (updatedName === null) return;
    try {
      const updated = await api<Student>(`/admin/students/${student.id}`, {
        method: "PATCH", body: JSON.stringify({ name: updatedName }),
      }, session!.csrf_token);
      setStudents((rows) => rows.map((row) => row.id === updated.id ? updated : row));
      setCredentials([]); setMessage("Name updated.");
    } catch (error) { setMessage((error as Error).message); }
  }

  return <div className={`${dark ? "theme-dark " : ""}min-h-screen bg-slate-100 text-slate-900`}>
    <header className="no-print flex items-center justify-between border-b border-slate-300 bg-white px-6 py-3">
      <strong>cJudge</strong>
      <div className="flex gap-2">
        <button type="button" aria-pressed={dark} onClick={() => setDark(!dark)}>{dark ? "Light theme" : "Dark theme"}</button>
        {session && <button className="rounded border px-3 py-1" onClick={logout}>Log out</button>}
      </div>
    </header>
    <main className="mx-auto max-w-5xl p-6">
      {session?.role === "admin" && <nav aria-label="Admin navigation" className="no-print mb-4 flex gap-2">
        <button aria-pressed={page === "students"} onClick={() => setPage("students")}>Students</button>
        <button aria-pressed={page === "tasks"} onClick={() => { setPage("tasks"); setCredentials([]); setMessage(""); }}>Tasks</button>
      </nav>}
      {loading ? <p role="status">Loading…</p> : !session ? <section className="mx-auto max-w-sm rounded border bg-white p-6">
        <h1 className="text-xl font-semibold">Sign in</h1>
        <div className="mt-4 flex gap-2" role="group" aria-label="Account type">
          {(["student", "admin"] as const).map((option) => <button key={option} type="button"
            className={`rounded border px-3 py-1 ${role === option ? "bg-slate-900 text-white" : ""}`}
            aria-pressed={role === option} onClick={() => { setRole(option); setMessage(""); }}>
            {option === "student" ? "Student" : "Admin"}
          </button>)}
        </div>
        <form className="mt-4 grid gap-3" onSubmit={login}>
          <label>{role === "student" ? "Roll number" : "Username"}<input className="mt-1 w-full rounded border p-2" required
            autoComplete="username" value={identifier} onChange={(event) => setIdentifier(event.target.value)} /></label>
          <label>Password<input className="mt-1 w-full rounded border p-2" type="password" required autoComplete="current-password"
            value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <button className="rounded bg-slate-900 p-2 text-white">Sign in</button>
        </form>
      </section> : session.role === "student" ? <section className="rounded border bg-white p-6">
        <h1 className="text-xl font-semibold">{session.name}</h1>
        <p className="mt-2">Roll number: {session.roll_number}</p>
        <p className="mt-4">No labs assigned yet.</p>
      </section> : page === "tasks" ? <TaskLibrary csrf={session.csrf_token} /> : <div className="space-y-6">
        <h1 className="text-xl font-semibold">Students</h1>
        <section className="no-print rounded border bg-white p-4">
          <h2 className="font-semibold">Add student</h2>
          <form className="mt-3 flex flex-wrap gap-2" onSubmit={addStudent}>
            <label>Roll number <input className="ml-1 rounded border p-2" required value={roll} onChange={(event) => setRoll(event.target.value)} /></label>
            <label>Name <input className="ml-1 rounded border p-2" required value={name} onChange={(event) => setName(event.target.value)} /></label>
            <button className="rounded bg-slate-900 px-3 py-2 text-white">Add</button>
          </form>
          <label className="mt-4 block">Import CSV (roll_number,name)
            <input className="mt-1 block" type="file" accept=".csv,text/csv"
              onChange={(event) => { void importFile(event.target.files?.[0]); event.target.value = ""; }} />
          </label>
        </section>
        <section className="no-print overflow-x-auto rounded border bg-white p-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-semibold">Global accounts ({students.length})</h2>
            <button className="rounded border px-3 py-1 disabled:opacity-50" disabled={!selected.length} onClick={showCredentials}>Show selected credentials</button>
          </div>
          <table className="mt-3 w-full text-left text-sm"><thead><tr className="border-b">
            <th><input type="checkbox" aria-label="Select all students" checked={students.length > 0 && selected.length === students.length}
              onChange={(event) => setSelected(event.target.checked ? students.map((student) => student.id) : [])} /></th>
            <th className="p-2">Roll number</th><th className="p-2">Name</th><th className="p-2">Actions</th>
          </tr></thead><tbody>{students.map((student) => <tr className="border-b" key={student.id}>
            <td><input type="checkbox" aria-label={`Select ${student.roll_number}`} checked={selected.includes(student.id)}
              onChange={(event) => setSelected((ids) => event.target.checked ? [...ids, student.id] : ids.filter((id) => id !== student.id))} /></td>
            <td className="p-2">{student.roll_number}</td><td className="p-2">{student.name}</td>
            <td className="p-2"><button className="mr-3 underline" onClick={() => renameStudent(student)}>Edit name</button>
              <button className="underline" onClick={() => resetStudent(student)}>Reset password</button></td>
          </tr>)}</tbody></table>
        </section>
        {credentials.length > 0 && <section className="rounded border bg-white p-4">
          <div className="no-print flex justify-between"><h2 className="font-semibold">Credential sheet</h2>
            <div><button className="mr-3 underline" onClick={() => print()}>Print</button>
              <button className="underline" onClick={() => setCredentials([])}>Hide</button></div></div>
          <table className="mt-3 w-full text-left text-sm"><thead><tr className="border-b"><th>Roll number</th><th>Name</th><th>Password</th></tr></thead>
            <tbody>{credentials.map((entry) => <tr className="border-b" key={entry.id}><td className="py-2">{entry.roll_number}</td>
              <td>{entry.name}</td><td className="font-mono">{entry.password}</td></tr>)}</tbody></table>
        </section>}
      </div>}
      {message && <p role="status" className="no-print mt-4 rounded border bg-white p-3">{message}</p>}
    </main>
  </div>;
}
