import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import Accounts, { credentialCsv } from "./Accounts";
import { renderRoute } from "./testRouter";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const ada = { id: "a", roll_number: "A1", name: "Ada" };
const bob = { id: "b", roll_number: "B2", name: "Bob" };

test("roster search retains explicit selection and bulk reset uses selected IDs", async () => {
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path.includes("?search=B") ? [bob] : path.endsWith("/reset")
      ? [{ ...ada, password: "abc123" }, { ...bob, password: "def456" }] : [ada, bob] }));
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("confirm", vi.fn(() => true));
  vi.stubGlobal("prompt", vi.fn(() => null));
  renderRoute(<Accounts csrf="csrf" />, "/admin/students");
  const row = (await screen.findByText("A1")).closest("tr")!;
  fireEvent.click(row);
  expect(screen.getByText(/selected 1/)).toBeTruthy();
  fireEvent.click(screen.getAllByRole("button", { name: "Edit name" })[0]);
  expect(screen.getByText(/selected 1/)).toBeTruthy();
  fireEvent.keyDown(row, { key: " " });
  expect(screen.getByText(/selected 0/)).toBeTruthy();
  fireEvent.keyDown(row, { key: "Enter" });
  expect(screen.getByText(/selected 1/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Search students"), { target: { value: "B" } });
  await waitFor(() => expect(screen.queryByText("A1")).toBeNull());
  fireEvent.click(screen.getByLabelText("Select all visible students"));
  expect(screen.getByText(/selected 2/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Reset selected passwords" }));
  await screen.findByText("abc123");
  expect(fetchMock).toHaveBeenCalledWith("/api/admin/students/reset", expect.objectContaining({
    body: JSON.stringify({ ids: ["a", "b"] }), headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
});

test("CSV quotes cells and neutralizes spreadsheet formulas", () => {
  expect(credentialCsv([{ ...ada, roll_number: "=bad", name: 'A,"B', password: "abc123" }]))
    .toBe('\ufeff"roll_number","name","password"\r\n"\'=bad","A,""B","abc123"\r\n');
});
