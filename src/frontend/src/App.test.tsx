import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import App from "./App";

afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

test("theme toggle stays selected after reopening the app", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }));
  const view = render(<App />);
  const toggle = screen.getByRole("button", { name: "Dark theme" });
  fireEvent.click(toggle);
  expect(localStorage.getItem("cjudge-theme")).toBe("dark");
  expect(toggle.getAttribute("aria-pressed")).toBe("true");
  expect(toggle.closest(".theme-dark")).toBeTruthy();
  view.unmount();
  render(<App />);
  expect(screen.getByRole("button", { name: "Light theme" }).getAttribute("aria-pressed")).toBe("true");
});

test("shows login when session is absent", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }));
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
  expect(screen.getByLabelText("Username or roll number")).toBeTruthy();
  expect(screen.queryByRole("group", { name: "Account type" })).toBeNull();
});

test("student sees own identity after login", async () => {
  const account = { id: "1", role: "student", roll_number: "001A", name: "Ada", csrf_token: "csrf" };
  vi.stubGlobal("fetch", vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200, json: async () => path.endsWith("/labs") ? [] : account })));
  render(<App />);
  expect(await screen.findByText("Roll number: 001A")).toBeTruthy();
  expect(await screen.findByText("No labs assigned yet.")).toBeTruthy();
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

 test.each([["  AdMiN  ", "admin", "AdMiN"], [" 001a ", "student", "001a"]])("unified login routes %s and prevents duplicate submission", async (input, role, identifier) => {
  let complete!: (value: unknown) => void;
  const fetchMock = vi.fn().mockImplementation((path: string) => path.endsWith("/login")
    ? new Promise((resolve) => { complete = resolve; })
    : Promise.resolve({ ok: false, json: async () => ({}) }));
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Username or roll number"), { target: { value: input } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect((screen.getByRole("button", { name: "Signing in…" }) as HTMLButtonElement).disabled).toBe(true);
  expect(fetchMock).toHaveBeenCalledWith(`/api/auth/${role}/login`, expect.objectContaining({ body: JSON.stringify({ identifier, password: "wrong" }) }));
  complete({ ok: false, status: 401, json: async () => ({ detail: "Invalid credentials" }) });
  expect(await screen.findByText("Invalid credentials")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Sign in" }) as HTMLButtonElement).disabled).toBe(false);
});
