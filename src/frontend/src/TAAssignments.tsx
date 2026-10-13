import { useEffect, useState } from "react";
import { Link } from "react-router";
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
    {available.length ? <div className="flex flex-wrap gap-3">{available.map((ta) => <div key={ta.id} className="flex items-center gap-2">
      <label><input aria-label={`Assign ${ta.username}`} type="checkbox" disabled={busy || !!lab.archived_at || !ta.active} checked={selected.includes(ta.id)} onChange={(e) => setSelected((ids) => e.target.checked ? [...ids, ta.id] : ids.filter((id) => id !== ta.id))} /></label>
      <Link to={`/admin/labs/${lab.id}/tas/${ta.id}`}>{ta.username} · {ta.name}</Link>{!ta.active && " (inactive)"}
    </div>)}</div> : <p>Create TA accounts before assigning them.</p>}
    <button disabled={busy || !!lab.archived_at || !changed} onClick={() => { void save(); }}>Save assignments</button>
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
  </section>;
}

type TADetail = { ta: TA & { assigned_at: string }; penalties: {
  id: string; roll_number: string; name: string; frozen: boolean; freeze_reason: string | null;
  cancelled: boolean; cancel_reason: string | null }[]; activity: {
  action: string; detail: { reason?: string }; created_at: string; student_id: string | null;
  roll_number: string | null; name: string | null }[] };

export function AdminTADetail({ labId, taId }: { labId: string; taId: string }) {
  const [detail, setDetail] = useState<TADetail | null>(null), [offset, setOffset] = useState(0), [error, setError] = useState("");
  useEffect(() => { setOffset(0); setDetail(null); }, [labId, taId]);
  useEffect(() => {
    const controller = new AbortController();
    void api<TADetail>(`/admin/labs/${labId}/tas/${taId}?offset=${offset}`, { signal: controller.signal })
      .then((value) => { setDetail(value); setError(""); })
      .catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [labId, taId, offset]);
  return <section className="space-y-4 rounded border bg-white p-4">
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    {!detail && !error && <p>Loading TA…</p>}
    {detail && <><h2 className="font-semibold">{detail.ta.username} · {detail.ta.name}</h2>
      <p>{detail.ta.active ? "Active" : "Inactive"} · Assigned {new Date(detail.ta.assigned_at).toLocaleString()}</p>
      <h3 className="font-semibold">Current penalties set by this TA</h3>
      {!detail.penalties.length && <p>None.</p>}
      <ul className="divide-y">{detail.penalties.map((item) => <li key={item.id} className="py-2">
        <Link to={`/admin/labs/${labId}/students/${item.id}`}>{item.roll_number} · {item.name}</Link>
        {item.frozen && <> · Frozen: {item.freeze_reason}</>}{item.cancelled && <> · Cancelled: {item.cancel_reason}</>}
      </li>)}</ul>
      <h3 className="font-semibold">Lab activity</h3>
      {!detail.activity.length && <p>No activity on this page.</p>}
      <ul className="divide-y">{detail.activity.map((item, index) => <li key={`${item.created_at}-${index}`} className="py-2">
        {new Date(item.created_at).toLocaleString()} · {item.action.replaceAll("_", " ")}
        {item.student_id && <> · <Link to={`/admin/labs/${labId}/students/${item.student_id}`}>{item.roll_number} · {item.name}</Link></>}
        {item.detail.reason && <> · {item.detail.reason}</>}
      </li>)}</ul>
      <div className="flex gap-2"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>Newer</button>
        <button disabled={detail.activity.length < 100} onClick={() => setOffset(offset + 100)}>Older</button></div>
    </>}
  </section>;
}
