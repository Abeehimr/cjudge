import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api } from "./api";
import { useAdminEvents } from "./Isolates";
import RestrictionNotice, { type Restriction } from "./RestrictionNotice";

type Source = { id: string; filename: string; state: string; progress: number; passed: number;
  total: number; verdict: string; percentage: number | null; restriction?: Restriction; compiler_feedback: string;
  compiler_truncated: boolean; diagnostic: string };
type Batch = { id: string; revision_id: string; created_at: string; sources: Source[] };
type Case = { number: number; verdict: string; cpu_seconds: number; wall_seconds: number; memory_kib: number };
type SourceDetail = { source: Source; code: string; cases: Case[] };
type Preview = { text: string; truncated: boolean };
type CaseDetail = Case & { stdin: Preview; expected: Preview; stdout: Preview; stderr: Preview;
  stdout_truncated: boolean; stderr_truncated: boolean };

function Stream({ label, value, truncated }: { label: string; value: Preview; truncated?: boolean }) {
  return <details className="rounded border p-2"><summary>{label}{value.truncated || truncated ? " (truncated)" : ""}</summary>
    <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all text-sm">{value.text || "(empty)"}</pre></details>;
}

export default function TaskTester({ csrf }: { csrf: string }) {
  const { taskId, batchId, sourceId } = useParams();
  const [params] = useSearchParams();
  const revision = params.get("revision") || "";
  const number = Number(params.get("case"));
  const navigate = useNavigate();
  const [batches, setBatches] = useState<Batch[]>([]);
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [selectedCase, setSelectedCase] = useState<CaseDetail | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const base = `/admin/tasks/${taskId}/tester`;

  async function refresh() {
    if (!taskId) return;
    try {
      const next = await api<Batch[]>(`${base}${revision ? `?revision_id=${revision}` : ""}`);
      setBatches(next);
      if (batchId && sourceId) {
        setDetail(await api<SourceDetail>(`${base}/${batchId}/sources/${sourceId}`));
        if (number > 0) setSelectedCase(await api<CaseDetail>(`${base}/${batchId}/sources/${sourceId}/cases/${number}`));
      }
      setError("");
    } catch (e) { setError((e as Error).message); }
  }
  const connection = useAdminEvents(refresh);
  useEffect(() => { setDetail(null); setSelectedCase(null); void refresh(); }, [taskId, batchId, sourceId, revision, number]);

  async function upload() {
    if (!file || !revision) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const archive = file.name.toLowerCase().endsWith(".zip");
      if (!archive && !file.name.endsWith(".c")) throw new Error("Choose a .c source or .zip archive.");
      const uploaded = await api<Batch>(`${base}?revision_id=${revision}`, {
        method: "POST", body: file,
        headers: { "Content-Type": archive ? "application/zip" : "application/octet-stream",
          "X-Filename": file.name, "Idempotency-Key": crypto.randomUUID() },
      }, csrf);
      setFile(null); setMessage("Test batch queued.");
      navigate(`${base}/${uploaded.id}?revision=${revision}`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function retry(source: Source) {
    if (!batchId) return;
    setBusy(true); setError("");
    try { await api(`${base}/${batchId}/sources/${source.id}/retry`, { method: "POST" }, csrf); await refresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function remove(batch: Batch) {
    const reason = prompt("Reason for deleting this finished batch?")?.trim();
    if (!reason) return;
    setBusy(true); setError("");
    try {
      await api(`${base}/${batch.id}`, { method: "DELETE", body: JSON.stringify({ reason }) }, csrf);
      if (batchId === batch.id) navigate(`${base}?revision=${revision}`);
      await refresh();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  const active = batches.find((batch) => batch.id === batchId);
  return <div className="space-y-4">
    <nav><Link to={`/admin/tasks/${taskId}${revision ? `?revision=${revision}` : ""}`}>Task revision</Link> / Tester</nav>
    <h1 className="text-xl font-semibold">Task tester</h1>
    <p className="text-sm">Runs against the selected published revision. These results never affect student marks.</p>
    <p className="text-sm">{connection}</p>
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    {message && <p role="status" className="notice notice-success">{message}</p>}
    {revision && <section className="rounded border bg-white p-4">
      <h2 className="font-semibold">New test batch</h2>
      <p className="text-sm">One .c file or a flat ZIP of up to 20 .c files; each source at most 64 KiB.</p>
      <input aria-label="C source or ZIP" type="file" accept=".c,.zip" onChange={(event) => setFile(event.target.files?.[0] || null)} />
      <button disabled={busy || !file} onClick={() => { void upload(); }}>Test sources</button>
    </section>}
    {!revision && <p>Select a published revision from the task page to start a test.</p>}
    <section className="rounded border bg-white p-4"><h2 className="font-semibold">Test history</h2>
      {batches.length === 0 ? <p>No test batches.</p> : batches.map((batch) => <div key={batch.id} className="mt-3 border-t pt-3">
        <div className="flex flex-wrap items-center gap-3"><Link to={`${base}/${batch.id}?revision=${revision}`}>{new Date(batch.created_at).toLocaleString()}</Link>
          <span>{batch.sources.length} source{batch.sources.length === 1 ? "" : "s"}</span>
          <button disabled={busy || batch.sources.some((source) => !["complete", "failed"].includes(source.state))}
            onClick={() => { void remove(batch); }}>Delete finished batch</button></div>
        {active?.id === batch.id && <ul className="mt-2 space-y-1">{batch.sources.map((source) => <li key={source.id}>
          <Link to={`${base}/${batch.id}/${source.id}?revision=${revision}`}>{source.filename}</Link>
          {" · "}<span className="case-result rounded border px-1" data-verdict={source.verdict}>{source.verdict}</span>
          {` · ${source.passed}/${source.total} passed`}
          {source.percentage !== null && ` · ${source.percentage}%`}
          {source.state === "failed" && <button disabled={busy} onClick={() => { void retry(source); }}>Retry</button>}
        </li>)}</ul>}
      </div>)}
    </section>
    {detail && <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">{detail.source.filename}</h2>
      <p><span className="case-result rounded border px-1" data-verdict={detail.source.verdict}>{detail.source.verdict}</span> · {detail.source.passed}/{detail.source.total} passed
        {detail.source.percentage !== null && ` · ${detail.source.percentage}%`}</p>
      <RestrictionNotice restriction={detail.source.restriction} />
      {detail.source.diagnostic && <p role="alert" className="notice notice-danger">{detail.source.diagnostic}</p>}
      <details><summary>Source code</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-sm">{detail.code}</pre></details>
      {(detail.source.compiler_feedback || detail.source.compiler_truncated) && <details><summary>Compiler feedback{detail.source.compiler_truncated ? " (truncated)" : ""}</summary>
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-sm">{detail.source.compiler_feedback}</pre></details>}
      <h3 className="font-semibold">Cases</h3>
      <div className="flex flex-wrap gap-2">{detail.cases.map((item) => <Link key={item.number}
        className="case-result rounded border px-2 py-1" data-verdict={item.verdict}
        to={`${base}/${batchId}/${sourceId}?revision=${revision}&case=${item.number}`}>
        {item.number}: {item.verdict}</Link>)}</div>
      {selectedCase && <div className="space-y-2"><h4 className="font-semibold">Case {selectedCase.number}: {selectedCase.verdict}</h4>
        <p className="text-sm">CPU {selectedCase.cpu_seconds.toFixed(3)} s · Wall {selectedCase.wall_seconds.toFixed(3)} s · Memory {selectedCase.memory_kib} KiB</p>
        <Stream label="Standard input" value={selectedCase.stdin} />
        <Stream label="Expected output" value={selectedCase.expected} />
        <Stream label="Standard output" value={selectedCase.stdout} truncated={selectedCase.stdout_truncated} />
        <Stream label="Standard error" value={selectedCase.stderr} truncated={selectedCase.stderr_truncated} />
      </div>}
    </section>}
  </div>;
}
