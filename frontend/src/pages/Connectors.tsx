import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Connection, Provider } from "../api/types";

const CONFIG_HINTS: Record<Provider, string> = {
  jira: '{"base_url":"https://you.atlassian.net","email":"you@co.com","project_id":1,"jira_project_key":"PLAT"}',
  github: '{"owner":"acme","repo":"platform"}',
  gdrive: "{}",
};

export default function Connectors() {
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  const justConnected = searchParams.get("connected");
  const [provider, setProvider] = useState<Provider>("jira");
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [config, setConfig] = useState(CONFIG_HINTS.jira);
  const [error, setError] = useState<string | null>(null);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<Connection[]>("/connectors/connections"),
  });

  async function connectOAuth(connectionId: number) {
    const { authorize_url } = await api.get<{ authorize_url: string }>(
      `/connectors/oauth/${connectionId}/authorize`,
    );
    window.location.href = authorize_url;
  }

  // Per-user SSO: authorize the current user's own account against this integration.
  async function connectMe(connectionId: number) {
    const { authorize_url } = await api.post<{ authorize_url: string }>(
      `/connectors/oauth/${connectionId}/connect-me`,
    );
    window.location.href = authorize_url;
  }

  const create = useMutation({
    mutationFn: () => {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(config || "{}");
      } catch {
        throw new Error("Config must be valid JSON");
      }
      return api.post<Connection>("/connectors/connections", {
        provider,
        name,
        token: token || null,
        config: parsed,
      });
    },
    onSuccess: () => {
      setName("");
      setToken("");
      setError(null);
      qc.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const sync = useMutation({
    mutationFn: (connectionId: number) =>
      api.post<Record<string, number>>(`/connectors/connections/${connectionId}/sync`),
    onSuccess: (res) =>
      setSyncMsg(`Synced: ${res.created} created, ${res.updated} updated, ${res.skipped} skipped`),
    onError: (e: Error) => setSyncMsg(`Sync failed: ${e.message}`),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Connectors</h1>

      {justConnected && (
        <div className="rounded border border-canopy-500/30 bg-canopy-50 px-4 py-2 text-sm text-canopy-700">
          Connection #{justConnected} authorized via OAuth.
        </div>
      )}

      <p className="text-sm text-slate-500">
        Add a connection, then either paste an API token above or use{" "}
        <span className="font-medium">Connect</span> to authorize via OAuth.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name) create.mutate();
        }}
        className="space-y-3 rounded-lg border border-slate-200 bg-white p-4"
      >
        <div className="flex gap-2">
          <select
            value={provider}
            onChange={(e) => {
              const p = e.target.value as Provider;
              setProvider(p);
              setConfig(CONFIG_HINTS[p]);
            }}
            className="rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="jira">Jira</option>
            <option value="github">GitHub</option>
            <option value="gdrive">Google Drive</option>
          </select>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Connection name"
            className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        <input
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="API token / access token (stored encrypted)"
          className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <textarea
          value={config}
          onChange={(e) => setConfig(e.target.value)}
          rows={3}
          className="w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
        />
        {error && <div className="text-sm text-red-600">{error}</div>}
        <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
          Add connection
        </button>
      </form>

      {syncMsg && (
        <div className="rounded border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600">
          {syncMsg}
        </div>
      )}

      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {(connections.data ?? []).map((c) => (
          <li key={c.id} className="flex items-center justify-between px-4 py-3">
            <span>
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium uppercase text-slate-500">
                {c.provider}
              </span>{" "}
              <span className="font-medium">{c.name}</span>
              {c.authorized ? (
                <span className="ml-2 rounded bg-green-100 px-2 py-0.5 text-xs text-green-700">
                  authorized
                </span>
              ) : (
                <span className="ml-2 rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
                  not connected
                </span>
              )}
              {c.watermark && (
                <span className="ml-2 text-xs text-slate-400">synced ≥ {c.watermark}</span>
              )}
              {c.allow_user_connect && (
                <span
                  className={`ml-2 rounded px-2 py-0.5 text-xs ${
                    c.user_connected
                      ? "bg-green-100 text-green-700"
                      : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {c.user_connected ? "your account connected" : "per-user SSO available"}
                </span>
              )}
            </span>
            <span className="flex gap-2">
              <button
                onClick={() => connectOAuth(c.id)}
                className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
              >
                {c.authorized ? "Reconnect" : "Connect"}
              </button>
              {c.allow_user_connect && (
                <button
                  onClick={() => connectMe(c.id)}
                  className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
                >
                  {c.user_connected ? "Reconnect my account" : "Connect my account"}
                </button>
              )}
              <button
                onClick={() => sync.mutate(c.id)}
                disabled={sync.isPending}
                className="rounded border border-canopy-500 px-3 py-1 text-xs font-medium text-canopy-700 disabled:opacity-50"
              >
                Sync now
              </button>
            </span>
          </li>
        ))}
        {connections.data?.length === 0 && (
          <li className="px-4 py-6 text-center text-sm text-slate-400">
            No connections yet.
          </li>
        )}
      </ul>
    </div>
  );
}
