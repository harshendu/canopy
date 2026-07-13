import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { DemoPublic } from "../api/types";
import { useAuth } from "../lib/auth";

export default function Login() {
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  // Empty by default — the demo-accounts panel below offers click-to-fill in demo mode.
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const demo = useQuery({
    queryKey: ["demo-public"],
    queryFn: () => api.get<DemoPublic>("/admin/demo/public"),
    staleTime: 5 * 60 * 1000,
  });

  if (isAuthenticated) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate("/");
    } catch {
      setError("Invalid email or password");
    } finally {
      setBusy(false);
    }
  }

  const demoInfo = demo.data;

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="w-80 space-y-4">
        <form
          onSubmit={onSubmit}
          className="space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
        >
          <h1 className="text-xl font-bold text-canopy-700">canopy</h1>
          <p className="text-sm text-slate-500">Architecture &amp; delivery cockpit</p>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="email"
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="password"
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          {error && <div className="text-sm text-red-600">{error}</div>}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded bg-canopy-500 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        {demoInfo?.demo_mode && demoInfo.accounts.length > 0 && (
          <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm">
            <p className="font-medium text-slate-700">Demo accounts</p>
            <p className="mt-0.5 text-xs text-slate-500">
              Click to fill, then sign in. Shared password:{" "}
              <code className="rounded bg-slate-100 px-1">{demoInfo.password}</code>
            </p>
            <ul className="mt-2 max-h-56 space-y-1 overflow-auto">
              {demoInfo.accounts.map((a) => (
                <li key={a.email}>
                  <button
                    type="button"
                    onClick={() => {
                      setEmail(a.email);
                      setPassword(demoInfo.password ?? "");
                    }}
                    className="flex w-full items-center justify-between rounded px-2 py-1 text-left hover:bg-slate-100"
                  >
                    <span className="truncate">{a.full_name}</span>
                    <span className="ml-2 shrink-0 text-xs text-slate-400">{a.role}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
