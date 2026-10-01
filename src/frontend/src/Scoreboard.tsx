import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { api } from "./api";
import { useAdminEvents } from "./Isolates";
import type { AdminLab, PublicLab } from "./Lab";

type Cell = { task_id: string; marks: string | null; elapsed_us: number | null; submission_id: string | null;
  state: "empty" | "zero" | "partial" | "judging" | "solved" | "first_solve"; pending: boolean; delayed: boolean; first_solve: boolean };
type Board = { tasks: { task_id: string; title: string; maximum_marks: string }[];
  students: { rank: number; roll_number: string; name: string; total: string; elapsed_us: number; pending: boolean; tasks: Cell[] }[] };
const labels = { empty: "No submission", zero: "Zero", partial: "Partial", judging: "Judging pending", solved: "Solved", first_solve: "First to solve" };

function elapsed(microseconds: number) {
  const seconds = Math.floor(microseconds / 1_000_000);
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60].map((part) => String(part).padStart(2, "0")).join(":");
}

export function Scoreboard({ lab, admin = false }: { lab: PublicLab | AdminLab; admin?: boolean }) {
  const [board, setBoard] = useState<Board | null>(null), [error, setError] = useState("");
  const current = useRef(0);
  const allowed = admin || !!lab.scoreboard_visible;
  async function refresh(signal?: AbortSignal) {
    const request = ++current.current;
    try {
      const value = await api<Board>(`${admin ? '/admin' : ''}/labs/${lab.id}/scoreboard`, { signal });
      if (request === current.current && !signal?.aborted) { setBoard(value); setError(""); }
    } catch (e) {
      if (request === current.current && !signal?.aborted) { setBoard(null); setError((e as Error).message); }
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    if (allowed) void refresh(controller.signal);
    else { current.current++; setBoard(null); setError(""); }
    return () => { controller.abort(); current.current++; };
  }, [lab, admin, allowed]);
  if (!allowed) return <p role="status">Scoreboard is visible only to admin.</p>;
  return <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">Scoreboard</h2>
    <p className="text-sm">Highest total first; ties use the smallest sum of times from lab start for positive-score tasks. No failed-attempt penalty.</p>
    <button onClick={() => { void refresh(); }}>Refresh scoreboard</button>
    {error && <p role="alert" className="notice notice-danger">{error}</p>}
    <div aria-label="Scoreboard legend" className="flex flex-wrap gap-2 text-sm">
      {Object.entries(labels).map(([state, label]) => <span key={state} className="scoreboard-cell" data-state={state}>{label}</span>)}
    </div>
    {!board && !error && <p role="status">Loading scoreboard…</p>}
    {board && <><div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Lab standings by marks and submission time</caption>
      <thead><tr><th scope="col">Rank</th><th scope="col">Student</th><th scope="col">Total / time</th>
        {board.tasks.map((task) => <th scope="col" key={task.task_id}>{task.title}<span className="block font-normal">{task.maximum_marks} marks</span></th>)}</tr></thead>
      <tbody>{board.students.map((row) => <tr className="border-t" key={row.roll_number}>
        <td>{row.rank}</td><th scope="row" className="font-normal">{row.roll_number} · {row.name}</th>
        <td><strong className="block text-lg">{row.total}</strong><span className="block text-xs">{elapsed(row.elapsed_us)}</span>{row.pending && <span className="block text-xs">Provisional</span>}</td>
        {row.tasks.map((cell) => {
          const content = <>{cell.marks !== null && <strong className="block">{cell.marks}</strong>}
            {cell.elapsed_us !== null && <span className="block text-xs">{elapsed(cell.elapsed_us)}</span>}
            {cell.state !== 'empty' && <span className="block text-xs">{cell.delayed ? 'Judging delayed' : labels[cell.state]}</span>}
            {cell.pending && cell.first_solve && <span className="block text-xs">First to solve · provisional</span>}</>;
          return <td key={cell.task_id}>{cell.submission_id ? <Link className="scoreboard-cell" data-state={cell.state}
            to={`${admin ? '/admin' : ''}/labs/${lab.id}/submissions/${cell.submission_id}`}>{content}</Link>
            : <div className="scoreboard-cell" data-state={cell.state} aria-label={cell.state === 'empty' ? 'No submission' : undefined}>{content}</div>}</td>;
        })}
      </tr>)}</tbody></table></div>{!board.students.length && <p>No enrolled students.</p>}</>}
  </section>;
}

export function AdminScoreboard({ lab, refreshLab }: { lab: AdminLab; refreshLab: () => Promise<void> }) {
  const [error, setError] = useState("");
  useAdminEvents(async () => { try { await refreshLab(); setError(""); } catch (e) { setError((e as Error).message); } });
  return <>{error && <p role="alert" className="notice notice-danger">{error}</p>}<Scoreboard lab={lab} admin /></>;
}
