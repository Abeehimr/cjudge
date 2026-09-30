import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AdminLabs, StudentLabs } from "./Labs";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const summary = { id: "lab", title: "C practice", phase: "Running", starts_at: "2020-01-01T00:00:00Z", ends_at: "2099-01-01T00:00:00Z", server_time: "2026-09-30T00:00:00Z" };
const materials = { ...summary, frozen: false, tasks: [{ position: 1, revision_id: "revision", title: "Addition", statement: "Add two numbers.", maximum_marks: "10", cpu_seconds: 1, wall_seconds: 2, memory_mib: 64 }], pdfs: [], announcements: [] };

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

test("admin freeze requires a reason and sends the lab-specific action", async () => {
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  const member = { id: "student", roll_number: "001A", name: "Ada", frozen: false, freeze_reason: null, bound_at: null, bound_ip: null, last_ip: null, ip_changed: false };
  const lab = { ...summary, version: 1, strict_ip: false, first_released_at: null, tasks: [], pdfs: [], students: [member], announcements: [] };
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: path.endsWith("/freeze") ? 204 : 200,
    json: async () => path === "/api/admin/labs?offset=0" ? [summary] : path === "/api/admin/labs/lab" ? lab : [] }));
  vi.stubGlobal("fetch", fetchMock);
  const promptMock = vi.fn().mockReturnValueOnce("").mockReturnValueOnce("Review required");
  vi.stubGlobal("prompt", promptMock);
  render(<AdminLabs csrf="csrf" />);
  fireEvent.click(await screen.findByRole("button", { name: "C practice" }));
  fireEvent.click(await screen.findByRole("button", { name: "Freeze 001A" }));
  expect(fetchMock.mock.calls.some(([path]) => path.endsWith("/freeze"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Freeze 001A" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/admin/labs/lab/students/student/freeze", expect.objectContaining({
    method: "POST", body: JSON.stringify({ reason: "Review required", frozen: true }), headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  })));
});
