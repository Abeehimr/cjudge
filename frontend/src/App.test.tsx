import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import App from "./App";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("shows login when session is absent", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }));
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
  expect(screen.getByLabelText("Roll number")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Admin" }));
  expect(screen.getByLabelText("Username")).toBeTruthy();
});

test("student sees own identity after login", async () => {
  const account = { id: "1", role: "student", roll_number: "001A", name: "Ada", csrf_token: "csrf" };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => account }));
  render(<App />);
  expect(await screen.findByText("Roll number: 001A")).toBeTruthy();
  expect(screen.getByText("No labs assigned yet.")).toBeTruthy();
});

test("admin reveals selected credentials only after an explicit action", async () => {
  const admin = { id: "admin", role: "admin", roll_number: null, name: "Administrator", csrf_token: "csrf" };
  const student = { id: "student", roll_number: "001A", name: "Ada" };
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({
    ok: true, status: 200,
    json: async () => path.endsWith("/auth/session") ? admin
      : path.endsWith("/admin/students") ? [student]
      : [{ ...student, password: "PRIVATE-PASS" }],
  }));
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  expect(await screen.findByText("001A")).toBeTruthy();
  expect(screen.queryByText("PRIVATE-PASS")).toBeNull();
  fireEvent.click(screen.getByLabelText("Select 001A"));
  fireEvent.click(screen.getByRole("button", { name: "Show selected credentials" }));
  expect(await screen.findByText("PRIVATE-PASS")).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith("/api/admin/students/credentials", expect.objectContaining({
    headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
  fireEvent.click(screen.getByRole("button", { name: "Hide" }));
  expect(screen.queryByText("PRIVATE-PASS")).toBeNull();
});
