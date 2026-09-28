import { useEffect, useState } from "react";

export default function App() {
  const [status, setStatus] = useState("Checking service…");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/ready", { signal: controller.signal })
      .then((response) => setStatus(response.ok ? "Service ready" : "Service unavailable"))
      .catch(() => { if (!controller.signal.aborted) setStatus("Service unavailable"); });
    return () => controller.abort();
  }, []);

  return <div className="min-h-screen bg-slate-100 text-slate-900">
    <header className="border-b border-slate-300 bg-white px-6 py-3 font-semibold">cJudge</header>
    <main className="mx-auto max-w-5xl p-6">
      <h1 className="text-xl font-semibold">Programming Fundamentals Lab Judge</h1>
      <p role="status" className="mt-4 rounded border border-slate-300 bg-white p-4">{status}</p>
    </main>
  </div>;
}
