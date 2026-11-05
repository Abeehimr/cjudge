import CaseResult, { Streams } from "./CaseResult";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api } from "./api";
import { useAdminEvents } from "./Isolates";
import RestrictionNotice, { type Restriction } from "./RestrictionNotice";
import { languageName, type Language } from "./languages";

type Source = { id: string; filename: string; language?: Language; state: string; progress: number; passed: number;
  total: number; verdict: string; percentage: number | null; restriction?: Restriction; compiler_feedback: string;
  compiler_truncated: boolean; diagnostic: string };
type Batch = { id: string; revision_id: string; created_at: string; sources: Source[] };
type Case = { number: number; verdict: string; cpu_seconds: number; wall_seconds: number; memory_kib: number };
type SourceDetail = { source: Source; code: string; cases: Case[] };
type Preview = { text: string; truncated: boolean };
type CaseDetail = Case & { stdin: Preview; expected: Preview; stdout: Preview; stderr: Preview;
  stdout_truncated: boolean; stderr_truncated: boolean };

function TestCase({ item, path, selected, refreshKey }: { item: Case; path: string; selected: boolean; refreshKey: number }) {
  const [open, setOpen] = useState(selected);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => { if (selected) setOpen(true); }, [selected]);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setDetail(null); setError("");
    void api<CaseDetail>(path, { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) setDetail(value); })
      .catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [open, path, refreshKey, retry]);
  return <CaseResult item={item} open={open} onToggle={setOpen}>
    {open && <>{error ? <div><p role="alert" className="notice notice-danger">{error}</p>
      <button onClick={() => setRetry((value) => value + 1)}>Retry case {item.number}</button></div>
      : !detail ? <p role="status">Loading case…</p> : <Streams item={{
        stdin: detail.stdin.text, expected: detail.expected.text, stdout: detail.stdout.text, stderr: detail.stderr.text,
        stdin_truncated: detail.stdin.truncated, expected_truncated: detail.expected.truncated,
        stdout_truncated: detail.stdout.truncated || detail.stdout_truncated,
        stderr_truncated: detail.stderr.truncated || detail.stderr_truncated,
      }} />}</>}
  </CaseResult>;
}

export default function TaskTester({ csrf }: { csrf: string }) {
  const { taskId, batchId, sourceId } = useParams();
  const [params] = useSearchParams();
  const revision = params.get("revision") || "";
  const number = Number(params.get("case"));
  const navigate = useNavigate();
  const [batches, setBatches] = useState<Batch[]>([]);
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const latest = useRef(0);
  const [refreshKey, setRefreshKey] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const base = `/admin/tasks/${taskId}/tester`;

  async function refresh() {
    if (!taskId) return;
    const request = ++latest.current;
    try {
      if (batchId && sourceId) {
        const next = await api<SourceDetail>(`${base}/${batchId}/sources/${sourceId}`);
        if (request !== latest.current) return;
        setDetail(next); setRefreshKey((value) => value + 1);
      } else {
        const next = await api<Batch[]>(`${base}${revision ? `?revision_id=${encodeURIComponent(revision)}` : ""}`);
        if (request !== latest.current) return;
        setBatches(next);
      }
      setError("");
    } catch (e) { if (request === latest.current) setError((e as Error).message); }
  }
  const connection = useAdminEvents(refresh);
  useEffect(() => {
    setDetail(null); setBatches([]); setError(""); void refresh();
    return () => { latest.current++; };
  }, [taskId, batchId, sourceId, revision]);

  async function upload() {
    if (!file || !revision) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const archive = file.name.toLowerCase().endsWith(".zip");
      if (!archive && !/\.(c|cpp)$/.test(file.name)) throw new Error("Choose a .c or .cpp source, or .zip archive.");
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
    <h1 className="text-xl font-semibold">{sourceId ? "Test submission" : "Task tester"}</h1>
    {sourceId && <Link to={`${base}/${batchId}${revision ? `?revision=${encodeURIComponent(revision)}` : ""}`}>Back to test batch</Link>}
    <p className="text-sm">Runs against the selected published revision. These results never affect student marks.</p>
    <p className="text-sm">{connection}</p>
    {sourceId && <button onClick={() => { void refresh(); }}>Refresh submission</button>}
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    {message && <p role="status" className="notice notice-success">{message}</p>}
    {!sourceId && <>{revision && <section className="rounded border bg-white p-4">
      <h2 className="font-semibold">New test batch</h2>
      <p className="text-sm">One .c/.cpp file or a flat ZIP of up to 20 sources in this revision's permitted languages; each source at most 64 KiB.</p>
      <input aria-label="C/C++ source or ZIP" type="file" accept=".c,.cpp,.zip" onChange={(event) => setFile(event.target.files?.[0] || null)} />
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
    </>}
    {sourceId && !detail && !error && <p role="status">Loading submission…</p>}
    {detail && <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">{detail.source.filename}</h2>
      <p><span className="case-result rounded border px-1" data-verdict={detail.source.verdict}>{detail.source.verdict}</span> · {detail.source.passed}/{detail.source.total} passed
        {detail.source.percentage !== null && ` · ${detail.source.percentage}%`}</p>
      <RestrictionNotice restriction={detail.source.restriction} />
      {detail.source.diagnostic && <p role="alert" className="notice notice-danger">{detail.source.diagnostic}</p>}
      {detail.source.state === "failed" && <button disabled={busy} onClick={() => { void retry(detail.source); }}>Retry</button>}
      <p>Progress: {detail.source.progress}/{detail.source.total}</p>
      <p>Language: {languageName(detail.source.language)}</p>
      <h3 className="font-semibold">Source: {detail.source.filename}</h3>
      <pre className="overflow-x-auto rounded border bg-slate-50 p-3"><code>{detail.code}</code></pre>
      {(detail.source.compiler_feedback || detail.source.compiler_truncated) && <details><summary>Compiler feedback{detail.source.compiler_truncated ? " (truncated)" : ""}</summary>
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-sm">{detail.source.compiler_feedback}</pre></details>}
      <h3 className="font-semibold">Case results</h3>
      {!detail.cases.length && <p>No case results available.</p>}
      {detail.cases.map((item) => <TestCase key={`${sourceId}/${item.number}`} item={item}
        path={`${base}/${batchId}/sources/${sourceId}/cases/${item.number}`}
        selected={number === item.number} refreshKey={refreshKey} />)}
    </section>}
  </div>;
}
