import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { renderRoute } from './testRouter';
import { Marks, Corrections } from './Marks';
import { AdminSubmissionDetail } from './AdminSubmissions';
import type { AdminLab } from './Lab';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function live() { vi.stubGlobal('EventSource', class extends EventTarget { close = vi.fn(); }); }

test('marks distinguish pending from zero and link the best submission', async () => {
  live(); vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [
    { id: 'a', roll_number: '001', name: 'Ada', total: '2.33', pending: true, submission_count: 2,
      tasks: [{ task_id: 'task', revision_id: 'r', title: 'Sum', marks: '2.33', pending: true, best_submission_id: 'best' }] },
    { id: 'b', roll_number: '002', name: 'Ben', total: '0.00', pending: true, submission_count: 1,
      tasks: [{ task_id: 'task', revision_id: 'r', title: 'Sum', marks: null, pending: true, best_submission_id: null }] },
    { id: 'c', roll_number: '003', name: 'Cal', total: '0.00', pending: false, submission_count: 0,
      tasks: [{ task_id: 'task', revision_id: 'r', title: 'Sum', marks: '0.00', pending: false, best_submission_id: null }] },
  ] }));
  renderRoute(<Marks labId="lab" taskId="task" />, '/admin/labs/lab/tasks/r');
  expect((await screen.findByRole('link', { name: '2.33' })).getAttribute('href')).toBe('/admin/labs/lab/submissions/best');
  expect(screen.getByText('Pending')).toBeTruthy();
  expect(screen.getByText('0.00')).toBeTruthy();
  expect(screen.getByText('Provisional · judging pending')).toBeTruthy();
});

const lab: AdminLab = { id: 'lab', title: 'Lab', phase: 'Ended', version: 3, strict_ip: false,
  compiler_feedback: 'short', first_released_at: '2026-09-30T00:00:00Z', starts_at: null, ends_at: null,
  server_time: '2026-09-30T00:00:00Z', students: [], pdfs: [], announcements: [],
  tasks: [{ position: 1, revision_id: 'old', task_id: 'task', number: 1,
    config: { title: 'Sum', statement: '', maximum_marks: '7', cpu_seconds: 2, wall_seconds: 6, memory_mib: 256 } }] };

test('correction warns after release and submits a reason with the current lab version', async () => {
  live(); const confirm = vi.fn().mockReturnValue(true); vi.stubGlobal('confirm', confirm);
  const fetchMock = vi.fn().mockImplementation((path: string, options: RequestInit) => Promise.resolve({ ok: true,
    status: options.method === 'POST' ? 201 : 200, json: async () => path.includes('/admin/tasks/') ? { revisions: [{ id: 'old', number: 1 }, { id: 'new', number: 2 }] } : options.method === 'POST' ? { id: 'batch' } : [] }));
  vi.stubGlobal('fetch', fetchMock);
  const refresh = vi.fn().mockResolvedValue(undefined), dirty = vi.fn();
  renderRoute(<Corrections lab={lab} task={lab.tasks[0]} csrf="csrf" refreshLab={refresh} onDirty={dirty} />, '/admin/labs/lab/tasks/old');
  await screen.findByRole('option', { name: 'Revision 2' });
  fireEvent.change(screen.getByLabelText('Corrected revision'), { target: { value: 'new' } });
  fireEvent.change(screen.getByLabelText('Correction reason'), { target: { value: 'Fix tests' } });
  fireEvent.click(screen.getByRole('button', { name: 'Start correction batch' }));
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Results have already been released'));
  const post = fetchMock.mock.calls.find(([, options]) => options.method === 'POST')!;
  expect(post[0]).toBe('/api/admin/labs/lab/tasks/task/corrections');
  expect(JSON.parse(post[1].body as string)).toEqual({ version: 3, revision_id: 'new', reason: 'Fix tests', acknowledge_reuse: false });
  expect(post[1].headers['X-CSRF-Token']).toBe('csrf');
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
});

test('submission deletion preserves the page and requires an audited reason', async () => {
  live(); vi.stubGlobal('confirm', vi.fn().mockReturnValue(true)); vi.stubGlobal('prompt', vi.fn().mockReturnValue('Duplicate evidence'));
  let deleted = false;
  const fetchMock = vi.fn().mockImplementation((path: string, options: RequestInit) => {
    if (options.method === 'PUT') deleted = true;
    return Promise.resolve({ ok: true, status: options.method === 'PUT' ? 204 : 200, json: async () => ({
      id: 'submission', account_id: 'a', revision_id: 'r', filename: 'main.c', source: 'int main(void){}', size: 16,
      roll_number: '001', name: 'Ada', accepted_at: lab.server_time, status: 'Passed', passed: 1, total: 1,
      marks: '7.00', attempt_count: 1, client_ip: '192.0.2.1', client_mac: null, cases: [], history: [], attempts: [],
      official_run_id: 'run', deleted_at: deleted ? lab.server_time : null, delete_reason: deleted ? 'Duplicate evidence' : null,
    }) });
  });
  vi.stubGlobal('fetch', fetchMock);
  renderRoute(<AdminSubmissionDetail labId="lab" submissionId="submission" csrf="csrf" />, '/admin/labs/lab/submissions/submission');
  fireEvent.click(await screen.findByRole('button', { name: 'Delete submission' }));
  expect(await screen.findByRole('button', { name: 'Restore submission' })).toBeTruthy();
  expect(screen.getByText(/Deleted from marks and student history/)).toBeTruthy();
  const put = fetchMock.mock.calls.find(([, options]) => options.method === 'PUT')!;
  expect(JSON.parse(put[1].body as string)).toEqual({ deleted: true, reason: 'Duplicate evidence' });
  expect(put[1].headers['X-CSRF-Token']).toBe('csrf');
});
