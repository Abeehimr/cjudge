import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
