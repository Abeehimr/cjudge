import { cleanup, fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import TaskTester from "./TaskTester";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("admin uploads one source with CSRF and sees case streams as text", async () => {
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  const source = { id: "source", filename: "main.cpp", language: "cpp17", state: "complete", progress: 2, passed: 1,
    total: 1, verdict: "AC", percentage: 100, compiler_feedback: "", compiler_truncated: false, diagnostic: "" };
  const batch = { id: "batch", revision_id: "revision", created_at: "2026-10-12T00:00:00Z", sources: [source] };
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => ({ ok: true,
    status: options?.method === "POST" ? 201 : 200,
    json: async () => options?.method === "POST" ? batch : path.endsWith("/cases/1") ? {
      number: 1, verdict: "AC", cpu_seconds: 0.1, wall_seconds: 0.2, memory_kib: 100,
      stdin: { text: "2\n", truncated: false }, expected: { text: "4\n", truncated: false },
      stdout: { text: "<script>alert(1)</script>", truncated: false },
      stderr: { text: "", truncated: false }, stdout_truncated: false, stderr_truncated: false,
    } : path.endsWith("/sources/source") ? { source, code: "int main(){}", cases: [{ number: 1, verdict: "AC", cpu_seconds: 0.1, wall_seconds: 0.2, memory_kib: 100 }] } : [batch],
  }));
  vi.stubGlobal("fetch", fetchMock);
  const router = createMemoryRouter([{ path: "/admin/tasks/:taskId/tester/:batchId?/:sourceId?",
    element: <TaskTester csrf="secret" /> }], { initialEntries: ["/admin/tasks/task/tester?revision=revision"] });
  render(<RouterProvider router={router} />);
  const input = screen.getByLabelText("C/C++ source or ZIP");
  fireEvent.change(input, { target: { files: [new File(["int main(){}"], "main.cpp")] } });
  fireEvent.click(screen.getByRole("button", { name: "Test sources" }));
  await screen.findByText("Test batch queued.");
  expect(fetchMock).toHaveBeenCalledWith("/api/admin/tasks/task/tester?revision_id=revision", expect.objectContaining({
    method: "POST", headers: expect.objectContaining({ "X-CSRF-Token": "secret", "X-Filename": "main.cpp" }),
  }));
  await router.navigate("/admin/tasks/task/tester/batch/source?revision=revision&case=1");
  expect(await screen.findByText("<script>alert(1)</script>")).toBeTruthy();
  expect(document.querySelector("script")).toBeNull();
});

const source = { id: "source", filename: "main.c", language: "c17", state: "complete", progress: 2, passed: 1,
  total: 2, verdict: "WA", percentage: 50, compiler_feedback: "warning", compiler_truncated: true, diagnostic: "" };
const cases = ["AC", "WA"].map((verdict, index) => ({ number: index + 1, verdict, cpu_seconds: 0.1, wall_seconds: 0.2, memory_kib: 100 }));
const detail = { source, code: "<script>code</script>", cases };
const batch = { id: "batch", revision_id: "revision", created_at: "2026-10-12T00:00:00Z", sources: [source] };
const streams = { ...cases[0], stdin: { text: "input", truncated: true }, expected: { text: "answer", truncated: false },
  stdout: { text: "<script>output</script>", truncated: false }, stderr: { text: "", truncated: false },
  stdout_truncated: true, stderr_truncated: false };
function setup(fetchMock: ReturnType<typeof vi.fn>, entry = "/admin/tasks/task/tester/batch?revision=revision") {
  const events: EventTarget[] = [];
  vi.stubGlobal("EventSource", class extends EventTarget { constructor() { super(); events.push(this); } close = vi.fn(); });
  vi.stubGlobal("fetch", fetchMock);
  const router = createMemoryRouter([{ path: "/admin/tasks/:taskId/tester/:batchId?/:sourceId?",
    element: <TaskTester csrf="secret" /> }], { initialEntries: [entry] });
  render(<RouterProvider router={router} />);
  return { router, events };
}
const response = (value: unknown) => ({ ok: true, json: async () => value });

test("source opens a dedicated page, lazily expands lab-style cases, and returns to its batch", async () => {
  const fetchMock = vi.fn(async (path: string) => response(path.includes("/cases/") ? streams
    : path.endsWith("/sources/source") ? detail : [batch]));
  const { router } = setup(fetchMock);
  fireEvent.click(await screen.findByRole("link", { name: "main.c" }));
  expect(await screen.findByText(detail.code)).toBeTruthy();
  expect(screen.queryByText("New test batch")).toBeNull();
  expect(screen.queryByText("Test history")).toBeNull();
  expect(fetchMock.mock.calls.some(([path]) => path.includes("/cases/"))).toBe(false);
  const summary = screen.getByText(/Case 1: AC/);
  expect(summary.closest("details")?.classList.contains("case-result")).toBe(true);
  fireEvent.click(summary);
  expect(await screen.findByText("<script>output</script>")).toBeTruthy();
  expect(screen.getByText("Standard input (truncated)")).toBeTruthy();
  expect(screen.getByText("Standard output (truncated)")).toBeTruthy();
  expect(screen.getByText("(empty)")).toBeTruthy();
  expect(document.querySelector("script")).toBeNull();
  expect(fetchMock.mock.calls.filter(([path]) => path.includes("/cases/")).map(([path]) => path))
    .toEqual(["/api/admin/tasks/task/tester/batch/sources/source/cases/1"]);
  fireEvent.click(screen.getByRole("link", { name: "Back to test batch" }));
  await screen.findByRole("link", { name: "main.c" });
  expect(router.state.location.pathname).toBe("/admin/tasks/task/tester/batch");
  expect(router.state.location.search).toBe("?revision=revision");
  expect(screen.queryByText(detail.code)).toBeNull();
  await act(() => router.navigate(-1));
  expect(await screen.findByText(detail.code)).toBeTruthy();
});

test("case errors can be retried and expanded cases survive live updates", async () => {
  let attempts = 0;
  const fetchMock = vi.fn(async (path: string) => path.includes("/cases/") && ++attempts === 1
    ? { ok: false, status: 503, json: async () => ({ detail: "Streams unavailable" }) }
    : response(path.includes("/cases/") ? streams : detail));
  const { events } = setup(fetchMock, "/admin/tasks/task/tester/batch/source?revision=revision&case=1");
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Streams unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Retry case 1" }));
  await screen.findByText("<script>output</script>");
  await act(() => { events[0].dispatchEvent(new Event("refresh")); });
  await waitFor(() => expect(attempts).toBe(3));
  await screen.findByText("<script>output</script>");
  expect(screen.getByText(/Case 1: AC/).closest("details")!.open).toBe(true);
});

test("direct submission links support failed-run retry without fetching history", async () => {
  const fetchMock = vi.fn(async (_path: string, options?: RequestInit) => options?.method === "POST"
    ? { ok: true, status: 204 } : response({ ...detail, source: { ...source, state: "failed" } }));
  setup(fetchMock, "/admin/tasks/task/tester/batch/source?revision=revision");
  fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/admin/tasks/task/tester/batch/sources/source/retry",
    expect.objectContaining({ method: "POST", headers: expect.objectContaining({ "X-CSRF-Token": "secret" }) })));
  expect(fetchMock.mock.calls.every(([path]) => path.includes("/sources/source"))).toBe(true);
});

test("late source and stream responses cannot overwrite another submission", async () => {
  let resolveOld: (value: unknown) => void = () => {};
  let resolveStreams: (value: unknown) => void = () => {};
  let calls = 0;
  const fetchMock = vi.fn((path: string) => {
    if (path.includes("/cases/")) return new Promise((resolve) => { resolveStreams = resolve; });
    if (path.endsWith("/sources/source") && ++calls > 1) return new Promise((resolve) => { resolveOld = resolve; });
    return Promise.resolve(response(path.endsWith("/sources/other")
      ? { source: { ...source, id: "other", filename: "other.c" }, code: "other code", cases } : detail));
  });
  const { router } = setup(fetchMock, "/admin/tasks/task/tester/batch/source?revision=revision&case=1");
  await screen.findByText(detail.code);
  await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => path.includes("/cases/"))).toBe(true));
  fireEvent.click(screen.getByRole("button", { name: "Refresh submission" }));
  await act(() => router.navigate("/admin/tasks/task/tester/batch/other?revision=revision"));
  await screen.findByText("other code");
  await act(async () => { resolveOld(response(detail)); resolveStreams(response(streams)); });
  expect(screen.getByText("other code")).toBeTruthy();
  expect(screen.queryByText(detail.code)).toBeNull();
  expect(screen.queryByText("<script>output</script>")).toBeNull();
});
