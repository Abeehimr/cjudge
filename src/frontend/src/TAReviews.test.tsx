import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { renderRoute } from "./testRouter";
import { AdminTAReviews, StudentTAReview } from "./TAReviews";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("TA claims, saves zero marks, and finalizes only completed tasks", async () => {
  const base = { student_id: "student", cancelled: false, owner_id: null, owner_name: null,
    reviewer_name: null, version: 0, finalized: false, needs_recheck: false, total: "0.00", provisional: true,
    tasks: [{ task_id: "task", title: "Sum", maximum: "5.00", marks: null, done: false }] };
  let current: typeof base | (Omit<typeof base, "owner_id" | "owner_name" | "tasks"> & {
    owner_id: string | null; owner_name: string | null;
    tasks: { task_id: string; title: string; maximum: string; marks: string | null; done: boolean }[] }) = base;
  const fetchMock = vi.fn().mockImplementation((_path: string, options?: RequestInit) => {
    if (options?.method === "POST" && _path.endsWith("/claim")) current = { ...current, owner_id: "ta", owner_name: "TA", version: 1 };
    if (options?.method === "PUT") current = { ...current, version: 2,
      tasks: [{ ...current.tasks[0], marks: "0.00", done: true }] };
    if (options?.method === "POST" && _path.endsWith("/finalize")) current = { ...current, version: 3, finalized: true, provisional: false };
    return Promise.resolve({ ok: true, status: 200, json: async () => current });
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<StudentTAReview labId="lab" studentId="student" csrf="csrf" accountId="ta"
    released archived={false} refreshKey={0} />, "/ta/labs/lab/students/student");
  fireEvent.click(await screen.findByRole("button", { name: "Claim student" }));
  fireEvent.click(await screen.findByRole("checkbox", { name: "Done" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save task" }));
  fireEvent.click(await screen.findByRole("button", { name: "Finalize" }));
  expect(await screen.findByText(/Finalized/)).toBeTruthy();
  expect(fetchMock.mock.calls.some(([path, options]) => String(path).endsWith("/tasks/task") &&
    JSON.parse(options.body).marks === "0.00" && JSON.parse(options.body).done)).toBe(true);
});

test("admin review list shows separate totals and incomplete status", async () => {
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({
    total: 1, remaining: 1, students: [{ id: "student", roll_number: "001", name: "Ada",
      cancelled: false, automatic_total: "4.00", ta_total: "2.50", combined_total: "6.50",
      review: { owner_id: "ta", owner_name: "TA One", finalized: false, needs_recheck: false, provisional: true } }],
  }) }));
  renderRoute(<AdminTAReviews labId="lab" csrf="csrf" archived={false} tas={[]} />, "/admin/labs/lab/reviews");
  expect(await screen.findByText("1 remaining / 1 active students")).toBeTruthy();
  expect(screen.getByText("6.50")).toBeTruthy();
  expect(screen.getByText(/TA One · Provisional/)).toBeTruthy();
});
