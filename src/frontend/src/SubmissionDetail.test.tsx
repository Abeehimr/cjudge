import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import SubmissionDetail from "./SubmissionDetail";
import { renderRoute } from "./testRouter";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
test("student detail deep link shows escaped code and restores retained-run selection", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "submission", filename: "main.c", source: "<script>hidden</script>",
    status: "Failed", accepted_at: "2026-09-30", marks: "0.00", official_marks: "0.00", passed: 0, total: 1,
    history: [], cases: [{ number: 1, verdict: "WA", stdin: "2 3", expected: "5", stdout: "6", stderr: "", cpu_seconds: 0, wall_seconds: 0, memory_kib: 1 }] }) });
  vi.stubGlobal("fetch", fetch);
  const { router } = renderRoute(<SubmissionDetail labId="lab" submissionId="submission" visible refreshKey="1" />, "/labs/lab/submissions/submission");
  expect(await screen.findByText("<script>hidden</script>")).toBeTruthy();
  expect(document.querySelector("script")).toBeNull();
  expect(screen.getByText("Expected output")).toBeTruthy();
  await router.navigate("/labs/lab/submissions/submission?run=old");
  await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/labs/lab/submissions/submission/details?run_id=old", expect.anything()));
});

test("hidden student details never request private data", () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  renderRoute(<SubmissionDetail labId="lab" submissionId="submission" visible={false} refreshKey="1" />, "/labs/lab/submissions/submission");
  expect(screen.getByText(/details are hidden/)).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
});
