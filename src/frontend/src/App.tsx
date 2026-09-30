import { useEffect, useState, type FormEvent } from "react";
import { createBrowserRouter, RouterProvider, Routes, Route, Navigate, NavLink, useLocation, useNavigate } from "react-router";
import { api } from "./api";
import Accounts from "./Accounts";
import TaskLibrary from "./TaskLibrary";
import { StudentLabs } from "./StudentLabs";
import { AdminLabs } from "./AdminLabs";
import Isolates from "./Isolates";
import { NotFound } from "./navigation";

type Session = { id: string; role: "admin" | "student"; roll_number: string | null; name: string; csrf_token: string };

function Screen() {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true), [signingIn, setSigningIn] = useState(false);
  const [identifier, setIdentifier] = useState(""), [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const location = useLocation(), navigate = useNavigate();
  useEffect(() => {
    const controller = new AbortController();
    api<Session>("/auth/session", { signal: controller.signal }).then(setSession).catch(() => {})
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    const expired = () => { setSession(null); setError("Login expired. Sign in again."); };
    window.addEventListener("cjudge-session-expired", expired);
    return () => { controller.abort(); window.removeEventListener("cjudge-session-expired", expired); };
  }, []);
  async function login(event: FormEvent) {
    event.preventDefault(); if (signingIn) return;
    setSigningIn(true); setError("");
    const username = identifier.trim(), role = username.toLowerCase() === "admin" ? "admin" : "student";
    try {
      const account = await api<Session>(`/auth/${role}/login`, { method: "POST", body: JSON.stringify({ identifier: username, password }) });
      setPassword(""); setIdentifier(""); setSession(account);
      const prefix = account.role === "admin" ? "/admin/" : "/labs";
      if (!location.pathname.startsWith(prefix)) navigate(account.role === "admin" ? "/admin/labs" : "/labs", { replace: true });
    } catch (e) { setError((e as Error).message); }
    finally { setSigningIn(false); }
  }
  async function logout() {
    if (!session) return;
    try { await api("/auth/logout", { method: "POST" }, session.csrf_token); setSession(null); setError(""); navigate("/login", { replace: true }); }
    catch (e) { setError((e as Error).message); }
  }
  const home = session?.role === "admin" ? "/admin/labs" : "/labs";
  const wrongRole = session && (session.role === "student" ? location.pathname.startsWith("/admin/") : location.pathname === "/labs" || location.pathname.startsWith("/labs/"));
  return <div className="min-h-screen bg-slate-100 text-slate-900">
    <header className="no-print flex flex-wrap items-center justify-between gap-3 border-b border-slate-300 bg-white px-6 py-3">
      <strong>cJudge</strong>{session && <div className="flex items-center gap-3"><span>{session.name}{session.roll_number && ` · Roll number: ${session.roll_number}`}</span>
        <button onClick={logout}>Log out</button></div>}
    </header>
    <main className="mx-auto max-w-6xl p-6">
      {loading ? <p role="status">Loading…</p> : !session ? <section className="mx-auto max-w-sm rounded border bg-white p-6">
        <h1 className="text-xl font-semibold">Sign in</h1><form className="mt-4 grid gap-3" onSubmit={login}>
          <label>Username or roll number<input className="mt-1 w-full" required autoComplete="username" value={identifier} onChange={(e) => setIdentifier(e.target.value)} /></label>
          <label>Password<input className="mt-1 w-full" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
          <button disabled={signingIn}>{signingIn ? "Signing in…" : "Sign in"}</button>
        </form></section> : <div key={session.id}>
        <nav aria-label={session.role === "admin" ? "Admin navigation" : "Student navigation"} className="no-print mb-4 flex flex-wrap gap-2">
          {session.role === "admin" ? <>{[["labs", "Labs"], ["students", "Students"], ["tasks", "Task Library"], ["isolates", "Isolates"]].map(([path, title]) =>
            <NavLink key={path} className="nav-link" to={`/admin/${path}`}>{title}</NavLink>)}</> : <NavLink className="nav-link" to="/labs">Labs</NavLink>}
        </nav>
        {wrongRole ? <Navigate to={home} replace /> : <Routes>
          <Route path="/" element={<Navigate to={home} replace />} />
          <Route path="/login" element={<Navigate to={home} replace />} />
          <Route path="/admin/students" element={<Accounts csrf={session.csrf_token} />} />
          <Route path="/admin/tasks/*" element={<TaskLibrary csrf={session.csrf_token} />} />
          <Route path="/admin/labs/*" element={<AdminLabs csrf={session.csrf_token} />} />
          <Route path="/admin/isolates" element={<Isolates />} />
          <Route path="/labs/*" element={<StudentLabs csrf={session.csrf_token} />} />
          <Route path="*" element={<NotFound />} />
        </Routes>}
      </div>}
      {error && <p role="alert" className="mt-4 notice notice-danger">{error}</p>}
    </main>
  </div>;
}

export default function App() {
  const [router] = useState(() => createBrowserRouter([{ path: "*", element: <Screen /> }]));
  return <RouterProvider router={router} />;
}
