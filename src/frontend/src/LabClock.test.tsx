import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import LabClock from "./LabClock";

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

test("countdown uses elapsed monotonic time and refreshes only at boundaries", () => {
  vi.useFakeTimers();
  let elapsed = 0;
  vi.spyOn(performance, "now").mockImplementation(() => elapsed);
  const refresh = vi.fn();
  render(<LabClock serverTime="2026-09-30T00:00:00Z" start="2026-09-30T00:00:02Z" end="2026-09-30T00:00:05Z" refresh={refresh} />);
  act(() => { elapsed = 1000; vi.advanceTimersByTime(1000); });
  expect(refresh).not.toHaveBeenCalled();
  act(() => { elapsed = 2000; vi.advanceTimersByTime(1000); });
  expect(screen.getByRole("timer").textContent).toContain("Time remaining");
  expect(refresh).toHaveBeenCalledTimes(1);
  act(() => { elapsed = 5000; vi.advanceTimersByTime(3000); });
  expect(screen.getByRole("timer").textContent).toBe("Lab ended.");
  expect(refresh).toHaveBeenCalledTimes(2);
});
