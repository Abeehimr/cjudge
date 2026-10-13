import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import TAAssignments, { AdminTADetail } from "./TAAssignments";
import type { AdminLab } from "./Lab";
import { MemoryRouter } from "react-router";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("admin saves versioned TA assignments without linking unsaved assignments", async () => {
  const ta = { id: "ta", username: "HELPER", name: "Helper", active: true };
  const lab = { id: "lab", version: 7, tas: [], archived_at: null } as unknown as AdminLab;
  const onSave = vi.fn();
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path === "/api/admin/tas" ? [ta] : { ...lab, version: 8, tas: [ta] },
  }));
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter><TAAssignments lab={lab} csrf="csrf" onSave={onSave} /></MemoryRouter>);
  fireEvent.click(await screen.findByLabelText("Assign HELPER"));
  expect(screen.queryByRole("link", { name: "View TA" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Save assignments" }));
  await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
  expect(fetchMock).toHaveBeenCalledWith("/api/admin/labs/lab/tas", expect.objectContaining({
    method: "PUT", body: JSON.stringify({ version: 7, ids: ["ta"] }),
    headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
});

test("admin lab TA page shows current penalties and student-linked activity", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200,
    json: async () => ({ ta: { id: "ta", username: "HELPER", name: "Helper", active: true,
      assigned_at: "2026-10-13T00:00:00Z" }, penalties: [{ id: "student", roll_number: "001A", name: "Ada",
      frozen: true, freeze_reason: "Exam rule", cancelled: true, cancel_reason: "Cancelled rule" }],
      activity: [{ action: "lab_student_frozen", detail: { reason: "Exam rule" }, created_at: "2026-10-13T00:00:00Z",
        student_id: "student", roll_number: "001A", name: "Ada" },
        { action: "lab_student_reinstated", detail: { reason: "Resolved" }, created_at: "2026-10-13T00:01:00Z",
          student_id: "student", roll_number: "001A", name: "Ada" }] }),
  }));
  render(<MemoryRouter><AdminTADetail labId="lab" taId="ta" /></MemoryRouter>);
  expect(await screen.findByText(/Assigned/)).toBeTruthy();
  expect(screen.getAllByRole("link", { name: "001A · Ada" })).toHaveLength(4);
  expect(screen.getAllByRole("table")).toHaveLength(2);
  expect(screen.getAllByText("Frozen")).toHaveLength(2);
  expect(screen.getAllByText("Frozen").every((cell) => cell.closest("tr")?.getAttribute("data-frozen") === "true")).toBe(true);
  expect(screen.getByText("Cancelled").closest("tr")?.getAttribute("data-cancelled")).toBe("true");
  expect(screen.getByText("Reinstated").closest("tr")?.getAttribute("data-restored")).toBe("true");
});
