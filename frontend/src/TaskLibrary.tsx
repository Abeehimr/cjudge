import { useEffect, useState, type FormEvent } from "react";
import { api } from "./api";
import Statement from "./Statement";

type Checker = { kind: "exact" | "tokens"; ignore_final_newline: boolean; ignore_case: boolean;
  absolute_tolerance: string; relative_tolerance: string };
type Config = { title: string; statement: string; maximum_marks: string; scoring: "partial" | "all_or_nothing";
  checker: Checker; cpu_seconds: number; wall_seconds: number; memory_mib: number; stack_mib: number; stdout_mib: number };
type Case = { number: number; input_bytes: number; answer_bytes: number };
type Revision = { id: string; number: number; draft_version: number; created_at: string };
type Task = { id: string; version: number; config: Config; case_count: number };
type Detail = Task & { cases: Case[]; revisions: Revision[] };
type Published = Revision & { task_id: string; config: Config; cases: Case[]; case_count: number };

function Summary({ config }: { config: Config }) {
  const c = config.checker;
  return <div className="space-y-2 text-sm">
    <p><strong>{config.title}</strong> · {config.maximum_marks} marks · {config.scoring === "partial" ? "Partial" : "All or nothing"}</p>
    <p>Checker: {c.kind}; {c.kind === "exact" ? (c.ignore_final_newline ? "ignore one final LF/CRLF" : "all bytes must match")
      : `${c.ignore_case ? "ASCII case-insensitive" : "case-sensitive"}; absolute tolerance ${c.absolute_tolerance}; relative tolerance ${c.relative_tolerance}`}</p>
    <p>CPU {config.cpu_seconds}s · Wall {config.wall_seconds}s · Memory {config.memory_mib} MiB · Stack {config.stack_mib} MiB · Output {config.stdout_mib} MiB</p>
    <Statement text={config.statement} />
  </div>;
}

export default function TaskLibrary({ csrf }: { csrf: string }) {
  const [rows, setRows] = useState<Task[]>([]);
  const [offset, setOffset] = useState(0);
  const [draft, setDraft] = useState<Detail | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [published, setPublished] = useState<Published | null>(null);
  const [review, setReview] = useState(false);
  const [title, setTitle] = useState("");
  const [input, setInput] = useState("");
  const [answer, setAnswer] = useState("");
  const [preview, setPreview] = useState<{ name: string; text: string; truncated: boolean } | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const dirty = !!draft && JSON.stringify(config) !== JSON.stringify(draft.config);

  async function refresh(page = offset) { setRows(await api<Task[]>(`/admin/tasks?offset=${page}`)); }
  useEffect(() => { void refresh().catch((error) => setMessage(error.message)); }, [offset]);

  async function perform(action: () => Promise<void>) {
    setBusy(true); setMessage("");
    try { await action(); } catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  }
  function accept(next: Detail) {
    setDraft(next); setConfig(next.config); setPublished(null); setReview(false); setPreview(null);
  }
  function change<K extends keyof Config>(key: K, value: Config[K]) {
    setConfig((current) => current && { ...current, [key]: value });
  }
  function checker(value: Partial<Checker>) {
    if (config) change("checker", { ...config.checker, ...value });
  }
  function canLeave() { return !dirty || confirm("Discard unsaved task settings?"); }
  async function select(id: string) {
    if (!canLeave()) return;
    await perform(async () => { accept(await api<Detail>(`/admin/tasks/${id}`)); setInput(""); setAnswer(""); });
  }
  async function create(event: FormEvent) {
    event.preventDefault(); if (!canLeave()) return;
    await perform(async () => {
      accept(await api<Detail>("/admin/tasks", { method: "POST", body: JSON.stringify({ title }) }, csrf));
      setTitle(""); setOffset(0); await refresh(0);
    });
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    await perform(async () => {
      accept(await api<Detail>(`/admin/tasks/${draft!.id}`, { method: "PUT", body: JSON.stringify({ version: draft!.version, config }) }, csrf));
      await refresh(); setMessage("Draft saved.");
    });
  }
  async function addCase(event: FormEvent) {
    event.preventDefault();
    await perform(async () => {
      accept(await api<Detail>(`/admin/tasks/${draft!.id}/cases`, {
        method: "POST", body: JSON.stringify({ version: draft!.version, input, answer }),
      }, csrf)); setInput(""); setAnswer(""); await refresh();
    });
  }
  async function upload(file?: File) {
    if (!file || !draft) return;
    if (file.size > 17 * 1024 * 1024) { setMessage("ZIP exceeds 17 MiB."); return; }
    if (draft.case_count && !confirm("Replace all draft cases with this ZIP? Published revisions stay unchanged.")) return;
    await perform(async () => {
      accept(await api<Detail>(`/admin/tasks/${draft.id}/cases?version=${draft.version}`, {
        method: "PUT", body: file, headers: { "Content-Type": "application/zip" },
      }, csrf)); await refresh();
    });
  }
  async function publish() {
    if (!draft || !confirm("Publish this reviewed draft as an immutable grading revision?")) return;
    await perform(async () => {
      const result = await api<Published>(`/admin/tasks/${draft.id}/publish`, {
        method: "POST", body: JSON.stringify({ version: draft.version }),
      }, csrf);
      accept(await api<Detail>(`/admin/tasks/${draft.id}`)); setPublished(result);
      setMessage(`Revision ${result.number} published.`);
    });
  }
  function caseUrl(number: number, part: string) {
    return `/api/admin/tasks/${draft!.id}/cases/${number}/${part}${published ? `?revision_id=${published.id}` : ""}`;
  }
  async function viewCase(number: number, part: string) {
    await perform(async () => {
      const response = await fetch(caseUrl(number, part));
      if (!response.ok) throw new Error(`Case unavailable (${response.status})`);
      const bytes = await response.arrayBuffer();
      setPreview({ name: `${number}.${part}`, text: new TextDecoder().decode(bytes.slice(0, 65536)), truncated: bytes.byteLength > 65536 });
    });
  }

  return <div className="space-y-4">
    <h1 className="text-xl font-semibold">Task library</h1>
    <form onSubmit={create} className="flex flex-wrap gap-2 rounded border bg-white p-4">
      <label>New task title <input required maxLength={160} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <button disabled={busy}>Create draft</button>
    </form>
    <div className="overflow-x-auto rounded border bg-white p-4">
      <table className="w-full text-left text-sm"><thead><tr><th>Title</th><th>Draft version</th><th>Cases</th><th>Marks</th></tr></thead>
        <tbody>{rows.map((row) => <tr className="border-t" key={row.id}>
          <td><button className="underline" disabled={busy} onClick={() => select(row.id)}>{row.config.title}</button></td>
          <td>{row.version}</td><td>{row.case_count}</td><td>{row.config.maximum_marks}</td>
        </tr>)}</tbody></table>
      <div className="mt-2 flex gap-2"><button disabled={busy || offset === 0} onClick={() => setOffset(offset - 100)}>Previous page</button>
        <button disabled={busy || rows.length < 100} onClick={() => setOffset(offset + 100)}>Next page</button></div>
    </div>
    {draft && config && <>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold">{published ? `Revision ${published.number} (read-only)` : `Draft version ${draft.version}`}</h2>
        <button disabled={busy} onClick={() => { setPublished(null); setReview(false); setPreview(null); }}>Edit draft</button>
        <button disabled={busy || dirty} onClick={() => { setPublished(null); setReview(true); setPreview(null); }}>Review draft</button>
        <button disabled={busy} onClick={() => select(draft.id)}>Reload draft</button>
        {dirty && <span role="status">Unsaved settings — save before changing cases or publishing.</span>}
      </div>
      {published || review ? <section className="space-y-3 rounded border bg-white p-4">
        <Summary config={published?.config || draft.config} />
        <p>{published?.case_count ?? draft.case_count} cases. Review case inputs and answers below.</p>
        {!published && <button disabled={busy || !draft.case_count || dirty || draft.revisions.some((r) => r.draft_version === draft.version)} onClick={publish}>Publish reviewed draft</button>}
      </section> : <form onSubmit={save} className="space-y-4 rounded border bg-white p-4">
        <fieldset disabled={busy} className="space-y-3">
          <legend className="font-semibold">Task settings</legend>
          <label className="block">Title <input required maxLength={160} value={config.title} onChange={(e) => change("title", e.target.value)} /></label>
          <label className="block">Statement (optional Markdown)<textarea className="mt-1 block w-full font-mono" rows={6} maxLength={65536}
            value={config.statement} onChange={(e) => change("statement", e.target.value)} /></label>
          <Statement text={config.statement} />
          <div className="flex flex-wrap gap-3">
            <label>Maximum marks <input type="number" min="0.01" max="10000" step="0.01" required value={config.maximum_marks} onChange={(e) => change("maximum_marks", e.target.value)} /></label>
            <label>Scoring <select value={config.scoring} onChange={(e) => change("scoring", e.target.value as Config["scoring"])}>
              <option value="partial">Partial</option><option value="all_or_nothing">All or nothing</option></select></label>
            <label>Checker <select value={config.checker.kind} onChange={(e) => checker({ kind: e.target.value as Checker["kind"],
              ignore_final_newline: false, ignore_case: false, absolute_tolerance: "0", relative_tolerance: "0" })}>
              <option value="exact">Exact bytes</option><option value="tokens">ASCII whitespace tokens</option></select></label>
          </div>
          {config.checker.kind === "exact" ? <label className="block"><input type="checkbox" checked={config.checker.ignore_final_newline}
            onChange={(e) => checker({ ignore_final_newline: e.target.checked })} /> Ignore one final LF/CRLF</label>
            : <div className="flex flex-wrap gap-3">
              <label><input type="checkbox" checked={config.checker.ignore_case} onChange={(e) => checker({ ignore_case: e.target.checked })} /> Ignore ASCII case</label>
              <label>Absolute tolerance <input type="number" min="0" max="1" step="any" required value={config.checker.absolute_tolerance}
                onChange={(e) => checker({ absolute_tolerance: e.target.value })} /></label>
              <label>Relative tolerance <input type="number" min="0" max="1" step="any" required value={config.checker.relative_tolerance}
                onChange={(e) => checker({ relative_tolerance: e.target.value })} /></label>
            </div>}
          <div className="flex flex-wrap gap-3">
            {([['cpu_seconds', 'CPU seconds', 60, .01], ['wall_seconds', 'Wall seconds', 60, .01],
              ['memory_mib', 'Memory MiB', 512, 1], ['stack_mib', 'Stack MiB', 64, 1], ['stdout_mib', 'Output MiB', 10, 1]] as const)
              .map(([key, label, max, step]) => <label key={key}>{label} <input className="w-24" type="number" required min={step} max={max} step={step}
                value={config[key]} onChange={(e) => change(key, Number(e.target.value))} /></label>)}
          </div>
          <button disabled={!dirty}>Save draft</button>
        </fieldset>
      </form>}
      <section className="space-y-3 rounded border bg-white p-4">
        <h2 className="font-semibold">{published ? "Published" : "Draft"} cases</h2>
        <p className="text-sm">Up to 100 cases; 1 MiB per input/answer; 16 MiB combined. Empty files are valid.</p>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Case</th><th>Input bytes</th><th>Answer bytes</th><th>Review / download</th></tr></thead>
          <tbody>{(published?.cases || draft.cases).map((entry) => <tr className="border-t" key={entry.number}>
            <td>{entry.number}</td><td>{entry.input_bytes}</td><td>{entry.answer_bytes}</td>
            <td className="flex flex-wrap gap-2">{(["in", "out"] as const).map((part) => <span key={part}>
              <button disabled={busy} onClick={() => viewCase(entry.number, part)}>View {entry.number}.{part}</button>{" "}
              <a className="underline" href={caseUrl(entry.number, part)} download>Download {entry.number}.{part}</a></span>)}
              {!published && !review && <button disabled={busy || dirty} onClick={() => {
                if (confirm(`Remove draft case ${entry.number}?`)) void perform(async () => {
                  accept(await api<Detail>(`/admin/tasks/${draft.id}/cases/${entry.number}?version=${draft.version}`, { method: "DELETE" }, csrf)); await refresh();
                });
              }}>Remove case {entry.number}</button>}
            </td></tr>)}</tbody></table></div>
        {preview && <div><h3>{preview.name}{preview.truncated ? " — first 64 KiB; truncated" : ""}</h3>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap border p-2">{preview.text || "(empty file)"}</pre>
          <button onClick={() => setPreview(null)}>Close preview</button></div>}
        {!published && !review && <fieldset disabled={busy || dirty} className="space-y-3">
          <label className="block">Replace cases from ZIP (flat N.in / N.out pairs)
            <input type="file" accept=".zip,application/zip" onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = ""; }} /></label>
          <form onSubmit={addCase} className="grid gap-2">
            <label>Case input<textarea className="block w-full font-mono" rows={3} value={input} onChange={(e) => setInput(e.target.value)} /></label>
            <label>Expected output<textarea className="block w-full font-mono" rows={3} value={answer} onChange={(e) => setAnswer(e.target.value)} /></label>
            <button disabled={draft.case_count >= 100}>Add pasted case</button>
          </form>
        </fieldset>}
      </section>
      <section className="rounded border bg-white p-4"><h2 className="font-semibold">Published revisions</h2>
        {draft.revisions.length ? <ul>{draft.revisions.map((revision) => <li key={revision.id}>
          <button className="underline" disabled={busy} onClick={() => { if (canLeave()) void perform(async () => {
            setPublished(await api<Published>(`/admin/tasks/${draft.id}/revisions/${revision.id}`)); setPreview(null);
          }); }}>Revision {revision.number}</button> · draft {revision.draft_version} · {new Date(revision.created_at).toLocaleString()}
        </li>)}</ul> : <p>No published revisions.</p>}
      </section>
    </>}
    {message && <p role="status" className="rounded border bg-white p-3">{message}</p>}
  </div>;
}
