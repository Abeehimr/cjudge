import { useEffect, useState } from "react";
import { api } from "./api";
import type { AdminLab } from "./Lab";
import type { TA } from "./TAAccounts";

export default function TAAssignments({ lab, csrf, onSave }: { lab: AdminLab; csrf: string; onSave: (lab: AdminLab) => void }) {
  const [available, setAvailable] = useState<TA[]>([]), [selected, setSelected] = useState<string[]>(lab.tas?.map((ta) => ta.id) || []);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => { setSelected(lab.tas?.map((ta) => ta.id) || []); }, [lab.id, lab.tas]);
  useEffect(() => { void api<TA[]>("/admin/tas").then(setAvailable).catch((e) => setError(e.message)); }, []);
  const changed = JSON.stringify([...selected].sort()) !== JSON.stringify((lab.tas || []).map((ta) => ta.id).sort());
  async function save() {
    setBusy(true); setError("");
    try { onSave(await api<AdminLab>(`/admin/labs/${lab.id}/tas`, { method: "PUT",
      body: JSON.stringify({ version: lab.version, ids: selected }) }, csrf)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded border bg-white p-4">
    <h2 className="font-semibold">Assigned TAs</h2>
    {available.length ? <div className="flex flex-wrap gap-3">{available.map((ta) => <label key={ta.id} className="flex items-center gap-2">
      <input type="checkbox" disabled={busy || !!lab.archived_at || !ta.active} checked={selected.includes(ta.id)} onChange={(e) => setSelected((ids) => e.target.checked ? [...ids, ta.id] : ids.filter((id) => id !== ta.id))} />
      {ta.username} · {ta.name}{!ta.active && " (inactive)"}
    </label>)}</div> : <p>Create TA accounts before assigning them.</p>}
    <button disabled={busy || !!lab.archived_at || !changed} onClick={() => { void save(); }}>Save assignments</button>
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
  </section>;
}
