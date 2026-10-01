import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { renderRoute } from './testRouter';
import { Scoreboard } from './Scoreboard';
import { AdminLabs } from './AdminLabs';
import { StudentLabs } from './StudentLabs';
import type { PublicLab } from './Lab';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const lab: PublicLab = { id: 'lab', title: 'Lab', phase: 'Running', scoreboard_visible: true, frozen: false,
  starts_at: '2026-01-01T00:00:00Z', ends_at: '2026-01-01T02:00:00Z', server_time: '2026-01-01T00:30:00Z',
  tasks: [], pdfs: [], announcements: [] };
const cell = { task_id: 'task', marks: '10.00', elapsed_us: 65_000_000, submission_id: 'own',
  state: 'first_solve', pending: false, delayed: false, first_solve: true };
const board = { tasks: [{ task_id: 'task', title: 'Sum', maximum_marks: '10' }], students: [
  { rank: 1, roll_number: 'R1', name: 'Ada', total: '10.00', elapsed_us: 65_000_000, pending: false, tasks: [cell] },
  { rank: 2, roll_number: 'R2', name: 'Ben', total: '5.00', elapsed_us: 80_000_000, pending: true,
    tasks: [{ ...cell, marks: '5.00', elapsed_us: 80_000_000, submission_id: null, state: 'judging', pending: true, delayed: true, first_solve: false }] },
] };
const response = (data: unknown) => ({ ok: true, status: 200, json: async () => data });

test('shows ranked shaded cells, elapsed time, delayed work and only supplied own links', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(board)));
  renderRoute(<Scoreboard lab={lab} />, '/labs/lab/scoreboard');
  const link = await screen.findByRole('link', { name: /10.00/ });
  expect(link.getAttribute('href')).toBe('/labs/lab/submissions/own');
  expect(link.getAttribute('data-state')).toBe('first_solve');
  expect(screen.getAllByRole('link')).toHaveLength(1);
  expect(screen.getAllByText('00:01:05')).toHaveLength(2);
  expect(screen.getByText('Provisional')).toBeTruthy();
  expect(screen.getByText('Judging delayed').parentElement?.getAttribute('data-state')).toBe('judging');
});

test('hidden scoreboard makes no request; denied refresh clears prior standings', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(response(board)).mockResolvedValue({ ok: false, status: 403,
    json: async () => ({ detail: 'Scoreboard is visible only to admin' }) });
  vi.stubGlobal('fetch', fetchMock);
  const view = renderRoute(<Scoreboard lab={{ ...lab, scoreboard_visible: false }} />, '/labs/lab/scoreboard');
  expect(fetchMock).not.toHaveBeenCalled();
  view.unmount();
  renderRoute(<Scoreboard lab={lab} />, '/labs/lab/scoreboard');
  await screen.findByText('R1 · Ada');
  fireEvent.click(screen.getByRole('button', { name: 'Refresh scoreboard' }));
  await screen.findByRole('alert');
  expect(screen.queryByText('R1 · Ada')).toBeNull();
});

test('student deep link survives refresh and existing lab SSE updates revoke visibility', async () => {
  let stream: EventTarget;
  vi.stubGlobal('EventSource', class extends EventTarget { constructor() { super(); stream = this; } close = vi.fn(); });
  let visible = true;
  vi.stubGlobal('fetch', vi.fn().mockImplementation((path: string) => Promise.resolve(response(
    path.endsWith('/scoreboard') ? board : path === '/api/labs' ? [lab] : { ...lab, scoreboard_visible: visible }))));
  renderRoute(<StudentLabs csrf="csrf" />, '/labs/lab/scoreboard');
  await screen.findByText('R1 · Ada');
  expect(screen.getByRole('link', { name: 'Scoreboard' })).toBeTruthy();
  visible = false;
  stream!.dispatchEvent(new Event('refresh'));
  await waitFor(() => expect(screen.queryByText('R1 · Ada')).toBeNull());
  expect(screen.queryByRole('link', { name: 'Scoreboard' })).toBeNull();
});


test('admin visibility toggle sends CSRF and version, and archived labs disable changes', async () => {
  vi.stubGlobal('EventSource', class extends EventTarget { close = vi.fn(); });
  let visible = false;
  const adminLab = { ...lab, version: 3, strict_ip: false, first_released_at: null, students: [] };
  const fetchMock = vi.fn().mockImplementation((path: string, options: RequestInit) => {
    if (path.endsWith('/visibility')) { visible = true; return Promise.resolve(response(null)); }
    return Promise.resolve(response(path.endsWith('/scoreboard') ? { tasks: [], students: [] } : { ...adminLab, scoreboard_visible: visible }));
  });
  vi.stubGlobal('fetch', fetchMock);
  renderRoute(<AdminLabs csrf="secret-csrf" />, '/admin/labs/lab/scoreboard');
  fireEvent.click(await screen.findByRole('button', { name: 'Visible to participants: Off' }));
  await screen.findByRole('button', { name: 'Visible to participants: On' });
  const request = fetchMock.mock.calls.find(([path]) => path.endsWith('/visibility'))!;
  expect(request[0]).toBe('/api/admin/labs/lab/scoreboard/visibility');
  expect(JSON.parse(request[1].body)).toEqual({ version: 3, visible: true });
  expect(request[1].headers['X-CSRF-Token']).toBe('secret-csrf');
  cleanup();
  fetchMock.mockImplementation((path: string) => Promise.resolve(response(path.endsWith('/scoreboard') ? { tasks: [], students: [] }
    : { ...adminLab, scoreboard_visible: true, archived_at: '2026-01-01T03:00:00Z', phase: 'Archived' })));
  renderRoute(<AdminLabs csrf="secret-csrf" />, '/admin/labs/lab/scoreboard');
  expect((await screen.findByRole('button', { name: 'Visible to participants: On' })).hasAttribute('disabled')).toBe(true);
});
