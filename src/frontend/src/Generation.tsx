import { useEffect, useState, type FormEvent } from "react";
import { api } from "./api";
import { useAdminEvents } from "./Isolates";

type Config = { language: "python" | "c"; generator: string; reference: string; seed: string; count: number };
type Job = { id: string; base_version: number; state: string; progress: number; diagnostic: string;
  config: { count: number; seed: string; generator?: string; reference?: string }; source_sha256?: Record<string, string>; cases: { number: number; seed: string; input_size: number; answer_size: number }[] };

export default function Generation({ taskId, version, csrf, disabled, applied, onDirty }: {
  taskId: string; version: number; csrf: string; disabled: boolean; applied: () => Promise<void>; onDirty: (dirty: boolean) => void;
}) {
  const [config, setConfig] = useState<Config>({ language: "python", generator: "", reference: "", seed: "0", count: 1 });
  const [job, setJob] = useState<Job | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [preview, setPreview] = useState<{ title: string; text: string; truncated: boolean } | null>(null);
  useEffect(() => { onDirty(!!config.generator || !!config.reference || busy);
    return () => onDirty(false); }, [config.generator, config.reference, busy, onDirty]);
  const base = `/admin/tasks/${taskId}/generation`;
  async function refresh() {
    try { setJob(await api<Job | null>(base)); } catch (e) { setError((e as Error).message); }
  }
  useAdminEvents(refresh);
  useEffect(() => { void refresh(); }, [taskId]);
  async function perform(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  function create(event: FormEvent) {
    event.preventDefault();
    void perform(async () => {
      // Keep all signed 64-bit seeds exact in JSON, without JavaScript number rounding.
      if (!/^\d+$/.test(config.seed) || BigInt(config.seed) > 9223372036854775807n) throw new Error("Seed must be a nonnegative signed 64-bit integer.");
      const { seed, ...program } = config;
      const body = JSON.stringify({ version, config: program }).slice(0, -2) + `,"seed":${BigInt(seed)}}}`;
      setJob(await api<Job>(base, { method: "POST", body }, csrf));
      setConfig({ ...config, generator: "", reference: "" });
    });
  }
  function action(name: "apply" | "retry" | "discard") {
    if (!job || !confirm(name === "apply" ? "Append these reviewed generated cases to existing draft cases?" : `${name} generation job?`)) return;
    void perform(async () => {
      await api(`${base}/${job.id}/${name}`, { method: "POST", body: JSON.stringify({ version }) }, csrf);
      if (name === "apply") await applied();
      await refresh();
    });
  }
  function view(number: number, part: string) {
    void perform(async () => {
      const response = await fetch(`/api${base}/${job!.id}/cases/${number}/${part}`);
      if (!response.ok) throw new Error(`Case unavailable (${response.status})`);
      const bytes = await response.arrayBuffer();
      setPreview({ title: `${number}.${part}`, text: new TextDecoder().decode(bytes.slice(0, 65536)), truncated: bytes.byteLength > 65536 });
    });
  }
  const unresolved = job && !["applied", "discarded"].includes(job.state);
  return <section className="space-y-3 rounded border bg-white p-4">
    <h2 className="font-semibold">Generate cases</h2>
    <p className="text-sm">One case per seed. Generator receives seed in argv[1]; Python random is seeded automatically. Reference C reads input and prints the answer.</p>
    <p className="text-sm">Sources: 64 KiB each. 1–100 cases; 1 MiB per input/answer; 16 MiB combined. CPU 10s, wall 30s per program.</p>
    <form onSubmit={create}><fieldset disabled={disabled || busy || !!unresolved} className="space-y-3">
      <label>Generator language <select value={config.language} onChange={(e) => setConfig({ ...config, language: e.target.value as Config["language"] })}><option value="python">Python</option><option value="c">C</option></select></label>
      <label className="block">Generator source<textarea required rows={6} maxLength={65536} className="block w-full font-mono" value={config.generator} onChange={(e) => setConfig({ ...config, generator: e.target.value })} /></label>
      <label className="block">Reference C source<textarea required rows={6} maxLength={65536} className="block w-full font-mono" value={config.reference} onChange={(e) => setConfig({ ...config, reference: e.target.value })} /></label>
      <label>Starting seed <input required inputMode="numeric" pattern="[0-9]+" value={config.seed} onChange={(e) => setConfig({ ...config, seed: e.target.value })} /></label>{" "}
      <label>Case count <input required type="number" min={1} max={100} value={config.count} onChange={(e) => setConfig({ ...config, count: Number(e.target.value) })} /></label>{" "}
      <button>Start generation</button>
    </fieldset></form>
    {job && <div className="space-y-2"><p role="status">Generation {job.state}: {job.progress}/{job.config.count} cases · draft {job.base_version}</p>
      <details><summary>Generation source and provenance</summary>{(["generator", "reference"] as const).map((part) => <div key={part}><h3>{part} · SHA-256 {job.source_sha256?.[part] || "Unavailable"}</h3><pre className="max-h-64 overflow-auto whitespace-pre-wrap border p-2">{job.config[part]}</pre></div>)}</details>
      {job.diagnostic && <pre className="notice notice-danger max-h-64 overflow-auto whitespace-pre-wrap">{job.diagnostic}</pre>}
      <table className="w-full text-left text-sm"><thead><tr><th>Case</th><th>Seed</th><th>Input bytes</th><th>Answer bytes</th><th>Preview</th></tr></thead>
        <tbody>{job.cases.map((entry) => <tr key={entry.number}><td>{entry.number}</td><td>{entry.seed}</td><td>{entry.input_size}</td><td>{entry.answer_size}</td><td>
          <button disabled={busy} onClick={() => view(entry.number, "in")}>View input {entry.number}</button>{" "}<button disabled={busy} onClick={() => view(entry.number, "out")}>View answer {entry.number}</button>
        </td></tr>)}</tbody></table>
      {job.state === "complete" && <button disabled={busy || disabled || version !== job.base_version} onClick={() => action("apply")}>Apply reviewed cases</button>}{" "}
      {job.state === "failed" && <button disabled={busy || disabled} onClick={() => action("retry")}>Retry generation</button>}{" "}
      {["complete", "failed"].includes(job.state) && <button disabled={busy || disabled} onClick={() => action("discard")}>Discard generation</button>}
      {job.state === "complete" && version !== job.base_version && <p className="notice notice-warning">Draft changed. Discard this job and generate again.</p>}
    </div>}
    {preview && <div><h3>{preview.title}{preview.truncated ? " — first 64 KiB" : ""}</h3><pre className="max-h-64 overflow-auto whitespace-pre-wrap border p-2">{preview.text || "(empty file)"}</pre><button onClick={() => setPreview(null)}>Close generation preview</button></div>}
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
  </section>;
}
