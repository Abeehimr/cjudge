import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { renderRoute } from './testRouter';
import { Marks, Corrections } from './Marks';
import { AdminSubmissionDetail } from './AdminSubmissions';
import type { AdminLab } from './Lab';
import { useState } from 'react';

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
    maximum_marks: '7', ta_maximum: '0.00', config: { title: 'Sum', statement: '', cpu_seconds: 2, wall_seconds: 6, memory_mib: 256 } }] };

test('correction warns after release and submits a reason with the current lab version', async () => {
  live(); const confirm = vi.fn().mockReturnValue(true); vi.stubGlobal('confirm', confirm);
  const fetchMock = vi.fn().mockImplementation((path: string, options: RequestInit) => Promise.resolve({ ok: true,
    status: options.method === 'POST' ? 201 : 200, json: async () => path.includes('/admin/tasks/') ? { revisions: [{ id: 'old', number: 1 }, { id: 'new', number: 2 }] } : path === '/api/admin/labs/lab' ? lab : options.method === 'POST' ? { id: 'batch' } : [] }));
  vi.stubGlobal('fetch', fetchMock);
  const refresh = vi.fn().mockResolvedValue(undefined), dirty = vi.fn();
  const saved = vi.fn();
  renderRoute(<Corrections lab={lab} task={lab.tasks[0]} csrf="csrf" refreshLab={refresh} onDirty={dirty} onSaved={saved} />, '/admin/labs/lab/tasks/old');
  await screen.findByRole('option', { name: 'Revision 2' });
  fireEvent.change(screen.getByLabelText('Published revision'), { target: { value: 'new' } });
  fireEvent.change(screen.getByLabelText('Correction reason'), { target: { value: 'Fix tests' } });
  fireEvent.click(screen.getByRole('button', { name: 'Change revision and rejudge' }));
  await waitFor(() => expect(saved).toHaveBeenCalledWith(lab));
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Results have already been released'));
  const post = fetchMock.mock.calls.find(([, options]) => options.method === 'POST')!;
  expect(post[0]).toBe('/api/admin/labs/lab/tasks/task/corrections');
  expect(JSON.parse(post[1].body as string)).toEqual({ version: 3, revision_id: 'new', reason: 'Fix tests', acknowledge_reuse: false });
  expect(post[1].headers['X-CSRF-Token']).toBe('csrf');
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
});

test.each(['Draft', 'Scheduled'])('revision changes before start preserve all assignments and maxima in %s', async (phase) => {
  live(); const confirm = vi.fn(); vi.stubGlobal('confirm', confirm);
  const current = { ...lab, phase, first_released_at: null, tasks: [
    { ...lab.tasks[0], ta_maximum: '3.00' }, { ...lab.tasks[0], task_id: 'other', revision_id: 'other', position: 2, maximum_marks: '12.00' },
  ] };
  const updated = { ...current, version: 4, tasks: [{ ...current.tasks[0], revision_id: 'new', number: 2 }, current.tasks[1]] };
  const fetchMock = vi.fn().mockImplementation((path: string, options: RequestInit) => Promise.resolve({ ok: true, status: 200,
    json: async () => options.method === 'PUT' ? updated : path.includes('/admin/tasks/')
      ? { revisions: [{ id: 'old', number: 1 }, { id: 'new', number: 2 }] } : [] }));
  vi.stubGlobal('fetch', fetchMock);
  const saved = vi.fn();
  renderRoute(<Corrections lab={current} task={current.tasks[0]} csrf="csrf" refreshLab={vi.fn()} onDirty={vi.fn()} onSaved={saved} />, '/admin/labs/lab/tasks/old');
  await screen.findByRole('option', { name: 'Revision 2' });
  expect(screen.getByText('Revision 1')).toBeTruthy();
  expect(screen.queryByLabelText('Correction reason')).toBeNull();
  fireEvent.change(screen.getByLabelText('Published revision'), { target: { value: 'new' } });
  fireEvent.click(screen.getByRole('button', { name: 'Change revision' }));
  await waitFor(() => expect(saved).toHaveBeenCalledWith(updated));
  const put = fetchMock.mock.calls.find(([, options]) => options.method === 'PUT')!;
  expect(put[0]).toBe('/api/admin/labs/lab/tasks');
  expect(JSON.parse(put[1].body)).toEqual({ version: 3, assignments: [
    { revision_id: 'new', maximum_marks: '7', ta_maximum: '3.00' },
    { revision_id: 'other', maximum_marks: '12.00', ta_maximum: '0.00' },
  ] });
  expect(confirm).not.toHaveBeenCalled();
  expect(fetchMock.mock.calls.some(([, options]) => options.method === 'POST')).toBe(false);
});

test('start-boundary rejection refreshes phase and requires an explicit reason and rejudge', async () => {
  live(); vi.stubGlobal('confirm', vi.fn().mockReturnValue(true));
  const saved = vi.fn();
  const running = { ...lab, phase: 'Running', version: 4, first_released_at: null };
  const fetchMock = vi.fn().mockImplementation((path: string, options: RequestInit) => Promise.resolve({
    ok: options.method !== 'PUT', status: options.method === 'PUT' ? 409 : 200,
    json: async () => options.method === 'PUT' ? { detail: 'Lab setup is fixed after start' }
      : path.includes('/admin/tasks/') ? { revisions: [{ id: 'old', number: 1 }, { id: 'new', number: 2 }] }
      : path === '/api/admin/labs/lab' ? running : [],
  }));
  vi.stubGlobal('fetch', fetchMock);
  function Page() {
    const [current, setCurrent] = useState({ ...lab, phase: 'Scheduled', first_released_at: null });
    return <Corrections lab={current} task={current.tasks[0]} csrf="csrf" onDirty={vi.fn()} onSaved={saved}
      refreshLab={async () => { setCurrent(running); }} />;
  }
  renderRoute(<Page />, '/admin/labs/lab/tasks/old');
  await screen.findByRole('option', { name: 'Revision 2' });
  fireEvent.change(screen.getByLabelText('Published revision'), { target: { value: 'new' } });
  fireEvent.click(screen.getByRole('button', { name: 'Change revision' }));
  expect(await screen.findByLabelText('Correction reason')).toBeTruthy();
  expect((await screen.findByRole('alert')).textContent).toContain('Lab setup is fixed after start');
  expect((screen.getByLabelText('Published revision') as HTMLSelectElement).value).toBe('new');
  expect((screen.getByRole('button', { name: 'Change revision and rejudge' }) as HTMLButtonElement).disabled).toBe(true);
  expect(fetchMock.mock.calls.some(([, options]) => options.method === 'POST')).toBe(false);
  fireEvent.change(screen.getByLabelText('Correction reason'), { target: { value: 'Corrected tests' } });
  fireEvent.click(screen.getByRole('button', { name: 'Change revision and rejudge' }));
  await waitFor(() => expect(saved).toHaveBeenCalled());
  expect(JSON.parse(fetchMock.mock.calls.find(([, options]) => options.method === 'POST')![1].body).version).toBe(4);
});

test.each(['archived', 'judging'])('revision changes are disabled when %s', async (state) => {
  live(); vi.stubGlobal('fetch', vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path.includes('/admin/tasks/') ? { revisions: [{ id: 'new', number: 2 }] }
      : state === 'judging' ? [{ id: 'batch', task_id: 'task', state: 'judging', total: 1, completed: 0, delayed: 0, created_at: lab.server_time }] : [] })));
  const current = { ...lab, archived_at: state === 'archived' ? lab.server_time : null };
  renderRoute(<Corrections lab={current} task={lab.tasks[0]} csrf="csrf" refreshLab={vi.fn()} onDirty={vi.fn()} onSaved={vi.fn()} />, '/admin/labs/lab/tasks/old');
  await screen.findByRole('option', { name: 'Revision 2' });
  expect((screen.getByLabelText('Published revision').closest('fieldset') as HTMLFieldSetElement).disabled).toBe(true);
  expect(screen.getByText('Revision 1')).toBeTruthy();
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
  expect(screen.getByText(/Deleted · Excluded from marks/)).toBeTruthy();
  const put = fetchMock.mock.calls.find(([, options]) => options.method === 'PUT')!;
  expect(JSON.parse(put[1].body as string)).toEqual({ deleted: true, reason: 'Duplicate evidence' });
  expect(put[1].headers['X-CSRF-Token']).toBe('csrf');
});
