import { useState } from "react";
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
              {c.watermark && (
                <span className="ml-2 text-xs text-slate-400">synced ≥ {c.watermark}</span>
              )}
            </span>
            <button
              onClick={() => sync.mutate(c.id)}
              disabled={sync.isPending}
              className="rounded border border-canopy-500 px-3 py-1 text-xs font-medium text-canopy-700 disabled:opacity-50"
            >
              Sync now
            </button>
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
