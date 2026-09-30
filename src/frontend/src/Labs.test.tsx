import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AdminLabs } from "./AdminLabs";
import { StudentLabs } from "./StudentLabs";
import { renderRoute } from "./testRouter";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const summary = { id: "lab", title: "C practice", phase: "Running", starts_at: "2020-01-01T00:00:00Z", ends_at: "2099-01-01T00:00:00Z", server_time: "2026-09-30T00:00:00Z" };
const materials = { ...summary, frozen: false, tasks: [{ position: 1, revision_id: "revision", title: "Addition", statement: "Add two numbers.", maximum_marks: "10", cpu_seconds: 1, wall_seconds: 2, memory_mib: 64, stack_mib: 8 }], pdfs: [], announcements: [] };
class Live extends EventTarget {
  static instances: Live[] = [];
  onopen = null; onerror = null; close = vi.fn();
  constructor() { super(); Live.instances.push(this); }
}
function live() { Live.instances = []; vi.stubGlobal("EventSource", Live); }

test("student enters explicitly; task navigation keeps one live stream; revocation hides materials", async () => {
  live(); let current = materials, bound = false;
  const fetchMock = vi.fn().mockImplementation((path: string) => {
    if (path.endsWith('/enter')) bound = true;
    const denied = path === '/api/labs/lab' && !bound;
    return Promise.resolve({ ok: !denied, status: denied ? 423 : 200,
      json: async () => denied ? { detail: 'Enter lab to bind this browser' } : path.includes('/submissions') ? [] : path === '/api/labs' ? [summary] : current });
  });
  vi.stubGlobal('fetch', fetchMock);
  const { router } = renderRoute(<StudentLabs csrf="csrf" />, '/labs/lab');
  fireEvent.click(await screen.findByRole('button', { name: 'Enter lab' }));
  const taskLink = await screen.findByRole('link', { name: '1. Addition' });
  expect(screen.queryByText('Add two numbers.')).toBeNull();
  fireEvent.click(taskLink);
  expect(await screen.findByText('Add two numbers.')).toBeTruthy();
  expect(router.state.location.pathname).toBe('/labs/lab/tasks/revision');
  expect(Live.instances).toHaveLength(1);
  expect(fetchMock).toHaveBeenCalledWith('/api/labs/lab/enter', expect.objectContaining({ method: 'POST', headers: { 'X-CSRF-Token': 'csrf' } }));
  current = { ...materials, frozen: true };
  act(() => Live.instances[0].dispatchEvent(new Event('refresh')));
  expect((await screen.findByText(/Submissions paused/)).className).toContain('notice-danger');
  act(() => Live.instances[0].dispatchEvent(new Event('denied')));
  expect(screen.queryByText('Add two numbers.')).toBeNull();
  expect(Live.instances[0].close).toHaveBeenCalled();
});

test('bound student task deep link restores statement and upload without entering again', async () => {
  live(); const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path.includes('/submissions') ? [] : path === '/api/labs' ? [summary] : materials }));
  vi.stubGlobal('fetch', fetchMock);
  renderRoute(<StudentLabs csrf="csrf" />, '/labs/lab/tasks/revision?offset=100');
  expect(await screen.findByText('Add two numbers.')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Submit' })).toBeTruthy();
  expect(screen.queryByRole('combobox')).toBeNull();
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/labs/lab/submissions?offset=100&revision_id=revision', expect.anything()));
  expect(fetchMock.mock.calls.some(([path]) => path.endsWith('/enter'))).toBe(false);
});

test('admin student page isolates controls and filters history to the student', async () => {
  live();
  const member = { id: 'student', roll_number: '001A', name: 'Ada', frozen: false, freeze_reason: null, bound_at: null, bound_ip: null, last_ip: null, ip_changed: false };
  const lab = { ...summary, version: 1, strict_ip: false, first_released_at: null, tasks: [], pdfs: [], students: [member], announcements: [] };
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: path.endsWith('/freeze') ? 204 : 200,
    json: async () => path === '/api/admin/labs/lab' ? lab : [] }));
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('prompt', vi.fn().mockReturnValueOnce('').mockReturnValueOnce('Review required'));
  renderRoute(<AdminLabs csrf="csrf" />, '/admin/labs/lab/students/student');
  fireEvent.click(await screen.findByRole('button', { name: 'Freeze 001A' }));
  expect(fetchMock.mock.calls.some(([path]) => path.endsWith('/freeze'))).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Freeze 001A' }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/labs/lab/students/student/freeze', expect.objectContaining({
    method: 'POST', body: JSON.stringify({ reason: 'Review required', frozen: true }), headers: expect.objectContaining({ 'X-CSRF-Token': 'csrf' }),
  })));
  expect(fetchMock).toHaveBeenCalledWith('/api/admin/labs/lab/submissions?offset=0&account_id=student&order=best', expect.anything());
  expect(screen.queryByText('Save lab settings')).toBeNull();
  expect(screen.queryByLabelText('Student roll number')).toBeNull();
});

test('admin overview does not load account options, task options, or submissions', async () => {
  live(); const lab = { ...summary, version: 1, strict_ip: false, first_released_at: null, compiler_feedback: 'short', tasks: [], pdfs: [], students: [], announcements: [] };
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200, json: async () => path.endsWith('/marks') ? [] : lab }));
  vi.stubGlobal('fetch', fetchMock);
  renderRoute(<AdminLabs csrf="csrf" />, '/admin/labs/lab');
  expect(await screen.findByRole('button', { name: 'Save lab settings' })).toBeTruthy();
  expect(fetchMock.mock.calls.every(([path]) => ['/api/admin/labs/lab', '/api/admin/labs/lab/marks'].includes(path))).toBe(true);
  expect(screen.queryByRole('heading', { name: 'Enrollment (0)' })).toBeNull();
});

test('unknown assigned task shows not-found and never offers an upload', async () => {
  live(); vi.stubGlobal('fetch', vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path === '/api/labs' ? [summary] : materials })));
  renderRoute(<StudentLabs csrf="csrf" />, '/labs/lab/tasks/unknown');
  expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Submit' })).toBeNull();
});

test('unconfirmed source and retry key survive navigation within the lab', async () => {
  live(); vi.stubGlobal('confirm', vi.fn().mockReturnValue(true));
  const current = { ...materials, admission: { allowed: true, reason: '', code: '', pending: 0, retry_at: null, server_time: summary.server_time } };
  let attempts = 0;
  const fetchMock = vi.fn().mockImplementation((path: string, options: RequestInit) => {
    if (options.method === 'POST') {
      if (++attempts === 1) return Promise.reject(new TypeError('Connection lost'));
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ id: 'submission', filename: 'main.c', accepted_at: summary.server_time }) });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => path.includes('/submissions') ? [] : path === '/api/labs' ? [summary] : current });
  });
  vi.stubGlobal('fetch', fetchMock);
  const { router } = renderRoute(<StudentLabs csrf="csrf" />, '/labs/lab/tasks/revision?offset=100');
  const file = new File(['int main(void){return 0;}'], 'main.c');
  fireEvent.change(await screen.findByLabelText(/C file/), { target: { files: [file] } });
  fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
  expect(await screen.findByRole('button', { name: 'Retry upload' })).toBeTruthy();
  fireEvent.click(screen.getByRole('link', { name: 'Overview' }));
  expect(await screen.findByRole('heading', { name: 'Announcements' })).toBeTruthy();
  await act(async () => { await router.navigate(-1); });
  fireEvent.click(await screen.findByRole('button', { name: 'Retry upload' }));
  expect(await screen.findByText(/Accepted main.c/)).toBeTruthy();
  const calls = fetchMock.mock.calls.filter(([, options]) => options.method === 'POST');
  expect(calls[0][1].headers['Idempotency-Key']).toBe(calls[1][1].headers['Idempotency-Key']);
  expect(calls[1][1].body).toBe(file);
  expect(router.state.location.search).toBe('');
  expect(vi.mocked(confirm)).toHaveBeenCalledTimes(2);
});

test('lab navigation blocks dirty settings; refresh preserves typed settings', async () => {
  live(); const lab = { ...summary, phase: 'Draft', starts_at: null, ends_at: null, version: 1, strict_ip: false, first_released_at: null, tasks: [], pdfs: [], students: [], announcements: [] };
  vi.stubGlobal('fetch', vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200, json: async () => path.endsWith('/marks') ? [] : lab })));
  const confirm = vi.fn().mockReturnValue(false); vi.stubGlobal('confirm', confirm);
  const { router } = renderRoute(<AdminLabs csrf="csrf" />, '/admin/labs/lab');
  const title = await screen.findByLabelText('Lab title');
  fireEvent.change(title, { target: { value: 'Unsaved title' } });
  fireEvent.click(screen.getByRole('button', { name: 'Refresh lab' }));
  await waitFor(() => expect((title as HTMLInputElement).value).toBe('Unsaved title'));
  fireEvent.click(screen.getByRole('link', { name: 'Students' }));
  await waitFor(() => expect(confirm).toHaveBeenCalled());
  expect(router.state.location.pathname).toBe('/admin/labs/lab');
  expect((title as HTMLInputElement).value).toBe('Unsaved title');
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole('link', { name: 'Students' }));
  expect(await screen.findByRole('heading', { name: 'Enrollment (0)' })).toBeTruthy();
});

test('a scheduled lab enables explicit entry when its start is reached', async () => {
  live(); let scheduled = true;
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({
    ok: path === '/api/labs', status: path === '/api/labs' ? 200 : scheduled ? 403 : 423,
    json: async () => path === '/api/labs' ? [{ ...summary, phase: scheduled ? 'Scheduled' : 'Running' }]
      : { detail: scheduled ? 'Lab materials are hidden until start' : 'Enter lab to bind this browser' },
  }));
  vi.stubGlobal('fetch', fetchMock);
  renderRoute(<StudentLabs csrf="csrf" />, '/labs/lab/tasks/revision');
  expect((await screen.findByRole('button', { name: 'Enter lab' }) as HTMLButtonElement).disabled).toBe(true);
  scheduled = false;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh lab' }));
  await waitFor(() => expect((screen.getByRole('button', { name: 'Enter lab' }) as HTMLButtonElement).disabled).toBe(false));
  expect(fetchMock.mock.calls.some(([path]) => path.endsWith('/enter'))).toBe(false);
});

test('removing enrollment from student detail returns to the roster with one confirmation', async () => {
  live(); const member = { id: 'student', roll_number: '001A', name: 'Ada', frozen: false, bound_at: null };
  let lab = { ...summary, phase: 'Draft', starts_at: null, ends_at: null, version: 1, strict_ip: false, first_released_at: null, tasks: [], pdfs: [], students: [member], announcements: [] };
  const confirm = vi.fn().mockReturnValue(true); vi.stubGlobal('confirm', confirm);
  vi.stubGlobal('fetch', vi.fn().mockImplementation((path: string, options: RequestInit) => {
    if (options.method === 'DELETE') lab = { ...lab, students: [] };
    return Promise.resolve({ ok: true, status: 200, json: async () => path.startsWith('/api/admin/labs/lab') && !path.includes('/submissions') && !path.endsWith('/marks') ? lab : [] });
  }));
  const { router } = renderRoute(<AdminLabs csrf="csrf" />, '/admin/labs/lab/students/student');
  fireEvent.click(await screen.findByRole('button', { name: 'Remove student' }));
  expect(await screen.findByRole('heading', { name: 'Enrollment (0)' })).toBeTruthy();
  expect(router.state.location.pathname).toBe('/admin/labs/lab/students');
  expect(confirm).toHaveBeenCalledTimes(1);
});

test('task corrections preserve unconfirmed uploads with the original revision and retry key', async () => {
  live(); vi.stubGlobal('confirm', vi.fn().mockReturnValue(true));
  const task = { ...materials.tasks[0], previous_revision_ids: [] as string[] };
  let current = { ...materials, tasks: [task], admission: { allowed: true, reason: '', code: '', pending: 0, retry_at: null, server_time: summary.server_time } };
  let attempts = 0;
  const fetchMock = vi.fn().mockImplementation((path: string, options: RequestInit) => {
    if (options.method === 'POST') {
      if (++attempts === 1) return Promise.reject(new TypeError('Connection lost'));
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ id: 'submission', filename: 'main.c', accepted_at: summary.server_time }) });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => path.includes('/submissions') ? [] : path === '/api/labs' ? [summary] : current });
  });
  vi.stubGlobal('fetch', fetchMock);
  renderRoute(<StudentLabs csrf="csrf" />, '/labs/lab/tasks/revision');
  fireEvent.change(await screen.findByLabelText(/C file/), { target: { files: [new File(['int main(void){}'], 'main.c')] } });
  fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
  await screen.findByRole('button', { name: 'Retry upload' });
  current = { ...current, tasks: [{ ...task, revision_id: 'corrected', previous_revision_ids: ['revision'] }] };
  fireEvent.click(screen.getByRole('button', { name: 'Refresh lab' }));
  await screen.findByText(/Task corrected/);
  fireEvent.click(screen.getByRole('button', { name: 'Retry upload' }));
  await screen.findByText(/Accepted main.c/);
  const posts = fetchMock.mock.calls.filter(([, options]) => options.method === 'POST');
  expect(posts[0][0]).toContain('revision_id=revision');
  expect(posts[1][0]).toContain('revision_id=revision');
  expect(posts[0][1].headers['Idempotency-Key']).toBe(posts[1][1].headers['Idempotency-Key']);
});
