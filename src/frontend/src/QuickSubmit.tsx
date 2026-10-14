import { useEffect, useRef } from 'react';
import { type PublicLab } from './Lab';
import { SubmissionUpload, type UploadDraft } from './Submissions';

export default function QuickSubmit({ lab, selected, select, draft, setDraft, busy, setBusy, csrf, refresh, close, accepted }: {
  lab: PublicLab; selected: string; select: (id: string) => void; draft: UploadDraft; setDraft: (draft: UploadDraft) => void;
  busy: boolean; setBusy: (busy: boolean) => void; csrf: string; refresh: () => Promise<void>; close: () => void; accepted: (receipt: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const task = lab.tasks.find((item) => item.revision_id === selected || item.previous_revision_ids?.includes(selected));
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => { if (element.open) element.close(); };
  }, []);
  return <dialog ref={dialog} aria-labelledby="quick-submit-title" className="quick-submit rounded border bg-white p-5"
    onCancel={(e) => { e.preventDefault(); if (!busy) close(); }}>
    <div className="mb-4 flex items-center justify-between gap-3"><h2 id="quick-submit-title" className="text-xl font-semibold">Quick submit</h2>
      <button disabled={busy} onClick={close}>Close</button></div>
    <label className="mb-4 block">Task <select autoFocus disabled={busy} value={task?.revision_id || ''} onChange={(e) => select(e.target.value)}>
      {lab.tasks.map((item) => <option key={item.revision_id} value={item.revision_id}>{item.position}. {item.title}</option>)}</select></label>
    {task ? <SubmissionUpload key={selected} labId={lab.id} tasks={lab.tasks} admission={lab.admission} csrf={csrf} refresh={refresh}
      revisionId={task.revision_id} draft={draft} setDraft={setDraft} onBusyChange={setBusy} onAccepted={accepted} />
      : <p role="alert">Task unavailable. Close and refresh the lab.</p>}
  </dialog>;
}
