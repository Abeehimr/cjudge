import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App";

beforeEach(() => { history.replaceState(null, "", "/"); });

afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

test("light theme ignores saved dark preference and has no toggle", async () => {
  localStorage.setItem("cjudge-theme", "dark");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }));
  render(<App />);
  const heading = await screen.findByRole("heading", { name: "Sign in" });
  expect(heading.closest(".theme-dark")).toBeNull();
  expect(screen.queryByRole("button", { name: /theme/i })).toBeNull();
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
  expect(await screen.findByText(/Roll number: 001A/)).toBeTruthy();
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
  history.replaceState(null, "", "/admin/students");
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
  expect((await screen.findByRole("alert")).className).toContain("notice-danger");
  expect(screen.getByText("Invalid credentials")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Sign in" }) as HTMLButtonElement).disabled).toBe(false);
});

test.each(["student", "admin"])("unified %s login opens the correct view and logs out", async (role) => {
  const account = { id: "account", role, roll_number: role === "student" ? "001A" : null, name: "Ada", csrf_token: "csrf" };
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({
    ok: !path.endsWith("/auth/session"), status: path.endsWith("/logout") ? 204 : 200,
    json: async () => path.endsWith("/login") ? account : [],
  }));
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Username or roll number"), { target: { value: role === "admin" ? "admin" : "001A" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  const logout = await screen.findByRole("button", { name: "Log out" });
  if (role === "admin") expect(screen.getByRole("navigation", { name: "Admin navigation" })).toBeTruthy();
  else expect(screen.getByText(/Roll number: 001A/)).toBeTruthy();
  fireEvent.click(logout);
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith("/api/auth/logout", expect.objectContaining({ method: "POST", headers: { "X-CSRF-Token": "csrf" } }));
});

test("restores an admin deep link after login and returns to login on session expiry", async () => {
  history.replaceState(null, "", "/admin/isolates");
  vi.stubGlobal("EventSource", class extends EventTarget { close = vi.fn(); });
  const admin = { id: "admin", role: "admin", name: "Admin", csrf_token: "csrf" };
  vi.stubGlobal("fetch", vi.fn().mockImplementation((path: string) => Promise.resolve({
    ok: !path.endsWith("/auth/session"), status: path.endsWith("/auth/session") ? 401 : 200,
    json: async () => path.endsWith("/login") ? admin : { configured: 1, healthy: 0, working: 0, server_time: new Date().toISOString(), workers: [] },
  })));
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Username or roll number"), { target: { value: "admin" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("heading", { name: "Isolates" })).toBeTruthy();
  expect(location.pathname).toBe("/admin/isolates");
  fireEvent(window, new Event("cjudge-session-expired"));
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
  expect(location.pathname).toBe("/admin/isolates");
});

test.each([
  ['student', '/admin/students', '/labs'], ['admin', '/labs/lab/tasks/revision', '/admin/labs'],
])('signed-in %s cannot open the other role pages', async (role, path, destination) => {
  history.replaceState(null, '', path);
  const account = { id: 'account', role, name: 'Ada', roll_number: null, csrf_token: 'csrf' };
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path.endsWith('/auth/session') ? account : [] }));
  vi.stubGlobal('fetch', fetchMock);
  render(<App />);
  expect(await screen.findByRole('heading', { name: role === 'student' ? 'Assigned labs' : 'Labs' })).toBeTruthy();
  expect(location.pathname).toBe(destination);
  expect(fetchMock.mock.calls.some(([path]) => role === 'student' ? path.includes('/admin/') : path.includes('/labs/lab'))).toBe(false);
});

test('admin stream revocation clears private pages immediately', async () => {
  history.replaceState(null, '', '/admin/isolates');
  let stream!: EventTarget;
  vi.stubGlobal('EventSource', class extends EventTarget { close = vi.fn(); constructor() { super(); stream = this; } });
  const account = { id: 'admin', role: 'admin', name: 'Admin', csrf_token: 'csrf' };
  vi.stubGlobal('fetch', vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, status: 200,
    json: async () => path.endsWith('/auth/session') ? account : { configured: 1, healthy: 0, working: 0, server_time: new Date().toISOString(), workers: [] } })));
  render(<App />);
  expect(await screen.findByRole('heading', { name: 'Isolates' })).toBeTruthy();
  act(() => stream.dispatchEvent(new Event('denied')));
  expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeTruthy();
  expect(screen.queryByRole('heading', { name: 'Isolates' })).toBeNull();
});
