import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { useState } from "react";
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

test("expanded case survives a live refresh and passing cases explain hidden streams", async () => {
  let resolveRefresh: (value: unknown) => void;
  const payload = { id: "submission", filename: "main.c", source: "code", status: "Passed", accepted_at: "2026-09-30",
    official_marks: "10.00", marks: "10.00", passed: 1, total: 1, history: [],
    cases: [{ number: 1, verdict: "AC", stdin: null, expected: null, stdout: null, stderr: null, cpu_seconds: 0, wall_seconds: 0, memory_kib: 1 }] };
  const fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => payload })
    .mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve; }));
  vi.stubGlobal("fetch", fetch);
  function LiveDetail() {
    const [refresh, setRefresh] = useState("1");
    return <><button onClick={() => setRefresh("2")}>Live refresh</button>
      <SubmissionDetail labId="lab" submissionId="submission" visible refreshKey={refresh} /></>;
  }
  const view = renderRoute(<LiveDetail />, "/labs/lab/submissions/submission");
  const summary = await screen.findByText(/Case 1: AC/);
  fireEvent.click(summary);
  expect(summary.closest("details")!.open).toBe(true);
  expect(screen.getByText(/Passed case. Test streams/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Live refresh" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(screen.getByText(/Case 1: AC/).closest("details")!.open).toBe(true);
  resolveRefresh!({ ok: true, json: async () => payload });
  await waitFor(() => expect(screen.getByText(/Case 1: AC/).closest("details")!.open).toBe(true));
  view.unmount();
});
