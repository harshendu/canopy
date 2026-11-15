import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import { TRACKERS_KEY, getTrackers } from "../api/trackers";
import type { Connection, Project, Provider } from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";
import { canContribute, canWriteProjects, isPlanner } from "../lib/permissions";
import {
  CLAUDE_SYNC_HELP,
  buildConnectorConfig,
  splitMirrorProject,
  connectorFields,
  missingRequired,
  providerOptions,
} from "../lib/connectorFields";
import { trackingFailure, type TrackingFailure } from "../lib/board";
import { providerLabel, trackerInfo, webhookUrl } from "../lib/tracking";
import { invalidateTracking } from "../lib/trackingCache";
import { PageHeader } from "../components/PageHeader";

interface Notice {
  text: string;
  error: boolean;
  link?: { to: string; label: string };
}

export default function Connectors() {
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  const justConnected = searchParams.get("connected");
  const { data: me } = useCurrentUser();
  const mayManage = canWriteProjects(me?.role); // admin/architect: create + shared-connection OAuth
  const mayPlan = isPlanner(me?.role); // + eng-manager: sync + file import
  const mayConnectSelf = canContribute(me?.role); // any non-viewer: connect their own account
  const [providerChoice, setProviderChoice] = useState<Provider | null>(null);
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [advanced, setAdvanced] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [error, setError] = useState<{ message: string; projectId: number | null } | null>(null);
  const [msg, setMsg] = useState<Notice | null>(null);
  const [rowError, setRowError] = useState<{ id: number; failure: TrackingFailure } | null>(null);
  const setField = (key: string, value: string) =>
    setFields((prev) => ({ ...prev, [key]: value }));

  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<Connection[]>("/connectors/connections"),
  });
  // The work trackers this instance knows: the provider picker and each tracker's form.
  const catalog = useQuery({ queryKey: TRACKERS_KEY, queryFn: getTrackers, staleTime: 5 * 60 * 1000 });

  // Powers the "canopy project" picker so the operator selects a project by name instead of
  // typing a numeric id into raw JSON.
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<Project[]>("/projects"),
    enabled: mayManage,
  });
  const projectsById = new Map((projects.data ?? []).map((p) => [p.id, p] as const));

  const options = providerOptions(catalog.data, { admin: me?.role === "admin" });
  const provider =
    providerChoice && options.some((o) => o.value === providerChoice) ? providerChoice : options[0].value;
  const tracker = trackerInfo(catalog.data, provider);
  const isTracker = tracker !== null || (provider === "jira" && !catalog.data);
  const mirrorId = isTracker && (fields.project_id ?? "").trim() !== "" ? Number(fields.project_id) : null;
  const formFields = connectorFields(provider, tracker, { mirroring: mirrorId !== null });
  const trackerLabels = catalog.data
    ? catalog.data.trackers.filter((t) => t.enabled).map((t) => t.label)
    : ["Jira"];

  // OAuth flows redirect on success; surface failures (misconfig / policy) instead of failing silently.
  const oauthConnect = useMutation({
    mutationFn: (connectionId: number) =>
      api.get<{ authorize_url: string }>(`/connectors/oauth/${connectionId}/authorize`),
    onSuccess: ({ authorize_url }) => {
      window.location.href = authorize_url;
    },
    onError: (e: Error) => setMsg({ text: `Connect failed: ${trackingFailure(e).message}`, error: true }),
  });

  // Per-user SSO: authorize the current user's own account against this integration.
  const connectMe = useMutation({
    mutationFn: (connectionId: number) =>
      api.post<{ authorize_url: string }>(`/connectors/oauth/${connectionId}/connect-me`),
    onSuccess: ({ authorize_url }) => {
      window.location.href = authorize_url;
    },
    onError: (e: Error) => setMsg({ text: `Connect failed: ${trackingFailure(e).message}`, error: true }),
  });

  // A tracker connection created with a canopy project binds that project (mirrored, its
  // existing work kept separate) — or 409s `project_already_bound` when it is mirrored already.
  const create = useMutation({
    mutationFn: (vars: { config: Record<string, unknown>; mirrorId: number | null }) =>
      api.post<Connection>("/connectors/connections", {
        provider,
        name,
        token: token || null,
        config: vars.config,
        project_id: vars.mirrorId,
      }),
    onSuccess: (conn, { mirrorId: bound }) => {
      setName("");
      setToken("");
      setFields({});
      setAdvanced("");
      setShowAdvanced(false);
      setError(null);
      void qc.invalidateQueries({ queryKey: ["connections"] });
      if (bound !== null) {
        void invalidateTracking(qc, bound);
        setMsg({
          text: `Added “${conn.name}” — ${projectsById.get(bound)?.key ?? "the project"} now mirrors from ${providerLabel(conn.provider, catalog.data)}.`,
          error: false,
          link: { to: `/projects/${bound}?tab=tracking`, label: "Open its Tracking tab" },
        });
      } else {
        setMsg({ text: `Added “${conn.name}”.`, error: false });
      }
    },
    onError: (e: Error, { mirrorId: bound }) =>
      setError({ message: trackingFailure(e).message, projectId: bound }),
  });

  const submit = () => {
    const missing = missingRequired(formFields, fields);
    if (missing.length > 0) {
      setError({ message: `Fill in ${missing.join(", ")}.`, projectId: null });
      return;
    }
    let config: Record<string, unknown>;
    try {
      config = buildConnectorConfig(formFields, fields, advanced);
    } catch (e) {
      setError({ message: e instanceof Error ? e.message : String(e), projectId: null });
      return;
    }
    setError(null);
    const body = splitMirrorProject(config, isTracker);
    create.mutate({ config: body.config, mirrorId: body.projectId });
  };

  const sync = useMutation({
    mutationFn: (connectionId: number) =>
      api.post<Record<string, number>>(`/connectors/connections/${connectionId}/sync`),
    onSuccess: (res) =>
      setMsg({
        text: `Synced: ${res.created} created, ${res.updated} updated, ${res.skipped} skipped`,
        error: false,
      }),
    onError: (e: Error) => setMsg({ text: `Sync failed: ${trackingFailure(e).message}`, error: true }),
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
      void qc.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (e: Error) => setMsg({ text: `Import failed: ${trackingFailure(e).message}`, error: true }),
  });

  // A connection that still feeds a project is refused (409 connection_in_use); one whose
  // history other records name is deactivated rather than deleted.
  const remove = useMutation({
    mutationFn: (c: Connection) => api.del(`/connectors/connections/${c.id}`),
    onSuccess: async (_res, c) => {
      setRowError(null);
      await qc.invalidateQueries({ queryKey: ["connections"] });
      const still = qc.getQueryData<Connection[]>(["connections"])?.some((x) => x.id === c.id);
      setMsg({
        text: still
          ? `“${c.name}” is deactivated: it no longer syncs, and what it synced keeps its history.`
          : `“${c.name}” is deleted.`,
        error: false,
      });
    },
    onError: (e: Error, c) => setRowError({ id: c.id, failure: trackingFailure(e) }),
  });

  const confirmRemove = (c: Connection) => {
    const message = [
      `Remove the connection “${c.name}”?`,
      "",
      "One that synced data is deactivated (kept for that history) rather than deleted; one that still feeds a project can't be removed until the project switches its tracking.",
    ].join("\n");
    if (window.confirm(message)) {
      setRowError(null);
      remove.mutate(c);
    }
  };

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
        These are canopy's <strong>data</strong> integrations —{" "}
        {trackerLabels.length > 0 ? `work trackers (${trackerLabels.join(", ")}), ` : ""}GitHub, Drive.
        Connecting <strong>Claude Code itself</strong> (an MCP token + the plugin) lives on{" "}
        <Link to="/agent-setup" className="font-medium text-canopy-700 hover:underline">
          Agent Setup →
        </Link>
      </div>

      {mayManage && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (name) submit();
          }}
          className="space-y-3 rounded-lg border border-slate-200 bg-white p-4"
        >
          <div className="flex gap-2">
            <select
              value={provider}
              aria-label="Provider"
              onChange={(e) => {
                // New provider → new field set; drop the old typed values so keys don't leak across.
                setProviderChoice(e.target.value);
                setFields({});
                setError(null);
              }}
              className="rounded border border-slate-300 px-3 py-2 text-sm"
            >
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
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
            placeholder={
              provider === "claude"
                ? "Compliance API key (stored encrypted)"
                : "API token / access token (stored encrypted)"
            }
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          {provider === "claude" && <p className="text-xs text-slate-500">{CLAUDE_SYNC_HELP}</p>}

          {/* Typed config fields (§lib/connectorFields) — Jira/GitHub/Drive by hand, every other
              tracker from its catalog schema; no hand-written JSON for the common case. */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {formFields.map((f) =>
              f.kind === "boolean" ? (
                <label key={f.key} className="flex items-center gap-2 self-end py-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={fields[f.key] === "true"}
                    onChange={(e) => setField(f.key, e.target.checked ? "true" : "")}
                  />
                  {f.label}
                </label>
              ) : (
                <label key={f.key} className="flex flex-col gap-1 text-xs font-medium text-slate-500">
                  <span>
                    {f.label}
                    {f.required && <span className="text-red-700"> (required)</span>}
                  </span>
                  {f.kind === "project" ? (
                    <select
                      value={fields[f.key] ?? ""}
                      onChange={(e) => setField(f.key, e.target.value)}
                      className="rounded border border-slate-300 px-3 py-2 text-sm font-normal text-slate-800"
                    >
                      <option value="">
                        {projects.isLoading
                          ? "Loading projects…"
                          : isTracker
                            ? "No project — bind one later"
                            : "Select a project…"}
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
                      inputMode={f.kind === "integer" ? "numeric" : f.kind === "number" ? "decimal" : undefined}
                      value={fields[f.key] ?? ""}
                      onChange={(e) => setField(f.key, e.target.value)}
                      placeholder={f.placeholder}
                      required={f.required}
                      className="rounded border border-slate-300 px-3 py-2 text-sm font-normal text-slate-800"
                    />
                  )}
                  {f.help && <span className="font-normal text-slate-400">{f.help}</span>}
                </label>
              ),
            )}
          </div>

          {/* Advanced escape hatch: extra/unknown config keys as raw JSON, merged under the typed fields. */}
          <div>
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              aria-expanded={showAdvanced}
              className="text-xs font-medium text-slate-500 hover:text-slate-700"
            >
              {showAdvanced ? "▾" : "▸"} Advanced (extra config as JSON)
            </button>
            {showAdvanced && (
              <textarea
                value={advanced}
                onChange={(e) => setAdvanced(e.target.value)}
                aria-label="Advanced config (JSON)"
                rows={3}
                placeholder='{"board_id": 42}'
                className="mt-2 w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
              />
            )}
          </div>

          {error && (
            <div role="alert" className="text-sm text-red-700">
              {error.message}
              {error.projectId !== null && (
                <>
                  {" "}
                  <Link
                    to={`/projects/${error.projectId}?tab=tracking`}
                    className="font-medium text-canopy-700 hover:underline"
                  >
                    Open its Tracking tab
                  </Link>
                </>
              )}
            </div>
          )}
          <button
            disabled={create.isPending}
            className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {create.isPending ? "Adding…" : "Add connection"}
          </button>
        </form>
      )}

      {msg && (
        <div
          role={msg.error ? "alert" : "status"}
          className={`rounded border px-4 py-2 text-sm ${
            msg.error
              ? "border-red-200 bg-red-50 text-red-700"
              : "border-canopy-500/30 bg-canopy-50 text-canopy-700"
          }`}
        >
          {msg.text}
          {msg.link && (
            <>
              {" "}
              <Link to={msg.link.to} className="font-medium underline">
                {msg.link.label}
              </Link>
            </>
          )}
        </div>
      )}

      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {(connections.data ?? []).map((c) => {
          const info = trackerInfo(catalog.data, c.provider);
          const label = providerLabel(c.provider, catalog.data);
          const readsDirectly = c.read_strategy === "direct" && (info ? info.capabilities.direct_read : true);
          const syncReason =
            c.read_strategy !== "direct"
              ? "Reads are managed via MCP/file for this provider — Claude ingests the data."
              : info && !info.capabilities.direct_read
                ? `canopy doesn't read ${label} directly — its items arrive by MCP, webhook or file ingest.`
                : undefined;
          return (
            <li key={c.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                    {label}
                  </span>{" "}
                  <span className="font-medium">{c.name}</span>
                  {!c.active ? (
                    <span
                      className="ml-2 rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500"
                      title="It no longer syncs; what it synced keeps its history."
                    >
                      deactivated
                    </span>
                  ) : c.authorized ? (
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
                  {c.allow_user_connect && c.active && (
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
                {c.active && (
                  <span className="flex flex-wrap gap-2">
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
                        disabled={sync.isPending || !readsDirectly}
                        title={syncReason}
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
                    {mayManage && (
                      <button
                        onClick={() => confirmRemove(c)}
                        disabled={remove.isPending}
                        className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:border-red-300 hover:bg-red-50 hover:text-red-700 disabled:opacity-50"
                      >
                        Remove
                      </button>
                    )}
                  </span>
                )}
              </div>
              {mayManage && c.active && info?.capabilities.webhooks && info.webhook_path && (
                <p className="mt-1.5 text-xs text-slate-500">
                  Webhook:{" "}
                  <code className="select-all rounded bg-slate-100 px-1 py-0.5 text-slate-700">
                    {webhookUrl(window.location.origin, info.webhook_path)}
                  </code>
                  {info.webhook_secret_setting && (
                    <>
                      {" "}
                      · signed with the secret in{" "}
                      <code className="rounded bg-slate-100 px-1 py-0.5 text-slate-700">
                        {info.webhook_secret_setting}
                      </code>{" "}
                      (unset = deliveries are refused)
                    </>
                  )}
                </p>
              )}
              {rowError?.id === c.id && (
                <div role="alert" className="mt-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {rowError.failure.message}
                  {rowError.failure.projectIds.length > 0 && (
                    <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                      {rowError.failure.projectIds.map((pid) => {
                        const p = projectsById.get(pid);
                        return (
                          <li key={pid}>
                            <Link to={`/projects/${pid}?tab=tracking`} className="font-medium underline">
                              {p ? `${p.key} — Tracking` : `Project #${pid} — Tracking`}
                            </Link>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              )}
            </li>
          );
        })}
        {connections.data?.length === 0 && (
          <li className="px-4 py-6 text-center text-sm text-slate-400">
            No connections yet.
          </li>
        )}
      </ul>
    </div>
  );
}
