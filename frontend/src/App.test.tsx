import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import App from "./App";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test.each([true, false])("shows readiness for response.ok=%s", async (ok) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok }));
  render(<App />);
  expect((await screen.findByRole("status")).textContent).toBe(ok ? "Service ready" : "Service unavailable");
});
