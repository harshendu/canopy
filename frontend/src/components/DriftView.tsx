import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Component, DriftEvent, DriftResponse } from "../api/types";
import { riskTone } from "../lib/risk";
import { driftKindLabel, RECONCILE_ACTIONS } from "../lib/drift";
import { useCurrentUser } from "../lib/useCurrentUser";
import { canWriteProjects } from "../lib/permissions";

const STATUS_BADGE: Record<string, string> = {
  open: "bg-amber-100 text-amber-700",
  accepted: "bg-emerald-100 text-emerald-700",
  rejected: "bg-red-100 text-red-700",
  false_positive: "bg-slate-200 text-slate-500",
};

export default function DriftView({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const mayReconcile = canWriteProjects(me?.role);

  const drift = useQuery({
    queryKey: ["drift", projectId],
    queryFn: () => api.get<DriftResponse>(`/projects/${projectId}/drift`),
  });
  const components = useQuery({
    queryKey: ["components", projectId],
    queryFn: () => api.get<Component[]>(`/architecture/components?project_id=${projectId}`),
  });

  const reconcile = useMutation({
    mutationFn: (vars: { id: number; action: string }) =>
      api.post(`/projects/${projectId}/drift/${vars.id}/reconcile`, { action: vars.action }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["drift", projectId] });
      qc.invalidateQueries({ queryKey: ["adrs", projectId] });
      qc.invalidateQueries({ queryKey: ["tasks", projectId] });
    },
  });

  if (!drift.data) {
    return <p className="text-sm text-slate-500">Loading drift…</p>;
  }
  const data = drift.data;
  const tone = riskTone(data.level);
  const componentName = (id: number) =>
    (components.data ?? []).find((c) => c.id === id)?.name ?? `#${id}`;
  const open = data.events.filter((e) => e.status === "open");
  const triaged = data.events.filter((e) => e.status !== "open");

  const renderEvent = (e: DriftEvent) => (
    <li key={e.id} className="rounded-lg border border-slate-200 p-3 text-sm">
      <div className="flex items-center gap-2">
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
          {driftKindLabel(e.kind)}
        </span>
        <span className={`rounded px-1.5 py-0.5 text-xs ${STATUS_BADGE[e.status] ?? ""}`}>
          {e.status.replace("_", " ")}
        </span>
      </div>
      <div className="mt-1">{e.summary}</div>
      {e.detail && <div className="mt-0.5 text-xs text-slate-400">{e.detail}</div>}
      <div className="mt-1 flex flex-wrap gap-1">
        {e.affected_component_ids.map((cid) => (
          <span key={cid} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            {componentName(cid)}
          </span>
        ))}
        {e.suspected_cause && (
          <span className="text-xs text-slate-400">cause: {e.suspected_cause}</span>
        )}
      </div>
      {mayReconcile && e.status === "open" && (
        <div className="mt-2 flex flex-wrap gap-2">
          {RECONCILE_ACTIONS.map((a) => (
            <button
              key={a.action}
              title={a.hint}
              onClick={() => reconcile.mutate({ id: e.id, action: a.action })}
              disabled={reconcile.isPending}
              className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:border-canopy-500 disabled:opacity-50"
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
    </li>
  );

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-4 rounded-lg border border-slate-200 bg-white p-4">
        <div className="text-4xl font-bold tabular-nums">{data.score}</div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="font-semibold">Drift score</span>
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${tone.badge}`}>
              {tone.label}
            </span>
            {data.scan_due && (
              <span
                className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700"
                title="Code bindings exist but the drift scan is missing or stale — run the Drift Sentinel."
              >
                scan due
              </span>
            )}
            <span className="text-xs text-slate-400">
              {data.last_scanned_at
                ? `last scanned ${new Date(data.last_scanned_at).toLocaleDateString()}`
                : "never scanned"}
            </span>
          </div>
          <div className="mt-1 h-2 w-full overflow-hidden rounded bg-slate-100">
            <div className={`h-full ${tone.bar}`} style={{ width: `${data.score}%` }} />
          </div>
          <p className="mt-1 text-xs text-slate-400">
            How far the code has drifted from the declared architecture. Findings are produced by
            the <span className="font-medium">Drift Sentinel</span> (the Claude plugin reads code
            and reports declared-vs-actual dependencies, unimplemented decisions, and implicit
            decisions); triage them below.
          </p>
        </div>
      </div>

      <div>
        <h2 className="mb-2 font-semibold">
          Drift queue{" "}
          <span className="text-xs font-normal text-slate-400">{open.length} open</span>
        </h2>
        {open.length === 0 ? (
          <p className="text-sm text-slate-400">
            No open drift. Configure component <span className="font-medium">code bindings</span>{" "}
            on the Architecture tab, then run the Drift Sentinel to populate this queue.
          </p>
        ) : (
          <ul className="space-y-2">{open.map(renderEvent)}</ul>
        )}
      </div>

      {triaged.length > 0 && (
        <div>
          <h2 className="mb-2 font-semibold text-slate-500">Triaged</h2>
          <ul className="space-y-2 opacity-75">{triaged.map(renderEvent)}</ul>
        </div>
      )}
    </div>
  );
}
