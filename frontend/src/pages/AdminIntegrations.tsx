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

// Phase 1 only wires direct reads; mcp/file reads light up in a later phase, so they're shown
// (to signal the roadmap) but not selectable — picking them today would leave canopy with no data.
const READ_OPTIONS: { value: ReadStrategy; label: string; disabled?: boolean }[] = [
  { value: "direct", label: "Direct — canopy's own credentials" },
  { value: "mcp", label: "MCP / Claude (later phase)", disabled: true },
  { value: "file", label: "File drop (later phase)", disabled: true },
];

const WRITE_OPTIONS: { value: WriteStrategy; label: string }[] = [
  { value: "direct", label: "Direct — canopy's own credentials" },
  { value: "mcp", label: "MCP / Claude" },
  { value: "disabled", label: "Disabled — read-only" },
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
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Choose, per provider, how canopy reads and writes. <strong>Reads</strong> use canopy's
          own credentials when available; <strong>writes</strong> can run directly, be routed
          through Claude over MCP, or be disabled. Defaults are direct/direct.
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
                  <option key={o.value} value={o.value} disabled={o.disabled}>
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
