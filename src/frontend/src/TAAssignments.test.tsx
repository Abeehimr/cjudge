import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import TAAssignments from "./TAAssignments";
import type { AdminLab } from "./Lab";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("admin saves versioned TA assignments from lab overview", async () => {
  const ta = { id: "ta", username: "HELPER", name: "Helper", active: true };
  const lab = { id: "lab", version: 7, tas: [], archived_at: null } as unknown as AdminLab;
  const onSave = vi.fn();
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path === "/api/admin/tas" ? [ta] : { ...lab, version: 8, tas: [ta] },
  }));
  vi.stubGlobal("fetch", fetchMock);
  render(<TAAssignments lab={lab} csrf="csrf" onSave={onSave} />);
  fireEvent.click(await screen.findByLabelText("HELPER · Helper"));
  fireEvent.click(screen.getByRole("button", { name: "Save assignments" }));
  await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
  expect(fetchMock).toHaveBeenCalledWith("/api/admin/labs/lab/tas", expect.objectContaining({
    method: "PUT", body: JSON.stringify({ version: 7, ids: ["ta"] }),
    headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
});
