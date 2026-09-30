import { useState } from "react";
import { api } from "./api";
import type { AdminLab } from "./Lab";

export default function Release({ lab, csrf, accept }: { lab: AdminLab; csrf: string; accept: (lab: AdminLab) => void }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
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
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
  </section>;
}
