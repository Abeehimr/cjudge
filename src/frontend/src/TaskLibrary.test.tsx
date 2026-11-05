import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import TaskLibrary from "./TaskLibrary";
import { renderRoute } from "./testRouter";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
beforeEach(() => { vi.stubGlobal('EventSource', class extends EventTarget { close = vi.fn(); }); });

function expectAbove(first: Element, second: Element) {
  expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
}

test("admin creates draft, adds case, reviews and publishes once", async () => {
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  const config = { title: "Sum", statement: "", maximum_marks: "100", scoring: "partial",
    checker: { kind: "exact", ignore_final_newline: false, ignore_case: false, absolute_tolerance: "0", relative_tolerance: "0" },
    cpu_seconds: 2, wall_seconds: 6, memory_mib: 256, stack_mib: 8, stdout_mib: 10 };
  let detail: { id: string; version: number; config: typeof config; case_count: number;
    cases: { number: number; input_bytes: number; answer_bytes: number }[]; revisions: object[] } = { id: "task", version: 1, config, case_count: 0, cases: [], revisions: [] as object[] };
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/generation")) return { ok: true, status: 200, json: async () => null };
    if (path.includes("/publish") || path.includes("/revisions/")) {
      detail = { ...detail, revisions: [{ id: "revision", number: 1, draft_version: 2, created_at: "2026-09-29T00:00:00Z" }] };
      return { ok: true, status: 201, json: async () => ({ id: "revision", task_id: "task", number: 1,
        draft_version: 2, created_at: "2026-09-29T00:00:00Z", config, cases: detail.cases, case_count: 1 }) };
    }
    if (options?.method === "POST" && path.endsWith("/cases")) {
      detail = { ...detail, version: 2, case_count: 1, cases: [{ number: 1, input_bytes: 1, answer_bytes: 1 }] };
    }
    return { ok: true, status: options?.method === "POST" ? 201 : 200,
      json: async () => path.includes("?offset=") ? (detail.case_count || detail.version > 1 ? [detail] : []) : detail };
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("confirm", vi.fn(() => true));
  renderRoute(<TaskLibrary csrf="csrf" />, "/admin/tasks");
  fireEvent.change(screen.getByLabelText("New task title"), { target: { value: "Sum" } });
  fireEvent.click(screen.getByRole("button", { name: "Create draft" }));
  expect(await screen.findByText("Draft version 1")).toBeTruthy();
  expectAbove(screen.getByRole("heading", { name: "Published revisions" }), screen.getByText("Task settings"));
  fireEvent.change(screen.getByLabelText("Case input"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Expected output"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "Add pasted case" }));
  expect(await screen.findByText("Draft version 2")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Review draft" }));
  expectAbove(screen.getByRole("heading", { name: "Published revisions" }),
    screen.getByText("1 cases. Review case inputs and answers below."));
  fireEvent.click(screen.getByRole("button", { name: "Publish reviewed draft" }));
  expect(await screen.findByText("Revision 1 published.")).toBeTruthy();
  expect(await screen.findByRole("heading", { name: "Revision 1 (read-only)" })).toBeTruthy();
  expect((screen.getByRole("link", { name: "Export task ZIP" }) as HTMLAnchorElement).getAttribute("href"))
    .toBe("/api/admin/tasks/task/revisions/revision/export");
  expectAbove(screen.getByRole("heading", { name: "Published revisions" }),
    screen.getByText("1 cases. Review case inputs and answers below."));
  cleanup();
  renderRoute(<TaskLibrary csrf="csrf" />, "/admin/tasks/task?revision=revision");
  expect(await screen.findByRole("heading", { name: "Revision 1 (read-only)" })).toBeTruthy();
  expect(screen.queryByLabelText("Title")).toBeNull();
  expect(fetchMock).toHaveBeenCalledWith("/api/admin/tasks/task/publish", expect.objectContaining({
    headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
    body: JSON.stringify({ version: 2 }),
  }));
});

test("import task ZIP creates and opens a draft", async () => {
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  const detail = { id: "imported", version: 1, case_count: 1, cases: [{ number: 1, input_bytes: 1, answer_bytes: 1 }], revisions: [],
    config: { title: "Imported", statement: "", scoring: "partial", checker: { kind: "exact", ignore_final_newline: false,
      ignore_case: false, absolute_tolerance: "0", relative_tolerance: "0" }, cpu_seconds: 2, wall_seconds: 6,
      memory_mib: 256, stack_mib: 8, stdout_mib: 10 } };
  const fetchMock = vi.fn(async (path: string) => ({ ok: true, status: path.endsWith("/import") ? 201 : 200,
    json: async () => path.endsWith("/generation") ? null : path.includes("?offset=") ? [] : detail }));
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<TaskLibrary csrf="csrf" />, "/admin/tasks");
  const file = new File(["bundle"], "task.zip", { type: "application/zip" });
  fireEvent.change(screen.getByLabelText("Import task ZIP"), { target: { files: [file] } });
  expect(await screen.findByText("Draft version 1")).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith("/api/admin/tasks/import", expect.objectContaining({
    method: "POST", body: file, headers: expect.objectContaining({ "Content-Type": "application/zip", "X-CSRF-Token": "csrf" }),
  }));
});

const replacementDraft = { id: 'task', version: 2, case_count: 1,
  cases: [{ number: 1, input_bytes: 3, answer_bytes: 3 }],
  revisions: [{ id: 'published', number: 1, draft_version: 2, created_at: '2026-11-05T00:00:00Z' }],
  config: { title: 'Original', statement: '', scoring: 'partial', banned_identifiers: [], languages: ['c11'],
    checker: { kind: 'exact', ignore_final_newline: false, ignore_case: false, absolute_tolerance: '0', relative_tolerance: '0' },
    cpu_seconds: 2, wall_seconds: 6, memory_mib: 256, stack_mib: 8, stdout_mib: 10 } };

test('replace task ZIP preserves identity and opens review without publishing', async () => {
  vi.stubGlobal('confirm', vi.fn(() => true));
  const updated = { ...replacementDraft, version: 3, config: { ...replacementDraft.config, title: 'Replacement' } };
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => ({ ok: true, status: 200,
    json: async () => path.endsWith('/generation') ? null : options?.method === 'PUT' ? updated : replacementDraft }));
  vi.stubGlobal('fetch', fetchMock);
  const { router } = renderRoute(<TaskLibrary csrf="csrf" />, '/admin/tasks/task');
  const field = await screen.findByLabelText('Replace draft from task ZIP');
  const file = new File(['zip'], 'replacement.zip', { type: 'application/zip' });
  fireEvent.change(field, { target: { files: [file] } });
  expect(await screen.findByText('Draft replaced. Review settings and cases before publishing.')).toBeTruthy();
  expect(screen.getByText('Draft version 3')).toBeTruthy();
  expect(await screen.findByText('Replacement')).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Revision 1' })).toBeTruthy();
  expect(router.state.location.search).toBe('?view=review');
  expect(screen.getByRole('button', { name: 'Publish reviewed draft' })).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith('/api/admin/tasks/task/import?version=2', expect.objectContaining({
    method: 'PUT', body: file, headers: expect.objectContaining({ 'Content-Type': 'application/zip', 'X-CSRF-Token': 'csrf' }),
  }));
  expect(fetchMock.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
  expect(screen.queryByLabelText('Replace draft from task ZIP')).toBeNull();
});

test.each(['cancel', 'oversized'])('task replacement %s does not send an upload', async (condition) => {
  vi.stubGlobal('confirm', vi.fn(() => false));
  const fetchMock = vi.fn(async (path: string) => ({ ok: true, status: 200,
    json: async () => path.endsWith('/generation') ? null : replacementDraft }));
  vi.stubGlobal('fetch', fetchMock);
  renderRoute(<TaskLibrary csrf="csrf" />, '/admin/tasks/task');
  const field = await screen.findByLabelText('Replace draft from task ZIP');
  const file = new File(['zip'], 'replacement.zip', { type: 'application/zip' });
  if (condition === 'oversized') Object.defineProperty(file, 'size', { value: 17 * 1024 * 1024 + 1 });
  fireEvent.change(field, { target: { files: [file] } });
  if (condition === 'oversized') expect(await screen.findByRole('alert')).toBeTruthy();
  expect(fetchMock.mock.calls.some(([path]) => path.includes('/import'))).toBe(false);
  expect(screen.getByText('Draft version 2')).toBeTruthy();
});

test.each([400, 409, 503])('replacement error %s retains the current draft and edit page', async (status) => {
  vi.stubGlobal('confirm', vi.fn(() => true));
  vi.stubGlobal('fetch', vi.fn(async (path: string, options?: RequestInit) => ({
    ok: options?.method !== 'PUT', status: options?.method === 'PUT' ? status : 200,
    json: async () => path.endsWith('/generation') ? null : options?.method === 'PUT' ? { detail: 'Replacement rejected; reload draft' } : replacementDraft,
  })));
  const { router } = renderRoute(<TaskLibrary csrf="csrf" />, '/admin/tasks/task');
  fireEvent.change(await screen.findByLabelText('Replace draft from task ZIP'), {
    target: { files: [new File(['zip'], 'task.zip', { type: 'application/zip' })] },
  });
  expect((await screen.findByRole('alert')).textContent).toBe('Replacement rejected; reload draft');
  expect(screen.getByText('Draft version 2')).toBeTruthy();
  expect((screen.getByLabelText('Title') as HTMLInputElement).value).toBe('Original');
  expect(router.state.location.search).toBe('');
});

test('replacement is disabled until unsaved settings, cases and generation edits are cleared', async () => {
  vi.stubGlobal('fetch', vi.fn(async (path: string) => ({ ok: true, status: 200,
    json: async () => path.endsWith('/generation') ? null : replacementDraft })));
  renderRoute(<TaskLibrary csrf="csrf" />, '/admin/tasks/task');
  const field = await screen.findByLabelText('Replace draft from task ZIP') as HTMLInputElement;
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Unsaved' } });
  expect(field.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Original' } });
  expect(field.disabled).toBe(false);
  fireEvent.change(screen.getByLabelText('Case input'), { target: { value: 'unsaved case' } });
  expect(field.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Case input'), { target: { value: '' } });
  expect(field.disabled).toBe(false);
  fireEvent.change(screen.getByLabelText('Generator source'), { target: { value: 'print(1)' } });
  await waitFor(() => expect(field.disabled).toBe(true));
});

test("optional banned identifiers and operators save on draft and appear in review", async () => {
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  let config = { title: "No printf", statement: "", scoring: "partial", banned_identifiers: [] as string[],
    checker: { kind: "exact", ignore_final_newline: false, ignore_case: false, absolute_tolerance: "0", relative_tolerance: "0" },
    cpu_seconds: 2, wall_seconds: 6, memory_mib: 256, stack_mib: 8, stdout_mib: 10 };
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/admin/tasks/task" && options?.method === "PUT") config = JSON.parse(String(options.body)).config;
    return { ok: true, status: 200, json: async () => path.endsWith("/generation") ? null :
      { id: "task", version: 1, config, case_count: 0, cases: [], revisions: [] } };
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<TaskLibrary csrf="csrf" />, "/admin/tasks/task");
  fireEvent.change(await screen.findByLabelText("Banned identifiers and operators (optional, one per line)"),
    { target: { value: "for\n+\n-\n*\n/\n" } });
  fireEvent.change(screen.getByLabelText("Permitted languages"), { target: { value: "cpp17" } });
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  expect(await screen.findByText("Draft saved.")).toBeTruthy();
  expect(fetchMock.mock.calls.some(([path, options]) => path === "/api/admin/tasks/task" && options?.method === "PUT" &&
    JSON.parse(String(options.body)).config.banned_identifiers.join(",") === "for,+,-,*,/")).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Review draft" }));
  expect((await screen.findByText("for, +, -, *, /")).className).toContain("text-red-900");
  expect(await screen.findByText("Languages: C++17")).toBeTruthy();
});
