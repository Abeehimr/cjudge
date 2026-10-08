import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { api } from "./api";

type Case = { number: number; verdict: string; cpu_seconds: number; wall_seconds: number; memory_kib: number;
  stdin: string | null; expected: string | null; stdout: string | null; stderr: string | null;
  stdin_truncated: boolean; expected_truncated: boolean; stdout_truncated: boolean; stderr_truncated: boolean };
type Detail = { id: string; filename: string; source: string; status: string; accepted_at: string;
  marks: string | null; maximum_marks: string | null; official_marks: string | null; passed: number | null; total: number | null; grading_pending: boolean;
  deleted_at: string | null; delete_reason: string | null; official_run_id: string | null; compiler_feedback: string | null; compiler_truncated: boolean;
  history: { id: string; verdict: string; finished_at: string }[]; cases: Case[] };

export default function SubmissionDetail({ labId, submissionId, visible, refreshKey }: {
  labId: string; submissionId: string; visible: boolean; refreshKey: string;
}) {
  const [params, setParams] = useSearchParams(), run = params.get("run") || "";
  const [row, setRow] = useState<Detail | null>(null), [error, setError] = useState("");
  const requested = useRef("");
  useEffect(() => {
    const identity = `${labId}/${submissionId}/${run}`;
    if (requested.current !== identity || !visible) setRow(null);
    requested.current = identity;
    const controller = new AbortController(); setError("");
    if (visible) void api<Detail>(`/labs/${labId}/submissions/${submissionId}/details${run ? `?run_id=${encodeURIComponent(run)}` : ""}`,
      { signal: controller.signal }).then((value) => { if (!controller.signal.aborted) setRow(value); })
      .catch((e) => { if (!controller.signal.aborted) { setRow(null); setError(e.message); } });
    return () => controller.abort();
  }, [labId, submissionId, visible, refreshKey, run]);
  if (!visible) return <p className="notice notice-warning">Submission details are hidden until results are released and reveal is enabled.</p>;
  return <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">Submission {submissionId}</h2>
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    {!row && !error && <p>Loading submission…</p>}
    {row && <><p><span className="submission-status" data-status={row.status}>{row.status}</span> · Accepted {new Date(row.accepted_at).toLocaleString()}</p>
      {row.deleted_at && <p className="notice notice-danger">Deleted · {row.delete_reason} · Excluded from lab marks.</p>}
      <p>Official marks: {row.official_marks ?? "Pending"}</p>
      {row.grading_pending && <p className="notice notice-warning">Grading in progress. Previous official marks remain visible.</p>}
      <label>Judge result <select value={run} onChange={(e) => setParams(e.target.value ? { run: e.target.value } : {})}>
        <option value="">Official result</option>{row.history.map((item) => <option key={item.id} value={item.id}>{item.verdict} · {new Date(item.finished_at).toLocaleString()} · {item.id === row.official_run_id ? "Official" : "Retained run"}</option>)}</select></label>
      {run && <p className="notice notice-warning">Viewing retained run; marks use the official result.</p>}
      {row.passed !== null && <p>Cases passed: {row.passed}/{row.total} · Run marks: {row.marks}{' '}<strong>/</strong>{' '}{row.maximum_marks}</p>}
      <h3 className="font-semibold">Source: {row.filename}</h3>
      <a download href={`/api/labs/${labId}/submissions/${row.id}/source`}>Download original source</a>
      <pre className="overflow-x-auto rounded border bg-slate-50 p-3"><code>{row.source}</code></pre>
      {row.compiler_feedback && <pre className="overflow-x-auto whitespace-pre-wrap">{row.compiler_feedback}</pre>}
      {row.compiler_truncated && <p>Compiler feedback truncated.</p>}
      <h3 className="font-semibold">Case results</h3>{!row.cases.length && <p>No case results available.</p>}
      {row.cases.map((item) => <details className="case-result rounded border p-3" data-verdict={item.verdict} key={item.number}>
        <summary>Case {item.number}: {item.verdict} · CPU {item.cpu_seconds}s · Wall {item.wall_seconds}s · Memory {item.memory_kib} KiB</summary>
        {item.stdin === null && <p>Passed case. Test streams are shown only for failed cases.</p>}
        {(["stdin", "expected", "stdout", "stderr"] as const).map((part) => item[part] !== null && <div key={part}>
          <h4>{{ stdin: "Standard input", expected: "Expected output", stdout: "Standard output", stderr: "Standard error" }[part]}{item[`${part}_truncated`] ? " (truncated)" : ""}</h4>
          <pre className="overflow-x-auto whitespace-pre-wrap">{item[part] || "(empty)"}</pre></div>)}
      </details>)}
    </>}
  </section>;
}
