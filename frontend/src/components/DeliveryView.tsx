import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { DeliveryMetrics } from "../api/types";

const WEEKS_OPTIONS = [4, 8, 12, 26];

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`text-xl font-bold tabular-nums ${tone ?? ""}`}>{value}</div>
      {hint && <div className="text-xs text-slate-400">{hint}</div>}
    </div>
  );
}

/** DORA + flow delivery metrics for a project or initiative. Team-level by design — there is
 *  deliberately no per-engineer breakdown (a Goodhart trap). */
export default function DeliveryView({
  scope,
  id,
}: {
  scope: "project" | "initiative";
  id: number;
}) {
  const [weeks, setWeeks] = useState(12);
  const q = useQuery({
    queryKey: ["delivery", scope, id, weeks],
    queryFn: () => api.get<DeliveryMetrics>(`/${scope}s/${id}/delivery?weeks=${weeks}`),
  });

  if (q.isLoading) return <p className="text-sm text-slate-500">Loading delivery metrics…</p>;
  if (!q.data) return <p className="text-sm text-slate-500">No metrics.</p>;
  const { dora, flow } = q.data;
  const fmt = (n: number | null, suffix = "") => (n === null ? "—" : `${n}${suffix}`);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">
          Delivery metrics
          <span className="ml-2 text-xs font-normal text-slate-400">
            DORA + flow · team-level, never per-engineer
          </span>
        </h2>
        <label className="flex items-center gap-1 text-xs text-slate-500">
          window
          <select
            value={weeks}
            onChange={(e) => setWeeks(Number(e.target.value))}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          >
            {WEEKS_OPTIONS.map((w) => (
              <option key={w} value={w}>
                {w} wk
              </option>
            ))}
          </select>
        </label>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-700">DORA</h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat
            label="Deploy freq"
            value={fmt(dora.deploy_frequency_per_week, "/wk")}
            hint={`${dora.deploys} in ${dora.window_weeks} wk`}
          />
          <Stat
            label="Change-fail rate"
            value={dora.change_fail_rate === null ? "—" : `${Math.round(dora.change_fail_rate * 100)}%`}
            hint={`${dora.failures} incident(s)`}
            tone={
              dora.change_fail_rate !== null && dora.change_fail_rate > 0.15 ? "text-amber-700" : ""
            }
          />
          <Stat
            label="Recovery time"
            value={fmt(dora.mean_recovery_hours, "h")}
            hint={`${dora.recovered_incidents} recovered (mean)`}
          />
          <Stat label="Failures" value={String(dora.failures)} hint="incidents opened" />
        </div>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-700">Flow</h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat
            label="Throughput"
            value={fmt(flow.throughput_per_week, "/wk")}
            hint={`${flow.completed_items} completed`}
          />
          <Stat
            label="Cycle time"
            value={fmt(flow.cycle_time_median_days, "d")}
            hint={`P85 ${fmt(flow.cycle_time_p85_days, "d")}`}
          />
          <Stat label="WIP" value={String(flow.wip)} hint="not-done items" />
          <Stat
            label="Aging WIP"
            value={String(flow.aging_wip)}
            hint="over cycle-time P85"
            tone={flow.aging_wip > 0 ? "text-amber-700" : ""}
          />
        </div>
        {!flow.sufficient && flow.reason && (
          <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            {flow.reason}
          </p>
        )}
      </div>

      {q.data.notes.length > 0 && (
        <ul className="space-y-1 border-t border-slate-100 pt-3 text-xs text-slate-400">
          {q.data.notes.map((n, i) => (
            <li key={i}>· {n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
