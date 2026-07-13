import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { FeatureGate } from "../api/types";
import { PageHeader } from "../components/PageHeader";

/** One on/off switch. Grey = forced off by the disabled group (own toggle preserved). */
function Toggle({
  on,
  dimmed,
  onChange,
  label,
}: {
  on: boolean;
  dimmed: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
        on ? "bg-canopy-500" : "bg-slate-300"
      } ${dimmed ? "opacity-50" : ""}`}
    >
      <span
        className="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform"
        style={{ transform: on ? "translateX(16px)" : "translateX(0)" }}
      />
    </button>
  );
}

export default function AdminFeatures() {
  const qc = useQueryClient();
  const gates = useQuery({
    queryKey: ["admin-features"],
    queryFn: () => api.get<FeatureGate[]>("/admin/features"),
  });

  const toggle = useMutation({
    mutationFn: (vars: { key: string; enabled: boolean }) =>
      api.patch<FeatureGate[]>(`/admin/features/${vars.key}`, { enabled: vars.enabled }),
    onSuccess: (fresh) => {
      qc.setQueryData(["admin-features"], fresh);
      void qc.invalidateQueries({ queryKey: ["features"] });
    },
  });

  const rows = gates.data ?? [];
  const groups = rows.filter((g) => g.group === null);
  const childrenOf = (key: string) => rows.filter((g) => g.group === key);

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader
        title="Features"
        subtitle="Turn whole surfaces (a group) or single features on and off. Changes apply immediately for everyone — gated pages, tabs, and API endpoints disappear/return without a restart. Core flows (projects, tasks, Gantt scheduling, team, sign-in) are always on."
      />

      {gates.isError && (
        <p className="text-sm text-red-600">{(gates.error as Error).message}</p>
      )}

      {groups.map((group) => {
        const children = childrenOf(group.key);
        return (
          <section
            key={group.key}
            className="rounded-lg border border-slate-200 bg-white"
          >
            <header className="flex items-start gap-3 border-b border-slate-100 px-4 py-3">
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-semibold text-slate-800">{group.label}</h2>
                <p className="mt-0.5 text-xs text-slate-500">{group.description}</p>
              </div>
              <Toggle
                on={group.enabled}
                dimmed={false}
                label={`Toggle ${group.label}`}
                onChange={(enabled) => toggle.mutate({ key: group.key, enabled })}
              />
            </header>
            {children.length > 0 && (
              <ul className="divide-y divide-slate-100">
                {children.map((child) => (
                  <li key={child.key} className="flex items-start gap-3 px-4 py-2.5 pl-8">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-slate-700">{child.label}</span>
                        {child.enabled && !child.effective && (
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
                            off via group
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 text-xs text-slate-400">{child.description}</p>
                    </div>
                    <Toggle
                      on={child.enabled}
                      dimmed={!group.enabled}
                      label={`Toggle ${child.label}`}
                      onChange={(enabled) => toggle.mutate({ key: child.key, enabled })}
                    />
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}

      {toggle.isError && (
        <p className="text-sm text-red-600">{(toggle.error as Error).message}</p>
      )}
    </div>
  );
}
