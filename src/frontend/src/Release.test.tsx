import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { render } from "@testing-library/react";
import Release from "./Release";
import type { AdminLab } from "./Lab";

const lab: AdminLab = { id: "lab", title: "Practice", version: 3, phase: "Archived", strict_ip: false,
  starts_at: "2026-09-30T00:00:00Z", ends_at: "2026-09-30T01:00:00Z", server_time: "2026-09-30T02:00:00Z",
  first_released_at: "2026-09-30T01:01:00Z", reveal_results: true, archived_at: "2026-09-30T01:02:00Z",
  tasks: [], students: [], pdfs: [], announcements: [] };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
test("permanent deletion requires export, saved-copy acknowledgment and matching title", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "export", sha256: "checksum", size: 123 }) });
  vi.stubGlobal("fetch", fetch); vi.stubGlobal("prompt", vi.fn().mockReturnValue("Retain evidence")); vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
  const deleted = vi.fn();
  render(<Release lab={lab} csrf="csrf" accept={vi.fn()} deleted={deleted} />);
  expect(screen.queryByRole("button", { name: "Permanently delete lab" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Generate lab ZIP" }));
  const button = await screen.findByRole("button", { name: "Permanently delete lab" });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByRole("link", { name: "Download lab ZIP" }).getAttribute("href")).toBe("/api/admin/labs/lab/exports/export");
  fireEvent.click(screen.getByRole("checkbox"));
  expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Type lab title to confirm"), { target: { value: "Practice" } });
  expect((button as HTMLButtonElement).disabled).toBe(false);
  fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ cleanup_pending: 0 }) });
  fireEvent.click(button);
  await waitFor(() => expect(deleted).toHaveBeenCalledOnce());
  expect(fetch).toHaveBeenLastCalledWith("/api/admin/labs/lab", expect.objectContaining({ method: "DELETE",
    body: JSON.stringify({ version: 3, export_id: "export", title: "Practice", saved_copy: true, reason: "Retain evidence" }) }));
});
