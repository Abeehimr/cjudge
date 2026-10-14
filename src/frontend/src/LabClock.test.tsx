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
  expect(screen.queryByRole('progressbar')).toBeNull();
  act(() => { elapsed = 1000; vi.advanceTimersByTime(1000); });
  expect(refresh).not.toHaveBeenCalled();
  act(() => { elapsed = 2000; vi.advanceTimersByTime(1000); });
  expect(screen.getByRole("timer").textContent).toContain("Time remaining");
  expect((screen.getByRole('progressbar') as HTMLProgressElement).value).toBe(0);
  expect(refresh).toHaveBeenCalledTimes(1);
  act(() => { elapsed = 5000; vi.advanceTimersByTime(3000); });
  expect(screen.getByRole("timer").textContent).toBe("Lab ended.");
  expect((screen.getByRole('progressbar') as HTMLProgressElement).value).toBe(100);
  expect(refresh).toHaveBeenCalledTimes(2);
});

test('an extension recalculates progress using the updated server schedule', () => {
  const refresh = vi.fn();
  const view = render(<LabClock serverTime="2026-09-30T01:00:00Z" start="2026-09-30T00:00:00Z" end="2026-09-30T02:00:00Z" refresh={refresh} />);
  expect((screen.getByRole('progressbar') as HTMLProgressElement).value).toBeCloseTo(50);
  view.rerender(<LabClock serverTime="2026-09-30T01:00:00Z" start="2026-09-30T00:00:00Z" end="2026-09-30T04:00:00Z" refresh={refresh} />);
  expect((screen.getByRole('progressbar') as HTMLProgressElement).value).toBeCloseTo(25);
  expect(refresh).not.toHaveBeenCalled();
});
