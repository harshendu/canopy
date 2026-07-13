import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { DemoStatus } from "../api/types";
import { PageHeader } from "../components/PageHeader";

const COUNT_LABELS: Record<string, string> = {
  users: "Users",
  engineers: "Team members",
  initiatives: "Initiatives",
  projects: "Projects",
  tasks: "Tasks",
  milestones: "Milestones",
  dependencies: "Dependencies",
  allocations: "Allocations",
  decisions: "ADRs",
  components: "Components",
  risks: "Risks (RAID)",
  specs: "Specs",
  outcomes: "Outcomes",
  blockers: "Blockers",
  retrospectives: "Retros",
  draft_plans: "Draft plans",
  connections: "Connections",
  scenarios: "Scenarios",
  activity_events: "Activity events",
  status_history: "Status history",
  documents: "Documents",
};

export default function DemoData() {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["demo-status"],
    queryFn: () => api.get<DemoStatus>("/admin/demo/status"),
  });

  const afterMutate = (data: DemoStatus) => {
    qc.setQueryData(["demo-status"], data);
    qc.invalidateQueries(); // the whole dataset changed — refresh every view
  };

  const reseed = useMutation({
    mutationFn: () => api.post<DemoStatus>("/admin/demo/reseed"),
    onSuccess: afterMutate,
  });
  const clear = useMutation({
    mutationFn: () => api.post<DemoStatus>("/admin/demo/clear"),
    onSuccess: afterMutate,
  });

  const data = status.data;
  const busy = reseed.isPending || clear.isPending;

  if (status.isLoading) {
    return <div className="p-2 text-sm text-slate-400">Loading…</div>;
  }

  if (data && !data.demo_mode) {
    return (
      <div className="space-y-4">
        <PageHeader title="Demo data" />
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          <p className="font-medium">Demo mode is disabled.</p>
          <p className="mt-1">
            Set <code>DEMO_MODE=true</code> in the backend environment (local/dev only) and
            restart to unlock seed &amp; reset controls. Demo mode also serves Jira / GitHub /
            Drive connectors from an offline mock so the whole app works without real credentials.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Demo data"
        subtitle="Load a full, coherent demo dataset — or wipe everything back to empty. Resetting keeps you (and the configured superuser) signed in and recreates all demo users. Connectors are served by an offline mock, so “Sync from Jira” and provider reads work without real credentials."
      />

      <div className="flex flex-wrap gap-3">
        <button
          onClick={() => {
            if (window.confirm("Wipe ALL data and reload the demo dataset from scratch?")) {
              reseed.mutate();
            }
          }}
          disabled={busy}
          className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {reseed.isPending ? "Reseeding…" : "Reset & load demo data"}
        </button>
        <button
          onClick={() => {
            if (window.confirm("Wipe ALL data and leave the instance empty?")) {
              clear.mutate();
            }
          }}
          disabled={busy}
          className="rounded border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
        >
          {clear.isPending ? "Clearing…" : "Clear all data"}
        </button>
        {(reseed.isError || clear.isError) && (
          <span className="self-center text-xs text-red-600">
            {((reseed.error || clear.error) as Error).message}
          </span>
        )}
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          Current contents
        </h2>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {Object.entries(data?.counts ?? {}).map(([key, value]) => (
            <div key={key} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
              <div className="text-lg font-semibold tabular-nums">{value}</div>
              <div className="text-xs text-slate-500">{COUNT_LABELS[key] ?? key}</div>
            </div>
          ))}
        </div>
      </section>

      {data?.accounts && data.accounts.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
            Demo logins
          </h2>
          <p className="text-xs text-slate-500">
            Every account uses the password{" "}
            <code className="rounded bg-slate-100 px-1 py-0.5">{data.password}</code>. Sign in as
            any of them to explore a different role / persona.
          </p>
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-400">
                <tr>
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Email</th>
                  <th className="px-3 py-2">Role</th>
                  <th className="px-3 py-2">Function</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.accounts.map((a) => (
                  <tr key={a.email}>
                    <td className="px-3 py-2 font-medium">{a.full_name}</td>
                    <td className="px-3 py-2 text-slate-500">{a.email}</td>
                    <td className="px-3 py-2">{a.role}</td>
                    <td className="px-3 py-2 text-slate-500">{a.function}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
