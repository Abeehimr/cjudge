import type { ReactNode } from "react";

export type CaseMetrics = { number: number; verdict: string; cpu_seconds: number; wall_seconds: number; memory_kib: number };
export type CaseStreams = { stdin: string | null; expected: string | null; stdout: string | null; stderr: string | null;
  stdin_truncated: boolean; expected_truncated: boolean; stdout_truncated: boolean; stderr_truncated: boolean };

export default function CaseResult({ item, children, open, onToggle }: {
  item: CaseMetrics; children: ReactNode; open?: boolean; onToggle?: (open: boolean) => void;
}) {
  return <details className="case-result rounded border p-3" data-verdict={item.verdict} open={open}
    onToggle={onToggle ? (event) => onToggle(event.currentTarget.open) : undefined}>
    <summary>Case {item.number}: {item.verdict} · CPU {item.cpu_seconds}s · Wall {item.wall_seconds}s · Memory {item.memory_kib} KiB</summary>
    {children}
  </details>;
}

export function Streams({ item }: { item: CaseStreams }) {
  return <>{(["stdin", "expected", "stdout", "stderr"] as const).map((part) => item[part] !== null && <div key={part}>
    <h4>{{ stdin: "Standard input", expected: "Expected output", stdout: "Standard output", stderr: "Standard error" }[part]}{item[`${part}_truncated`] ? " (truncated)" : ""}</h4>
    <pre className="overflow-x-auto whitespace-pre-wrap">{item[part] || "(empty)"}</pre>
  </div>)}</>;
}
