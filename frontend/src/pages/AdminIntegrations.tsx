import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  IntegrationSetting,
  Provider,
  ReadStrategy,
  WriteStrategy,
} from "../api/types";

const PROVIDER_LABELS: Record<Provider, string> = {
  jira: "Jira",
  github: "GitHub",
  gdrive: "Google Drive",
};

const READ_OPTIONS: { value: ReadStrategy; label: string }[] = [
  { value: "direct", label: "Direct — canopy polls with its own credentials" },
  { value: "mcp", label: "MCP — Claude ingests (poll/webhooks stand down)" },
  { value: "file", label: "File drop — load from uploads / a watched folder" },
];

const WRITE_OPTIONS: { value: WriteStrategy; label: string }[] = [
  { value: "direct", label: "Direct — canopy writes with its own credentials" },
  { value: "mcp", label: "MCP — Claude performs the write (in-app push disabled)" },
  { value: "disabled", label: "Disabled — read-only (no writes)" },
];

export default function AdminIntegrations() {
  const qc = useQueryClient();
  const settings = useQuery({
    queryKey: ["integration-settings"],
    queryFn: () => api.get<IntegrationSetting[]>("/admin/integrations"),
  });

  const update = useMutation({
    mutationFn: (vars: { provider: Provider; body: Partial<IntegrationSetting> }) =>
      api.patch<IntegrationSetting>(`/admin/integrations/${vars.provider}`, vars.body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["integration-settings"] }),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Integrations</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Choose, per provider, how canopy moves data — this governs every role.{" "}
          <strong>Reads:</strong> <code>direct</code> polls with canopy's credentials;{" "}
          <code>mcp</code> stands the poll/webhooks down and waits for Claude to ingest;{" "}
          <code>file</code> loads from an upload or watched folder. <strong>Writes:</strong>{" "}
          <code>direct</code> writes with canopy's credentials; <code>mcp</code> disables the
          in-app push/export (Claude does the write); <code>disabled</code> blocks writes. Choosing{" "}
          <code>mcp</code>/<code>disabled</code> writes will disable push-to-Jira and
          export-to-Drive for users. <strong>Per-user SSO</strong> lets each contributor connect
          their own account so canopy acts as them. Defaults are direct/direct, SSO off.
        </p>
      </div>

      <div className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {(settings.data ?? []).map((s) => (
          <div key={s.provider} className="flex flex-wrap items-center gap-4 px-4 py-4">
            <span className="w-32 shrink-0 font-medium">{PROVIDER_LABELS[s.provider]}</span>
            <label className="flex items-center gap-2 text-sm text-slate-600">
              <span className="text-xs uppercase text-slate-400">Reads</span>
              <select
                value={s.read_strategy}
                onChange={(e) =>
                  update.mutate({
                    provider: s.provider,
                    body: { read_strategy: e.target.value as ReadStrategy },
                  })
                }
                className="rounded border border-slate-300 px-2 py-1.5 text-sm"
              >
                {READ_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-600">
              <span className="text-xs uppercase text-slate-400">Writes</span>
              <select
                value={s.write_strategy}
                onChange={(e) =>
                  update.mutate({
                    provider: s.provider,
                    body: { write_strategy: e.target.value as WriteStrategy },
                  })
                }
                className="rounded border border-slate-300 px-2 py-1.5 text-sm"
              >
                {WRITE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={s.allow_user_connect}
                onChange={(e) =>
                  update.mutate({
                    provider: s.provider,
                    body: { allow_user_connect: e.target.checked },
                  })
                }
                className="rounded border-slate-300"
              />
              <span className="text-xs uppercase text-slate-400">Per-user SSO</span>
            </label>
          </div>
        ))}
        {settings.data?.length === 0 && (
          <div className="px-4 py-6 text-center text-sm text-slate-400">No providers.</div>
        )}
      </div>

      {update.isError && (
        <p className="text-xs text-red-600">{(update.error as Error).message}</p>
      )}
    </div>
  );
}
