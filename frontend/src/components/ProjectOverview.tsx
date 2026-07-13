import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { AlertsResponse, ForecastResponse, ProjectSummary } from "../api/types";
import { riskTone } from "../lib/risk";
import { tabEnabled, type IsFeatureOn, type ProjectTab } from "../lib/projectNav";
import OutcomesPanel from "./OutcomesPanel";
import { QueryError } from "./QueryError";
import { Icon } from "./icons";

/**
 * The project cockpit's at-a-glance entry (the default landing view). It answers "is this project
 * on track, and what needs me?" in one screen by surfacing signals that used to be buried — the
 * `/alerts` exception feed (previously only inside the Risk tab), the computed risk/drift scores and
 * progress from `/projects/{id}/summary` (previously only on the portfolio), and the Monte-Carlo
 * forecast (previously at the bottom of the Gantt) — each drilling through into the workspace that
 * owns it. "Overview first, then details on demand."
 */

/** Which workspace an alert kind drills into. */
const ALERT_TAB: Record<string, ProjectTab> = {
  blocked: "board",
  deadline_miss: "gantt",
  unscheduled: "gantt",
  milestone_overdue: "gantt",
  over_allocation: "capacity",
  risk_overdue: "risk",
};

function alertDot(severity: string): string {
  if (severity === "error") return "bg-red-500";
  if (severity === "warning") return "bg-amber-500";
  return "bg-sky-400";
}

function Tile({
  label,
  value,
  hint,
  tone,
  onOpen,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: string;
  onOpen?: () => void;
}) {
  const body = (
    <>
      <div className="text-xs uppercase tracking-wide opacity-70">{label}</div>
      <div className="mt-1 text-2xl font-bold tabular-nums">{value}</div>
      {hint != null && <div className="mt-0.5 text-xs opacity-80">{hint}</div>}
    </>
  );
  const base = `rounded-lg border p-4 text-left ${tone ?? "border-slate-200 bg-white"}`;
  if (!onOpen) return <div className={base}>{body}</div>;
  return (
    <button
      onClick={onOpen}
      className={`${base} transition hover:border-canopy-500 hover:shadow-sm`}
    >
      {body}
    </button>
  );
}

export default function ProjectOverview({
  projectId,
  mayPlan,
  isOn,
  onOpenTab,
}: {
  projectId: number;
  mayPlan: boolean;
  isOn: IsFeatureOn;
  onOpenTab: (tab: ProjectTab) => void;
}) {
  const id = projectId;
  const forecastOn = isOn("tracking.forecast");
  const alertsOn = isOn("tracking.alerts");
  const riskOn = isOn("governance.risk");
  const driftOn = isOn("architecture.drift");
  const outcomesOn = isOn("portfolio.outcomes");

  const summary = useQuery({
    queryKey: ["project-summary", id],
    queryFn: () => api.get<ProjectSummary>(`/projects/${id}/summary`),
  });
  const forecast = useQuery({
    queryKey: ["forecast", id],
    queryFn: () => api.get<ForecastResponse>(`/projects/${id}/forecast`),
    enabled: forecastOn,
  });
  const alerts = useQuery({
    queryKey: ["alerts", id],
    queryFn: () => api.get<AlertsResponse>(`/projects/${id}/alerts`),
    enabled: alertsOn,
  });

  const s = summary.data;
  const fc = forecast.data;
  const alertList = alerts.data?.alerts ?? [];
  const risk = riskTone(s?.risk_level ?? "");
  const drift = riskTone(s?.drift_level ?? "");
  const drill = (tab: ProjectTab): (() => void) | undefined =>
    tabEnabled(tab, isOn) ? () => onOpenTab(tab) : undefined;

  return (
    <div className="space-y-5">
      {/* "What needs me" — green is silent. */}
      {alertsOn && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="mb-2 flex items-center gap-2">
            <Icon name="alerts" size={16} />
            <h2 className="font-semibold">Needs attention</h2>
            {alertList.length > 0 && (
              <span className="rounded-full bg-amber-500 px-1.5 text-xs font-semibold text-white">
                {alertList.length}
              </span>
            )}
          </div>
          {alerts.isLoading ? (
            <p className="text-sm text-slate-400">Loading alerts…</p>
          ) : alerts.isError ? (
            // Never fall through to "On track" on a fetch failure — that would falsely reassure.
            <QueryError
              error={alerts.error}
              onRetry={() => void alerts.refetch()}
              label="Couldn’t load alerts"
            />
          ) : alertList.length === 0 ? (
            <p className="flex items-center gap-1.5 text-sm text-slate-500">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              On track — no open exceptions.
            </p>
          ) : (
            <ul className="space-y-1">
              {alertList.map((a, i) => {
                const tab = ALERT_TAB[a.kind];
                const onOpen = tab ? drill(tab) : undefined;
                return (
                  <li key={`${a.kind}-${a.entity_id ?? i}`}>
                    <button
                      onClick={onOpen}
                      disabled={!onOpen}
                      className={`flex w-full items-start gap-2 rounded px-2 py-1 text-left text-sm ${
                        onOpen ? "hover:bg-slate-50" : "cursor-default"
                      }`}
                    >
                      <span
                        className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${alertDot(a.severity)}`}
                      />
                      <span className="flex-1 text-slate-700">{a.message}</span>
                      {onOpen && (
                        <Icon name="arrow-right" size={14} />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      {/* Headline numbers — computed the same way as the portfolio, so they match. */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Tile
          label="Progress"
          value={s ? `${s.avg_percent_complete}%` : "—"}
          hint={s ? `${s.completed_tasks}/${s.total_tasks} tasks` : undefined}
          onOpen={drill("board")}
        />
        <Tile
          label="Latest end (CPM)"
          value={s?.project_end ?? "—"}
          hint={s?.target_date ? `target ${s.target_date}` : "no target"}
          onOpen={drill("gantt")}
        />
        {forecastOn && (
          <Tile
            label="Forecast (P85)"
            value={fc?.sufficient ? fc.p85_date ?? "—" : "—"}
            hint={fc?.sufficient ? `P50 ${fc.p50_date}` : "needs throughput history"}
            onOpen={drill("gantt")}
          />
        )}
        {riskOn && (
          <Tile
            label="Risk"
            value={s?.risk_score ?? "—"}
            hint={<span className="capitalize">{s?.risk_level ?? "—"}</span>}
            tone={risk.badge.replace("text-", "border-transparent text-")}
            onOpen={drill("risk")}
          />
        )}
        {driftOn && (
          <Tile
            label="Drift"
            value={s?.drift_score ?? "—"}
            hint={<span className="capitalize">{s?.drift_level ?? "—"}</span>}
            tone={drift.badge.replace("text-", "border-transparent text-")}
            onOpen={drill("drift")}
          />
        )}
        {riskOn && (
          <Tile
            label="Open risks"
            value={s?.open_risks ?? "—"}
            hint="RAID register"
            onOpen={drill("risk")}
          />
        )}
      </div>

      {/* The bet — relocated here from above the tabs so it leads the entry, not every workspace. */}
      {outcomesOn && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <OutcomesPanel scope="project" scopeId={id} mayWrite={mayPlan} />
        </div>
      )}
    </div>
  );
}
