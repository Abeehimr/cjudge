import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import TaskLibrary from "./TaskLibrary";
import { renderRoute } from "./testRouter";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

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
  fireEvent.change(screen.getByLabelText("Case input"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Expected output"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "Add pasted case" }));
  expect(await screen.findByText("Draft version 2")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Review draft" }));
  fireEvent.click(screen.getByRole("button", { name: "Publish reviewed draft" }));
  expect(await screen.findByText("Revision 1 published.")).toBeTruthy();
  expect(await screen.findByRole("heading", { name: "Revision 1 (read-only)" })).toBeTruthy();
  cleanup();
  renderRoute(<TaskLibrary csrf="csrf" />, "/admin/tasks/task?revision=revision");
  expect(await screen.findByRole("heading", { name: "Revision 1 (read-only)" })).toBeTruthy();
  expect(screen.queryByLabelText("Title")).toBeNull();
  expect(fetchMock).toHaveBeenCalledWith("/api/admin/tasks/task/publish", expect.objectContaining({
    headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
    body: JSON.stringify({ version: 2 }),
  }));
});
