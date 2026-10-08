import { useEffect, useState, type FormEvent } from "react";
import { api } from "./api";
import { useUnsaved } from "./navigation";
import { useSearchParams } from "react-router";

type Student = { id: string; roll_number: string; name: string };
type Credential = Student & { password: string };
type ImportResult = { created: string[]; existing: string[]; name_mismatches: string[] };

export function credentialCsv(entries: Credential[]): string {
  const cell = (value: string) => {
    const safe = /^[\t\r\n]|^[\s]*[=+\-@]/.test(value) ? `'${value}` : value;
    return `"${safe.replaceAll('"', '""')}"`;
  };
  return "\ufeff" + [["roll_number", "name", "password"], ...entries.map(({ roll_number, name, password }) =>
    [roll_number, name, password])].map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n";
}

export default function Accounts({ csrf }: { csrf: string }) {
  const [students, setStudents] = useState<Student[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [params, setParams] = useSearchParams();
  const search = params.get("search") || "";
  const [busy, setBusy] = useState(false);
  const [roll, setRoll] = useState("");
  const [name, setName] = useState("");
  const [message, setMessageText] = useState("");
  const [messageError, setMessageError] = useState(false);
  function setMessage(text: string) { setMessageError(false); setMessageText(text); }
  function showError(text: string) { setMessageError(true); setMessageText(text); }

  useUnsaved(!!roll || !!name);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void api<Student[]>(`/admin/students?search=${encodeURIComponent(search)}`, { signal: controller.signal })
        .then(setStudents).catch((e) => { if (!controller.signal.aborted) showError(e.message); });
    }, search ? 200 : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [search]);
  function toggle(id: string) {
    setSelected((ids) => ids.includes(id) ? ids.filter((value) => value !== id) : [...ids, id]);
  }
  const visibleIds = students.map((student) => student.id);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.includes(id));
  async function addStudent(event: FormEvent) {
    event.preventDefault();
    try {
      const student = await api<Student>("/admin/students", {
        method: "POST", body: JSON.stringify({ roll_number: roll, name }),
      }, csrf);
      setStudents((rows) => search && !`${student.roll_number} ${student.name}`.toLowerCase().includes(search.toLowerCase())
        ? rows : [...rows, student].sort((a, b) => a.roll_number.localeCompare(b.roll_number)).slice(0, 500));
      setRoll(""); setName(""); setMessage(`${student.roll_number} created. Select account to show credentials.`);
    } catch (error) { showError((error as Error).message); }
  }

  async function importFile(file?: File) {
    if (!file) return;
    setCredentials([]);
    try {
      const result = await api<ImportResult>("/admin/students/import", { method: "POST", body: file }, csrf);
      setStudents(await api<Student[]>(`/admin/students?search=${encodeURIComponent(search)}`));
      setMessage(`${result.created.length} created; ${result.existing.length} existing. Name mismatches: ${result.name_mismatches.join(", ") || "none"}.`);
    } catch (error) { showError((error as Error).message); }
  }

  async function showCredentials() {
    setCredentials([]);
    try {
      setCredentials(await api<Credential[]>("/admin/students/credentials", {
        method: "POST", body: JSON.stringify({ ids: selected }),
      }, csrf));
      setMessage("");
    } catch (error) { showError((error as Error).message); }
  }

  async function downloadCredentials() {
    try {
      const entries = await api<Credential[]>("/admin/students/credentials", {
        method: "POST", body: JSON.stringify({ ids: selected }),
      }, csrf);
      const url = URL.createObjectURL(new Blob([credentialCsv(entries)], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url; link.download = "student-credentials.csv";
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
      setMessage(`${entries.length} credentials downloaded. Keep the file private.`);
    } catch (error) { showError((error as Error).message); }
  }

  async function resetSelected() {
    if (!confirm(`Reset passwords for ${selected.length} selected students? All their sessions will end.`)) return;
    setBusy(true);
    setCredentials([]);
    try {
      setCredentials(await api<Credential[]>("/admin/students/reset", {
        method: "POST", body: JSON.stringify({ ids: selected }),
      }, csrf));
      setMessage("Passwords reset. Print or save new credentials now.");
    } catch (error) { showError((error as Error).message); }
    finally { setBusy(false); }
  }

  async function resetStudent(student: Student) {
    if (!confirm(`Reset password for ${student.roll_number}? Existing sessions will end.`)) return;
    setCredentials([]);
    try {
      setCredentials([await api<Credential>(`/admin/students/${student.id}/reset`, { method: "POST" }, csrf)]);
      setMessage("Password reset. Print or save new credential now.");
    } catch (error) { showError((error as Error).message); }
  }

  async function renameStudent(student: Student) {
    const updatedName = prompt(`Name for ${student.roll_number}`, student.name);
    if (updatedName === null) return;
    try {
      const updated = await api<Student>(`/admin/students/${student.id}`, {
        method: "PATCH", body: JSON.stringify({ name: updatedName }),
      }, csrf);
      setStudents((rows) => rows.map((row) => row.id === updated.id ? updated : row));
      setCredentials([]); setMessage("Name updated.");
    } catch (error) { showError((error as Error).message); }
  }

  return <> <div className="space-y-6">
        <h1 className="text-xl font-semibold">Students</h1>
        <section className="no-print rounded border bg-white p-4">
          <h2 className="font-semibold">Add student</h2>
          <form className="mt-3 flex flex-wrap gap-2" onSubmit={addStudent}>
            <label>Roll number <input className="ml-1 rounded border p-2" required value={roll} onChange={(event) => setRoll(event.target.value)} /></label>
            <label>Name <input className="ml-1 rounded border p-2" required value={name} onChange={(event) => setName(event.target.value)} /></label>
            <button className="rounded px-3 py-2">Add</button>
          </form>
          <label className="mt-4 block">Import CSV (roll_number,name)
            <input className="mt-1 block" type="file" accept=".csv,text/csv"
              onChange={(event) => { void importFile(event.target.files?.[0]); event.target.value = ""; }} />
          </label>
        </section>
        <section className="no-print overflow-x-auto rounded border bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-semibold">Global accounts (showing {students.length}, selected {selected.length})</h2>
            <div className="flex flex-wrap gap-2">
              <button className="rounded border px-3 py-1 disabled:opacity-50" disabled={!selected.length || selected.length > 200 || busy} onClick={showCredentials}>Show selected credentials</button>
              <button className="rounded border px-3 py-1 disabled:opacity-50" disabled={!selected.length || selected.length > 200 || busy} onClick={downloadCredentials}>Download selected CSV</button>
              <button className="rounded border px-3 py-1 disabled:opacity-50" disabled={!selected.length || selected.length > 200 || busy} onClick={resetSelected}>Reset selected passwords</button>
            </div>
          </div>
          <label className="mt-3 block">Search students <input className="ml-1 rounded border p-2" maxLength={64} value={search}
            onChange={(event) => setParams(event.target.value ? { search: event.target.value } : {}, { replace: true })} /></label>
          {selected.length > 200 && <p role="status">Select at most 200 students for credential actions.</p>}
          <table className="mt-3 w-full text-left text-sm"><thead><tr className="border-b">
            <th><input type="checkbox" aria-label="Select all visible students" checked={allVisibleSelected}
              onChange={(event) => setSelected((ids) => event.target.checked
                ? [...new Set([...ids, ...visibleIds])] : ids.filter((id) => !visibleIds.includes(id)))} /></th>
            <th className="p-2">Roll number</th><th className="p-2">Name</th><th className="p-2">Actions</th>
          </tr></thead><tbody>{students.map((student) => <tr className="border-b cursor-pointer focus-visible:outline" key={student.id}
            tabIndex={0} aria-label={`Toggle ${student.roll_number}`} aria-selected={selected.includes(student.id)}
            onClick={(event) => { if (!(event.target as HTMLElement).closest("button, input, a")) toggle(student.id); }}
            onKeyDown={(event) => { if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); toggle(student.id); } }}>
            <td><input type="checkbox" aria-label={`Select ${student.roll_number}`} checked={selected.includes(student.id)}
              onChange={() => toggle(student.id)} /></td>
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
      </div>
    {message && <p role={messageError ? "alert" : "status"} className={`notice ${messageError ? "notice-danger" : "notice-warning"}`}>{message}</p>}
  </>;
}
