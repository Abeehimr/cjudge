import { useEffect, useState, type FormEvent } from "react";
import { api } from "./api";

export type TA = { id: string; username: string; name: string; active: boolean };

export default function TAAccounts({ csrf }: { csrf: string }) {
  const [rows, setRows] = useState<TA[]>([]), [username, setUsername] = useState(""), [name, setName] = useState(""), [password, setPassword] = useState("");
  const [resetId, setResetId] = useState(""), [resetPassword, setResetPassword] = useState("");
  const [error, setError] = useState(""), [message, setMessage] = useState(""), [busy, setBusy] = useState(false);
  async function reload() { setRows(await api<TA[]>("/admin/tas")); }
  useEffect(() => { void reload().catch((e) => setError(e.message)); }, []);
  async function act(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); await reload(); } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function create(event: FormEvent) {
    event.preventDefault();
    await act(async () => {
      await api("/admin/tas", { method: "POST", body: JSON.stringify({ username, name, password }) }, csrf);
      setUsername(""); setName(""); setPassword(""); setMessage("TA created. Share the password directly.");
    });
  }
  return <div className="space-y-4">
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    {message && <p role="status" className="notice notice-warning">{message}</p>}
    <h1 className="text-xl font-semibold">TA accounts</h1>
    <form onSubmit={(e) => { void create(e); }} className="grid gap-3 rounded border bg-white p-4 sm:grid-cols-2">
      <label>Username<input required maxLength={64} value={username} onChange={(e) => setUsername(e.target.value)} /></label>
      <label>Name<input required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>Password<input required type="password" minLength={12} maxLength={128} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      <button disabled={busy}>Create TA</button>
    </form>
    <section className="rounded border bg-white p-4"><h2 className="font-semibold">Accounts</h2>
      <ul className="divide-y">{rows.map((row) => <li key={row.id} className="space-y-2 py-3">
        <p><strong>{row.username}</strong> · {row.name} · {row.active ? "Active" : "Inactive"}</p>
        <div className="flex flex-wrap gap-2">
          <button disabled={busy} onClick={() => { const value = prompt(`Name for ${row.username}`, row.name); if (value !== null) void act(async () => { await api(`/admin/tas/${row.id}`, { method: "PATCH", body: JSON.stringify({ name: value }) }, csrf); }); }}>Rename</button>
          <button disabled={busy} onClick={() => { if (confirm(`${row.active ? "Deactivate" : "Reactivate"} ${row.username}? Their sessions will end.`)) void act(async () => { await api(`/admin/tas/${row.id}/state`, { method: "PUT", body: JSON.stringify({ active: !row.active }) }, csrf); }); }}>{row.active ? "Deactivate" : "Reactivate"}</button>
          <button disabled={busy} onClick={() => { setResetId(row.id); setResetPassword(""); }}>Reset password</button>
        </div>
        {resetId === row.id && <form className="flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); void act(async () => {
          await api(`/admin/tas/${row.id}/password`, { method: "POST", body: JSON.stringify({ password: resetPassword }) }, csrf);
          setResetId(""); setResetPassword(""); setMessage("Password reset; existing TA sessions ended.");
        }); }}><label>New password <input required type="password" minLength={12} maxLength={128} autoComplete="new-password" value={resetPassword} onChange={(e) => setResetPassword(e.target.value)} /></label>
          <button disabled={busy}>Save password</button><button type="button" onClick={() => { setResetId(""); setResetPassword(""); }}>Cancel</button></form>}
      </li>)}</ul>
    </section>
  </div>;
}
