export type Summary = { id: string; title: string; starts_at: string | null; ends_at: string | null; phase: string; server_time: string };
export type Pdf = { id: string; name: string; size: number; active?: boolean; replaces_id?: string | null };
export type Message = { id: string; body: string; created_at: string; audience?: string };
export type Student = { id: string; roll_number: string; name: string };
export type Enrollment = Student & { frozen: boolean; freeze_reason: string | null; cancelled: boolean; cancel_reason: string | null; bound_ip: string | null; last_ip: string | null; ip_changed: boolean; bound_at: string | null };
export type Task = { position: number; revision_id: string; previous_revision_ids?: string[]; task_id: string; number: number; config: { title: string; statement: string; maximum_marks: string; cpu_seconds: number; wall_seconds: number; memory_mib: number } };
export type AdminLab = Summary & { scoreboard_visible?: boolean; early_feedback_visible?: boolean; version: number; strict_ip: boolean; compiler_feedback?: string; first_released_at: string | null; reveal_results?: boolean; archived_at?: string | null; tasks: Task[]; pdfs: Pdf[]; students: Enrollment[]; announcements: Message[] };
export type PublicTask = { position: number; revision_id: string; previous_revision_ids?: string[]; title: string; statement: string; maximum_marks: string; cpu_seconds: number; wall_seconds: number; memory_mib: number; stack_mib: number };
export type PublicLab = Summary & { scoreboard_visible?: boolean; early_feedback_visible?: boolean; results_visible?: boolean; frozen: boolean; cancelled?: boolean; cancel_reason?: string | null; tasks: PublicTask[]; pdfs: Pdf[]; announcements: Message[]; admission?: { allowed: boolean; reason: string; code: string; pending: number; retry_at: string | null; server_time: string } };

export function Announcements({ messages }: { messages: Message[] }) {
  const newest = messages[messages.length - 1];
  const older = messages.slice(0, -1).reverse();
  const item = (message: Message) => <li className="border-t pt-2" key={message.id}>
    <span className="block text-sm font-medium">{message.audience || "Everyone"}</span>
    <time className="text-sm">{new Date(message.created_at).toLocaleString()}</time>
    <p className="whitespace-pre-wrap">{message.body}</p>
  </li>;
  return <section className="notice notice-warning"><h2 className="font-semibold">Announcements</h2>
    {newest ? <><ul className="space-y-3">{item(newest)}</ul>
      {older.length > 0 && <details className="mt-3"><summary>Older announcements ({older.length})</summary>
        <ul className="space-y-3">{older.map(item)}</ul></details>}</> : <p>No announcements.</p>}
  </section>;
}
