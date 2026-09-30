import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import Generation from "./Generation";
import { renderRoute } from "./testRouter";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("generation preserves exact seeds, requires review confirmation, and escapes diagnostics", async () => {
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  vi.stubGlobal("confirm", vi.fn(() => false));
  let job: object | null = null;
  const applied = vi.fn(async () => {});
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (options?.method === "POST" && path.endsWith("/generation")) job = {
      id: "job", base_version: 1, state: "complete", progress: 1, config: { count: 1, seed: "9223372036854775807" },
      diagnostic: "<img src=x onerror=alert(1)>", cases: [{ number: 1, seed: "9223372036854775807", input_size: 2, answer_size: 2 }],
    };
    return { ok: true, status: 200, json: async () => job };
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Generation taskId="task" version={1} csrf="csrf" disabled={false} applied={applied} onDirty={vi.fn()} />, "/admin/tasks/task");
  fireEvent.change(screen.getByLabelText("Generator source"), { target: { value: "print(1)" } });
  fireEvent.change(screen.getByLabelText("Reference C source"), { target: { value: "int main(){}" } });
  fireEvent.change(screen.getByLabelText("Starting seed"), { target: { value: "9223372036854775807" } });
  fireEvent.click(screen.getByRole("button", { name: "Start generation" }));
  expect(await screen.findByText("Generation complete: 1/1 cases · draft 1")).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith("/api/admin/tasks/task/generation", expect.objectContaining({
    body: '{"version":1,"config":{"language":"python","generator":"print(1)","reference":"int main(){}","count":1,"seed":9223372036854775807}}',
    headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
  expect(document.querySelector("img")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Apply reviewed cases" }));
  expect(applied).not.toHaveBeenCalled();
  vi.stubGlobal("confirm", vi.fn(() => true));
  fireEvent.click(screen.getByRole("button", { name: "Apply reviewed cases" }));
  await vi.waitFor(() => expect(applied).toHaveBeenCalledOnce());
});

test("draft changes disable applying generated cases", async () => {
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({
    id: "job", base_version: 1, state: "complete", progress: 1, config: { count: 1 }, diagnostic: "", cases: [],
  }) }));
  renderRoute(<Generation taskId="task" version={2} csrf="csrf" disabled={false} applied={vi.fn()} onDirty={vi.fn()} />, "/admin/tasks/task");
  const button = await screen.findByRole("button", { name: "Apply reviewed cases" });
  expect((button as HTMLButtonElement).disabled).toBe(true);
});
