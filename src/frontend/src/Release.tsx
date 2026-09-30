import { useEffect, useState } from "react";
import { api } from "./api";
import type { AdminLab } from "./Lab";

export default function Release({ lab, csrf, accept, deleted }: { lab: AdminLab; csrf: string; accept: (lab: AdminLab) => void; deleted: () => void }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [receipt, setReceipt] = useState<{ id: string; sha256: string; size: number } | null>(null);
  const [saved, setSaved] = useState(false), [title, setTitle] = useState("");
  useEffect(() => { setReceipt(null); setSaved(false); setTitle(""); }, [lab.id, lab.version]);
  async function exportZip() {
    if (busy) return;
    const reason = prompt("Reason for archive export"); if (!reason?.trim()) return;
    setBusy(true); setError("");
    try { setReceipt(await api(`/admin/labs/${lab.id}/exports`, { method: "POST",
      body: JSON.stringify({ version: lab.version, reason: reason.trim() }) }, csrf)); setSaved(false); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (busy || !receipt || !saved || title !== lab.title) return;
    if (!confirm("Permanently delete this lab and its submissions/PDFs? This cannot be undone. Keep the downloaded archive.")) return;
    const reason = prompt("Reason for permanent deletion"); if (!reason?.trim()) return;
    setBusy(true); setError("");
    try {
      const result = await api<{ cleanup_pending: number }>(`/admin/labs/${lab.id}`, { method: "DELETE",
        body: JSON.stringify({ version: lab.version, export_id: receipt.id, title, saved_copy: saved, reason: reason.trim() }) }, csrf);
      if (result.cleanup_pending) alert(`Lab deleted. ${result.cleanup_pending} artifacts await cleanup. Retry through POST /api/admin/labs/${lab.id}/cleanup.`);
      deleted();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function change(action: "results" | "archive") {
    if (busy) return;
    const enabled = !lab.reveal_results;
    const message = action === "archive" ? "Archive this lab? Lab edits and grading changes will be locked." : enabled
      ? "Reveal results and retained grading runs? Students will see failed-case tests. Hiding later cannot undo disclosure."
      : "Hide submission details from students? Previously downloaded results cannot be retracted.";
    if (!confirm(message)) return;
    const reason = prompt("Reason for this action"); if (!reason?.trim()) return;
    setBusy(true); setError("");
    try {
      let acknowledge = false;
      if (action === "results" && enabled) {
        const warnings = await api<{ id: string; title: string }[]>(`/admin/labs/${lab.id}/release-warnings`);
        if (warnings.length) {
          acknowledge = confirm(`Tests are reused by scheduled labs: ${warnings.map((row) => row.title).join(", ")}. Reveal anyway?`);
          if (!acknowledge) return;
        }
      }
      accept(await api<AdminLab>(`/admin/labs/${lab.id}/${action}`, { method: "POST", body: JSON.stringify({ version: lab.version,
        reason: reason.trim(), ...(action === "results" ? { enabled, acknowledge_reuse: acknowledge } : {}) }) }, csrf));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">Results and archive</h2>
    <p>{lab.first_released_at ? `First release: ${new Date(lab.first_released_at).toLocaleString()}` : "Results not released."} · Student details {lab.reveal_results ? "visible" : "hidden"}.</p>
    {(lab.phase === "Ended" || !!lab.first_released_at) && <button disabled={busy} onClick={() => { void change("results"); }}>{lab.reveal_results ? "Hide results" : lab.first_released_at ? "Reveal results" : "Release results"}</button>}
    {lab.first_released_at && !lab.archived_at && <button disabled={busy} onClick={() => { void change("archive"); }}>Archive lab</button>}
    {lab.archived_at && <p>Archived · lab and grading edits are locked.</p>}
    {["Ended", "Results released", "Archived"].includes(lab.phase) && <button disabled={busy} onClick={() => { void exportZip(); }}>Generate lab ZIP</button>}
    {receipt && <><p>Verified archive · {receipt.size} bytes</p><p className="break-all text-sm">SHA-256: {receipt.sha256}</p>
      <a download href={`/api/admin/labs/${lab.id}/exports/${receipt.id}`}>Download lab ZIP</a>
      {lab.archived_at && <fieldset disabled={busy} className="space-y-2 rounded border p-3">
        <legend>Permanent deletion</legend>
        <label><input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} /> I downloaded and saved this archive.</label>
        <label>Type lab title to confirm<input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
        <button className="notice-danger" disabled={!saved || title !== lab.title} onClick={() => { void remove(); }}>Permanently delete lab</button>
      </fieldset>}
    </>}
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
  </section>;
}
