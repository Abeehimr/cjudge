import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AdminSubmissions, StudentSubmissions } from "./Submissions";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const admission = { allowed: true, reason: "", code: "", pending: 0, retry_at: null, server_time: "2026-09-30T00:00:00Z" };
const tasks = [{ revision_id: "revision", title: "Sum" }];

test("unconfirmed upload retries identical source with the same idempotency key", async () => {
  let attempts = 0;
  const fetchMock = vi.fn().mockImplementation((path: string, options: RequestInit) => {
    if (options.method === "POST") {
      attempts++;
      if (attempts === 1) return Promise.reject(new TypeError("Connection lost"));
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ id: "accepted", filename: "main.c", accepted_at: admission.server_time }) });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => [] });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<StudentSubmissions labId="lab" tasks={tasks} admission={admission} csrf="csrf" refresh={vi.fn().mockResolvedValue(undefined)} />);
  const file = new File(["int main(void){return 0;}"], "main.c");
  fireEvent.change(screen.getByLabelText(/C file/), { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "Submit" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry upload" }));
  expect(await screen.findByText(/Accepted main.c/)).toBeTruthy();
  const calls = fetchMock.mock.calls.filter(([, options]) => options.method === "POST");
  expect(calls).toHaveLength(2);
  expect(calls[0][1].headers["Idempotency-Key"]).toBe(calls[1][1].headers["Idempotency-Key"]);
  expect(calls[0][1].body).toBe(file);
  expect(calls[0][1].headers["X-CSRF-Token"]).toBe("csrf");
});

test("pending limit disables new uploads with its reason", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [] }));
  render(<StudentSubmissions labId="lab" tasks={tasks} admission={{ ...admission, allowed: false, pending: 3, reason: "Three submissions are pending", code: "pending_limit" }} csrf="csrf" refresh={vi.fn()} />);
  fireEvent.change(screen.getByLabelText(/C file/), { target: { files: [new File(["x"], "main.c")] } });
  await waitFor(() => expect((screen.getByRole("button", { name: "Submit" }) as HTMLButtonElement).disabled).toBe(true));
  expect(screen.getByText(/Three submissions are pending/)).toBeTruthy();
});

test("saving feedback refreshes the parent lab version before further edits", async () => {
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  vi.stubGlobal("fetch", vi.fn().mockImplementation((path: string, options: RequestInit) => Promise.resolve({
    ok: true, status: options.method === "PUT" ? 204 : 200, json: async () => [],
  })));
  const refreshLab = vi.fn().mockResolvedValue(undefined);
  render(<AdminSubmissions labId="lab" csrf="csrf" feedback="short" refreshLab={refreshLab} />);
  fireEvent.change(screen.getByLabelText("Student compiler feedback"), { target: { value: "none" } });
  fireEvent.click(screen.getByRole("button", { name: "Save compiler feedback" }));
  await waitFor(() => expect(refreshLab).toHaveBeenCalledTimes(1));
});
