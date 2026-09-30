import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AdminLabs } from "./AdminLabs";
import { StudentLabs } from "./Labs";
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

test("student enters explicitly, receives live updates, and loses materials on revocation", async () => {
  let current = materials;
  class Live extends EventTarget {
    static instance: Live;
    onopen = null; onerror = null;
    close = vi.fn();
    constructor() { super(); Live.instance = this; }
  }
  vi.stubGlobal("EventSource", Live);
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path.includes("/submissions") ? [] : path === "/api/labs" ? [summary] : current }));
  vi.stubGlobal("fetch", fetchMock);
  render(<StudentLabs csrf="csrf" />);
  fireEvent.click(await screen.findByRole("button", { name: "C practice" }));
  expect(screen.queryByText("Add two numbers.")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Enter lab" }));
  expect(await screen.findByText("Add two numbers.")).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith("/api/labs/lab/enter", expect.objectContaining({ method: "POST", headers: { "X-CSRF-Token": "csrf" } }));
  current = { ...materials, frozen: true };
  act(() => Live.instance.dispatchEvent(new Event("refresh")));
  expect((await screen.findByText(/Submissions paused/)).className).toContain("notice-danger");
  expect(screen.getByRole("heading", { name: "Announcements" }).parentElement?.className).toContain("notice-warning");
  act(() => Live.instance.dispatchEvent(new Event("denied")));
  expect(screen.queryByText("Add two numbers.")).toBeNull();
  expect(Live.instance.close).toHaveBeenCalled();
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
  expect(fetchMock).toHaveBeenCalledWith('/api/admin/labs/lab/submissions?offset=0&account_id=student', expect.anything());
  expect(screen.queryByText('Save lab settings')).toBeNull();
  expect(screen.queryByLabelText('Student roll number')).toBeNull();
});

test('admin overview does not load account options, task options, or submissions', async () => {
  live(); const lab = { ...summary, version: 1, strict_ip: false, first_released_at: null, compiler_feedback: 'short', tasks: [], pdfs: [], students: [], announcements: [] };
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => lab });
  vi.stubGlobal('fetch', fetchMock);
  renderRoute(<AdminLabs csrf="csrf" />, '/admin/labs/lab');
  expect(await screen.findByRole('button', { name: 'Save lab settings' })).toBeTruthy();
  expect(fetchMock.mock.calls.every(([path]) => path === '/api/admin/labs/lab')).toBe(true);
  expect(screen.queryByRole('heading', { name: 'Enrollment (0)' })).toBeNull();
});


test('lab navigation blocks dirty settings; refresh preserves typed settings', async () => {
  live(); const lab = { ...summary, phase: 'Draft', starts_at: null, ends_at: null, version: 1, strict_ip: false, first_released_at: null, tasks: [], pdfs: [], students: [], announcements: [] };
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => lab }));
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
