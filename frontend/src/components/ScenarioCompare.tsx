import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import type { ScenarioApplyResult, ScenarioCompareResponse } from "../api/types";
import { isPlanner } from "../lib/permissions";
import { useCurrentUser } from "../lib/useCurrentUser";
import { deltaTone, formatDayDelta, totalChanges } from "../lib/scenarioDiff";

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-0.5 text-lg font-bold tabular-nums ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

export default function ScenarioCompare({
  scenarioId,
  status,
}: {
  scenarioId: number;
  status: string;
}) {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const mayPlan = isPlanner(me?.role);
  const [applied, setApplied] = useState<ScenarioApplyResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const compare = useQuery({
    queryKey: ["scenario-compare", scenarioId],
    queryFn: () => api.get<ScenarioCompareResponse>(`/scenarios/${scenarioId}/compare`),
  });

  const apply = useMutation({
    mutationFn: (force: boolean) =>
      api.post<ScenarioApplyResult>(`/scenarios/${scenarioId}/apply`, { force }),
    onSuccess: (res) => {
      setApplied(res);
      setError(null);
      qc.invalidateQueries({ queryKey: ["scenario", scenarioId] });
      qc.invalidateQueries({ queryKey: ["scenario-compare", scenarioId] });
    },
    onError: (e) => {
      setError(e instanceof ApiError ? e.message : String(e));
    },
  });

  if (!compare.data) return <p className="text-sm text-slate-500">Comparing to live…</p>;
  const { diff, conflicts } = compare.data;
  const stale = conflicts.length > 0;
  const isApplied = status === "applied" || applied?.status === "applied";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Total changes" value={String(totalChanges(diff))} />
        <Stat
          label="Project end"
          value={formatDayDelta(diff.end_delta_days)}
          tone={deltaTone(diff.end_delta_days)}
        />
        <Stat
          label="Critical path"
          value={formatDayDelta(diff.cp_delta_days)}
          tone={deltaTone(diff.cp_delta_days)}
        />
        <Stat
          label="Scope"
          value={`+${diff.tasks_added} / -${diff.tasks_removed} / ~${diff.tasks_changed}`}
        />
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm text-slate-600 md:grid-cols-4">
        <span>Deps: +{diff.deps_added} / -{diff.deps_removed}</span>
        <span>Milestones: {diff.milestones_changed}</span>
        <span>Allocations: {diff.allocations_changed}</span>
        <span>Availability: {diff.availability_changed}</span>
      </div>

      {diff.per_project.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
              <th className="py-1">Project</th>
              <th className="py-1">Live end</th>
              <th className="py-1">Scenario end</th>
              <th className="py-1">Δ</th>
            </tr>
          </thead>
          <tbody>
            {diff.per_project.map((p) => (
              <tr key={p.project_id} className="border-t border-slate-100">
                <td className="py-1 font-mono text-xs">{p.project_key}</td>
                <td className="py-1">{p.live_end ?? "—"}</td>
                <td className="py-1">{p.scenario_end ?? "—"}</td>
                <td className={`py-1 ${deltaTone(p.end_delta_days)}`}>
                  {formatDayDelta(p.end_delta_days)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {stale && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
          <p className="font-medium">Live data changed since this scenario was captured:</p>
          <ul className="mt-1 list-disc pl-5">
            {conflicts.map((c, i) => (
              <li key={i}>{c.reason}</li>
            ))}
          </ul>
        </div>
      )}

      {error && <p className="text-sm text-red-600">{error}</p>}

      {isApplied ? (
        <p className="rounded-lg border border-canopy-200 bg-canopy-50 p-3 text-sm text-canopy-700">
          Applied to live — {applied?.created ?? 0} created, {applied?.updated ?? 0} updated,{" "}
          {applied?.deleted ?? 0} deleted; replanned{" "}
          {applied?.replanned_projects.length ?? 0} project(s).
        </p>
      ) : (
        mayPlan && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => apply.mutate(false)}
              disabled={apply.isPending}
              className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {apply.isPending ? "Applying…" : "Apply to live"}
            </button>
            {stale && (
              <button
                onClick={() => apply.mutate(true)}
                disabled={apply.isPending}
                className="rounded border border-red-300 px-4 py-2 text-sm font-medium text-red-600 disabled:opacity-50"
              >
                Force apply
              </button>
            )}
          </div>
        )
      )}
    </div>
  );
}
