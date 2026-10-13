import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import TALabs from "./TALabs";
import { renderRoute } from "./testRouter";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("TA sees only compact live status and clears a revealed password on navigation", async () => {
  const lab = { id: "lab", title: "Lab 1", phase: "Running", starts_at: null, ends_at: null,
    server_time: "2026-10-13T00:00:00Z", results_visible: false, archived: false };
  const student = { id: "student", roll_number: "001A", name: "Ada", frozen: false, freeze_reason: null,
    frozen_by_name: null, cancelled: false, cancel_reason: null, cancelled_by_name: null,
    bound: true, ip_changed: false, submission_count: 2, last_submission_at: "2026-10-13T00:00:00Z" };
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  vi.stubGlobal("confirm", vi.fn(() => true));
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path === "/api/ta/labs" ? [lab]
      : path === "/api/ta/labs/lab" ? lab
      : path.endsWith("/password") ? { password: "private" } : student,
  }));
  vi.stubGlobal("fetch", fetchMock);
  const { router } = renderRoute(<TALabs csrf="csrf" />, "/ta/labs/lab/students/student");
  expect(await screen.findByText(/2 submissions/)).toBeTruthy();
  expect(screen.getByText(/Results hidden/)).toBeTruthy();
  expect(screen.queryByText("Released submissions")).toBeNull();
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes("/submissions"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Show password" }));
  expect(await screen.findByText(/private/)).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith("/api/ta/labs/lab/students/student/password", expect.objectContaining({
    headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }), body: JSON.stringify({ confirm: true }),
  }));
  await router.navigate("/ta/labs");
  await waitFor(() => expect(screen.queryByText(/private/)).toBeNull());
});

test("released TA evidence links to a student submission", async () => {
  const lab = { id: "lab", title: "Lab 1", phase: "Results released", starts_at: null, ends_at: null,
    server_time: "2026-10-13T00:00:00Z", results_visible: true, archived: false };
  const student = { id: "student", roll_number: "001A", name: "Ada", frozen: false, freeze_reason: null,
    frozen_by_name: null, cancelled: false, cancel_reason: null, cancelled_by_name: null,
    bound: false, ip_changed: false, submission_count: 1, last_submission_at: null };
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  vi.stubGlobal("fetch", vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path === "/api/ta/labs" ? [lab] : path === "/api/ta/labs/lab" ? lab
      : path.endsWith("/submissions?offset=0") ? [{ id: "sub", filename: "answer.c", accepted_at: lab.server_time,
          status: "Passed", best_for_review: true, deleted_at: null, delete_reason: null }] : student,
  })));
  renderRoute(<TALabs csrf="csrf" />, "/ta/labs/lab/students/student");
  expect((await screen.findByRole("link", { name: "answer.c" })).getAttribute("href")).toBe("/ta/labs/lab/students/student/submissions/sub");
  expect(screen.getByText("Best for review")).toBeTruthy();
});
