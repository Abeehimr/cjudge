import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import TALabs from "./TALabs";
import { renderRoute } from "./testRouter";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("TA sees pre-release evidence, reveals password with one click, and clears it on navigation", async () => {
  const lab = { id: "lab", title: "Lab 1", phase: "Running", starts_at: null, ends_at: null,
    server_time: "2026-10-13T00:00:00Z", results_visible: false, archived: false };
  const student = { id: "student", roll_number: "001A", name: "Ada", frozen: false, freeze_reason: null,
    frozen_by_name: null, cancelled: false, cancel_reason: null, cancelled_by_name: null,
    bound: true, ip_changed: false, submission_count: 2, last_submission_at: "2026-10-13T00:00:00Z" };
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  vi.stubGlobal("confirm", vi.fn(() => { throw Error("No password confirmation expected"); }));
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path === "/api/ta/labs" ? [lab]
      : path === "/api/ta/labs/lab" ? lab
      : path.endsWith("/password") ? { password: "private" }
      : path.endsWith("/marks") ? [{ id: "student", roll_number: "001A", name: "Ada", cancelled: false,
        tasks: [], total: "0.00", pending: false, submission_count: 2 }]
      : path.includes("/submissions?offset=") ? [] : student,
  }));
  vi.stubGlobal("fetch", fetchMock);
  const { router } = renderRoute(<TALabs csrf="csrf" />, "/ta/labs/lab/students/student");
  expect(await screen.findByText(/2 submissions/)).toBeTruthy();
  expect(screen.getByText(/Results hidden/)).toBeTruthy();
  expect(await screen.findByText("Submissions")).toBeTruthy();
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes("/submissions?offset="))).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Show password" }));
  expect(await screen.findByText(/private/)).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith("/api/ta/labs/lab/students/student/password", expect.objectContaining({
    headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }), body: JSON.stringify({}),
  }));
  await router.navigate("/ta/labs");
  await waitFor(() => expect(screen.queryByText(/private/)).toBeNull());
});

test("TA evidence links to a standalone student submission before release", async () => {
  const lab = { id: "lab", title: "Lab 1", phase: "Running", starts_at: null, ends_at: null,
    server_time: "2026-10-13T00:00:00Z", results_visible: false, archived: false };
  const student = { id: "student", roll_number: "001A", name: "Ada", frozen: false, freeze_reason: null,
    frozen_by_name: null, cancelled: false, cancel_reason: null, cancelled_by_name: null,
    bound: false, ip_changed: false, submission_count: 1, last_submission_at: null };
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  vi.stubGlobal("fetch", vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path === "/api/ta/labs" ? [lab] : path === "/api/ta/labs/lab" ? lab
      : path.endsWith("/submissions/sub") ? { id: "sub", filename: "answer.c", source: "int main(){}", status: "Passed",
        accepted_at: lab.server_time, marks: "5.00", maximum_marks: "5.00", official_marks: "5.00", passed: 2, total: 2,
        grading_pending: false, deleted_at: null, delete_reason: null, official_run_id: null, compiler_feedback: null,
        compiler_truncated: false, history: [], cases: [] }
      : path.endsWith("/submissions?offset=0") ? [{ id: "sub", filename: "answer.c", accepted_at: lab.server_time,
          status: "Passed", best_for_review: true, deleted_at: null, delete_reason: null, marks: "5.00", maximum_marks: "5.00", passed: 2, total: 2 }]
      : path.endsWith("/marks") ? [{ id: "student", roll_number: "001A", name: "Ada", cancelled: false,
        tasks: [], total: "5.00", pending: false, submission_count: 1 }] : student,
  })));
  const { router } = renderRoute(<TALabs csrf="csrf" />, "/ta/labs/lab/students/student");
  expect((await screen.findByRole("link", { name: "answer.c" })).getAttribute("href")).toBe("/ta/labs/lab/students/student/submissions/sub");
  expect(screen.getByText("Best for review")).toBeTruthy();
  expect(screen.getByText(/Marks 5.00/)).toBeTruthy();
  await router.navigate("/ta/labs/lab/students/student/submissions/sub");
  await waitFor(() => expect(screen.queryByRole("button", { name: "Show password" })).toBeNull());
  expect(screen.queryByRole("heading", { name: "Submissions" })).toBeNull();
});

test("search to student loads submissions without a refresh", async () => {
  const lab = { id: "lab", title: "Lab 1", phase: "Running", starts_at: null, ends_at: null,
    server_time: "2026-10-13T00:00:00Z", results_visible: false, archived: false };
  const student = { id: "student", roll_number: "001A", name: "Ada", frozen: false, freeze_reason: null,
    frozen_by_name: null, cancelled: false, cancel_reason: null, cancelled_by_name: null,
    bound: true, ip_changed: false, submission_count: 1, last_submission_at: null };
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path === "/api/ta/labs" ? [lab] : path === "/api/ta/labs/lab" ? lab
      : path.includes("students?search=") ? [student]
      : path.endsWith("/submissions?offset=0") ? [{ id: "sub", filename: "answer.c", accepted_at: lab.server_time,
          status: "Passed", best_for_review: true, deleted_at: null, delete_reason: null,
          marks: "5.00", maximum_marks: "5.00", passed: 1, total: 1 }]
      : path.endsWith("/marks") ? [{ id: "student", roll_number: "001A", name: "Ada", cancelled: false,
        tasks: [], total: "5.00", pending: false, submission_count: 1 }] : student,
  }));
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<TALabs csrf="csrf" />, "/ta/labs/lab?search=Ada");
  fireEvent.click(await screen.findByRole("link", { name: "001A · Ada" }));
  expect(await screen.findByRole("link", { name: "answer.c" })).toBeTruthy();
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes("/students/student/marks"))).toBe(true);
});
