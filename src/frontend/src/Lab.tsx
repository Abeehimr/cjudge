export type Summary = { id: string; title: string; starts_at: string | null; ends_at: string | null; phase: string; server_time: string };
export type Pdf = { id: string; name: string; size: number; active?: boolean; replaces_id?: string | null };
export type Message = { id: string; body: string; created_at: string };
export type Student = { id: string; roll_number: string; name: string };
export type Enrollment = Student & { frozen: boolean; freeze_reason: string | null; bound_ip: string | null; last_ip: string | null; ip_changed: boolean; bound_at: string | null };
export type Task = { position: number; revision_id: string; task_id: string; number: number; config: { title: string; statement: string; maximum_marks: string; cpu_seconds: number; wall_seconds: number; memory_mib: number } };
export type AdminLab = Summary & { version: number; strict_ip: boolean; compiler_feedback?: string; first_released_at: string | null; tasks: Task[]; pdfs: Pdf[]; students: Enrollment[]; announcements: Message[] };
export type PublicTask = { position: number; revision_id: string; title: string; statement: string; maximum_marks: string; cpu_seconds: number; wall_seconds: number; memory_mib: number; stack_mib: number };
export type PublicLab = Summary & { frozen: boolean; tasks: PublicTask[]; pdfs: Pdf[]; announcements: Message[]; admission?: { allowed: boolean; reason: string; code: string; pending: number; retry_at: string | null; server_time: string } };

export function Announcements({ messages }: { messages: Message[] }) {
  return <section className="notice notice-warning"><h2 className="font-semibold">Announcements</h2>
    {messages.length ? <ul className="space-y-3">{[...messages].reverse().map((message) => <li className="border-t pt-2" key={message.id}>
      <time className="text-sm">{new Date(message.created_at).toLocaleString()}</time>
      <p className="whitespace-pre-wrap">{message.body}</p>
    </li>)}</ul> : <p>No announcements.</p>}
  </section>;
}

