import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Connection, Project, Provider } from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";
import { canContribute, canWriteProjects, isPlanner } from "../lib/permissions";
import { CONNECTOR_FIELDS, buildConnectorConfig } from "../lib/connectorFields";
import { PageHeader } from "../components/PageHeader";

export default function Connectors() {
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  const justConnected = searchParams.get("connected");
  const { data: me } = useCurrentUser();
  const mayManage = canWriteProjects(me?.role); // admin/architect: create + shared-connection OAuth
  const mayPlan = isPlanner(me?.role); // + eng-manager: sync + file import
  const mayConnectSelf = canContribute(me?.role); // any non-viewer: connect their own account
  const [provider, setProvider] = useState<Provider>("jira");
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [advanced, setAdvanced] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ text: string; error: boolean } | null>(null);
  const setField = (key: string, value: string) =>
    setFields((prev) => ({ ...prev, [key]: value }));

  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<Connection[]>("/connectors/connections"),
  });

  // Powers the "canopy project" picker so the operator selects a project by name instead of
  // typing a numeric id into raw JSON.
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<Project[]>("/projects"),
    enabled: mayManage,
  });

  // OAuth flows redirect on success; surface failures (misconfig / policy) instead of failing silently.
  const oauthConnect = useMutation({
    mutationFn: (connectionId: number) =>
      api.get<{ authorize_url: string }>(`/connectors/oauth/${connectionId}/authorize`),
    onSuccess: ({ authorize_url }) => {
      window.location.href = authorize_url;
    },
    onError: (e: Error) => setMsg({ text: `Connect failed: ${e.message}`, error: true }),
  });

  // Per-user SSO: authorize the current user's own account against this integration.
  const connectMe = useMutation({
    mutationFn: (connectionId: number) =>
      api.post<{ authorize_url: string }>(`/connectors/oauth/${connectionId}/connect-me`),
    onSuccess: ({ authorize_url }) => {
      window.location.href = authorize_url;
    },
    onError: (e: Error) => setMsg({ text: `Connect failed: ${e.message}`, error: true }),
  });

  const create = useMutation({
    mutationFn: () =>
      api.post<Connection>("/connectors/connections", {
        provider,
        name,
        token: token || null,
        config: buildConnectorConfig(provider, fields, advanced),
      }),
    onSuccess: () => {
      setName("");
      setToken("");
      setFields({});
      setAdvanced("");
      setShowAdvanced(false);
      setError(null);
      qc.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const sync = useMutation({
    mutationFn: (connectionId: number) =>
      api.post<Record<string, number>>(`/connectors/connections/${connectionId}/sync`),
    onSuccess: (res) =>
      setMsg({
        text: `Synced: ${res.created} created, ${res.updated} updated, ${res.skipped} skipped`,
        error: false,
      }),
    onError: (e: Error) => setMsg({ text: `Sync failed: ${e.message}`, error: true }),
  });

  // File-drop ingest: upload a JSON/CSV export; canopy parses + loads it idempotently.
  const importFile = useMutation({
    mutationFn: ({ connectionId, file }: { connectionId: number; file: File }) => {
      const form = new FormData();
      form.append("file", file);
      return api.upload<{
        created: number;
        updated: number;
        skipped: number;
        parsed: number;
        errors: string[];
      }>(`/connectors/connections/${connectionId}/ingest/file`, form);
    },
    onSuccess: (res) => {
      const errs = res.errors.length ? `, ${res.errors.length} row error(s)` : "";
      setMsg({
        text: `Imported: ${res.created} created, ${res.updated} updated, ${res.skipped} skipped${errs}`,
        error: res.errors.length > 0,
      });
      qc.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (e: Error) => setMsg({ text: `Import failed: ${e.message}`, error: true }),
  });

  return (
    <div className="space-y-6">
      <PageHeader title="Connectors" />

      {justConnected && (
        <div className="rounded border border-canopy-500/30 bg-canopy-50 px-4 py-2 text-sm text-canopy-700">
          Connection #{justConnected} authorized via OAuth.
        </div>
      )}

      <p className="text-sm text-slate-500">
        {mayManage
          ? "Add a connection, then either paste an API token or use Connect to authorize via OAuth."
          : "You can view connections and, where enabled, connect your own account. Managing shared connections requires an architect or admin."}
      </p>

      <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-600">
        These are canopy's <strong>data</strong> integrations — Jira, GitHub, Drive. Connecting{" "}
        <strong>Claude Code itself</strong> (an MCP token + the plugin) lives on{" "}
        <Link to="/agent-setup" className="font-medium text-canopy-700 hover:underline">
          Agent Setup →
        </Link>
      </div>

      {mayManage && (
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
              // New provider → new field set; drop the old typed values so keys don't leak across.
              setProvider(e.target.value as Provider);
              setFields({});
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

        {/* Typed config fields (§lib/connectorFields) — no more hand-written JSON for the common case. */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {CONNECTOR_FIELDS[provider].map((f) => (
            <label key={f.key} className="flex flex-col gap-1 text-xs font-medium text-slate-500">
              {f.label}
              {f.kind === "project" ? (
                <select
                  value={fields[f.key] ?? ""}
                  onChange={(e) => setField(f.key, e.target.value)}
                  className="rounded border border-slate-300 px-3 py-2 text-sm font-normal text-slate-800"
                >
                  <option value="">
                    {projects.isLoading ? "Loading projects…" : "Select a project…"}
                  </option>
                  {(projects.data ?? []).map((p) => (
                    <option key={p.id} value={String(p.id)}>
                      {p.key} — {p.name}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type={f.kind === "email" ? "email" : f.kind === "url" ? "url" : "text"}
                  value={fields[f.key] ?? ""}
                  onChange={(e) => setField(f.key, e.target.value)}
                  placeholder={f.placeholder}
                  className="rounded border border-slate-300 px-3 py-2 text-sm font-normal text-slate-800"
                />
              )}
              {f.help && <span className="font-normal text-slate-400">{f.help}</span>}
            </label>
          ))}
        </div>

        {/* Advanced escape hatch: extra/unknown config keys as raw JSON, merged under the typed fields. */}
        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="text-xs font-medium text-slate-500 hover:text-slate-700"
          >
            {showAdvanced ? "▾" : "▸"} Advanced (extra config as JSON)
          </button>
          {showAdvanced && (
            <textarea
              value={advanced}
              onChange={(e) => setAdvanced(e.target.value)}
              rows={3}
              placeholder='{"board_id": 42}'
              className="mt-2 w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
            />
          )}
        </div>

        {error && <div className="text-sm text-red-600">{error}</div>}
        <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
          Add connection
        </button>
      </form>
      )}

      {msg && (
        <div
          className={`rounded border px-4 py-2 text-sm ${
            msg.error
              ? "border-red-200 bg-red-50 text-red-700"
              : "border-canopy-500/30 bg-canopy-50 text-canopy-700"
          }`}
        >
          {msg.text}
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
              {(c.read_strategy !== "direct" || c.write_strategy !== "direct") && (
                <span
                  className="ml-2 rounded bg-indigo-100 px-2 py-0.5 text-xs text-indigo-700"
                  title={`reads: ${c.read_strategy} · writes: ${c.write_strategy}`}
                >
                  MCP-managed
                </span>
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
              {mayManage && (
                <button
                  onClick={() => oauthConnect.mutate(c.id)}
                  className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
                >
                  {c.authorized ? "Reconnect" : "Connect"}
                </button>
              )}
              {c.allow_user_connect && mayConnectSelf && (
                <button
                  onClick={() => connectMe.mutate(c.id)}
                  className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
                >
                  {c.user_connected ? "Reconnect my account" : "Connect my account"}
                </button>
              )}
              {mayPlan && (
                <button
                  onClick={() => sync.mutate(c.id)}
                  disabled={sync.isPending || c.read_strategy !== "direct"}
                  title={
                    c.read_strategy !== "direct"
                      ? "Reads are managed via MCP/file for this provider — Claude ingests the data."
                      : undefined
                  }
                  className="rounded border border-canopy-500 px-3 py-1 text-xs font-medium text-canopy-700 disabled:opacity-50"
                >
                  Sync now
                </button>
              )}
              {mayPlan && c.provider !== "gdrive" && (
                <label
                  className="cursor-pointer rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
                  title="Import a JSON or CSV export — canopy parses and loads it idempotently."
                >
                  Import file
                  <input
                    type="file"
                    accept=".json,.csv"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) importFile.mutate({ connectionId: c.id, file });
                      e.target.value = "";
                    }}
                  />
                </label>
              )}
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
