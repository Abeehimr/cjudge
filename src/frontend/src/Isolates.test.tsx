import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import Isolates from "./Isolates";

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

test("worker heartbeat expires locally without health polling", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ configured: 1, healthy: 1, working: 0,
    server_time: "2026-09-30T00:00:00Z", workers: [{ slot: 0, state: "Idle", healthy: true, heartbeat_at: "2026-09-30T00:00:00Z",
      started_at: "2026-09-30T00:00:00Z", lease_until: null, submission_id: null, completed: 2, fault: null }] }) });
  vi.stubGlobal("fetch", fetchMock);
  await act(async () => { render(<Isolates />); });
  expect(screen.getByText("1 configured · 1 healthy · 0 working")).toBeTruthy();
  await act(async () => { vi.advanceTimersByTime(90050); });
  expect(screen.getByText("Offline")).toBeTruthy();
  expect(screen.getByText("1 configured · 0 healthy · 0 working")).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
