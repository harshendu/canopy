import { lazy, Suspense, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  AlertsResponse,
  BoardResponse,
  CapacityResponse,
  ForecastResponse,
  GanttResponse,
  Initiative,
  InitiativeCriticalPath,
  Project,
  ScenarioDetail,
} from "../api/types";
import CapacityHeatmap from "../components/CapacityHeatmap";
import GanttChart from "../components/GanttChart";
import ScenarioCompare from "../components/ScenarioCompare";
import ScenarioEditor from "../components/ScenarioEditor";
import { PageHeader } from "../components/PageHeader";
import { Icon } from "../components/icons";
import { useCurrentUser } from "../lib/useCurrentUser";
import { isPlanner } from "../lib/permissions";
import {
  SCENARIO_GROUPS,
  SCENARIO_NEEDS_PROJECT,
  SCENARIO_VIEW_ICONS,
  SCENARIO_VIEW_LABELS,
  defaultScenarioView,
  resolveScenarioView,
  type ScenarioGroupKey,
  type ScenarioView,
} from "../lib/scenarioNav";

const DependencyGraph = lazy(() => import("../components/DependencyGraph"));
const BurndownChart = lazy(() => import("../components/BurndownChart"));

function Loading() {
  return <p className="text-sm text-slate-400">Loading…</p>;
}

export default function ScenarioWorkspace() {
  const { initiativeId, scenarioId } = useParams();
  const sid = Number(scenarioId);
  const [searchParams, setSearchParams] = useSearchParams();
  const { group: activeGroup, view } = resolveScenarioView(searchParams.get("tab"));
  const [projectId, setProjectId] = useState<number | null>(null);
  const { data: me } = useCurrentUser();
  const mayPlan = isPlanner(me?.role); // scenario edits are planner-gated (§A3a / §T2)

  const goToView = (v: ScenarioView) => setSearchParams({ tab: v }, { replace: true });
  const goToGroup = (key: ScenarioGroupKey) => goToView(defaultScenarioView(key));

  const scenario = useQuery({
    queryKey: ["scenario", sid],
    queryFn: () => api.get<ScenarioDetail>(`/scenarios/${sid}`),
  });
  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<Project[]>("/projects"),
  });
  const { data: initiatives = [] } = useQuery({
    queryKey: ["initiatives"],
    queryFn: () => api.get<Initiative[]>("/initiatives"),
  });
  const initiativeName =
    initiatives.find((i) => i.id === Number(initiativeId))?.name ?? "Initiative";
  const projects = (projectsQuery.data ?? []).filter(
    (p) => p.initiative_id === Number(initiativeId),
  );
  const activeProject = projectId ?? projects[0]?.id ?? null;

  const activeSub = SCENARIO_GROUPS.find((g) => g.key === activeGroup)?.tabs ?? [];
  const showPicker = SCENARIO_NEEDS_PROJECT.includes(view) && projects.length > 0;

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumbs={[
          { label: "Initiatives", to: "/initiatives" },
          { label: initiativeName, to: `/initiatives/${initiativeId}` },
          { label: "Scenarios", to: `/initiatives/${initiativeId}/scenarios` },
          { label: scenario.data?.title ?? "Scenario" },
        ]}
        title={scenario.data?.title ?? "Scenario"}
        titleAdornment={
          scenario.data && (
            <span
              className={`rounded px-2 py-0.5 text-xs font-medium ${
                scenario.data.status === "applied"
                  ? "bg-canopy-100 text-canopy-700"
                  : "bg-slate-100 text-slate-600"
              }`}
            >
              {scenario.data.status}
            </span>
          )
        }
        actions={
          showPicker && activeProject != null ? (
            <select
              value={activeProject}
              onChange={(e) => setProjectId(Number(e.target.value))}
              className="rounded border border-slate-300 px-3 py-2 text-sm"
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.key} · {p.name}
                </option>
              ))}
            </select>
          ) : undefined
        }
      />

      {/* Two-level nav: scenario workspaces (primary) + the active group's views (secondary),
          matching the project cockpit (§B3). */}
      <div>
        <div
          role="tablist"
          aria-label="Scenario workspaces"
          className="flex gap-1 overflow-x-auto border-b border-slate-200"
        >
          {SCENARIO_GROUPS.map((g) => (
            <button
              key={g.key}
              role="tab"
              aria-selected={activeGroup === g.key}
              onClick={() => goToGroup(g.key)}
              className={`-mb-px flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-4 py-2 text-sm font-medium ${
                activeGroup === g.key
                  ? "border-canopy-500 text-canopy-700"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              <Icon name={g.icon} size={15} />
              {g.label}
            </button>
          ))}
        </div>
        {activeSub.length > 0 && (
          <div role="tablist" aria-label="Views" className="mt-2 flex flex-wrap gap-1">
            {activeSub.map((v) => (
              <button
                key={v}
                role="tab"
                aria-selected={view === v}
                onClick={() => goToView(v)}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium ${
                  view === v
                    ? "bg-canopy-50 text-canopy-700"
                    : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
                }`}
              >
                <Icon name={SCENARIO_VIEW_ICONS[v]} size={14} />
                {SCENARIO_VIEW_LABELS[v]}
              </button>
            ))}
          </div>
        )}
      </div>

      <div>
        {view === "compare" && (
          <ScenarioCompare scenarioId={sid} status={scenario.data?.status ?? "draft"} />
        )}
        {view === "edit" &&
          activeProject != null &&
          (mayPlan ? (
            <ScenarioEditor
              scenarioId={sid}
              projects={projects}
              projectId={activeProject}
              onProjectChange={setProjectId}
            />
          ) : (
            <p className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">
              Editing a scenario is limited to planners (architect / engineering manager). You can
              view every projection here.
            </p>
          ))}
        {view === "criticalpath" && <CriticalPathPanel scenarioId={sid} />}
        {view === "capacity" && <CapacityPanel scenarioId={sid} />}
        {view === "forecast" && <ForecastPanel scenarioId={sid} />}
        {view === "gantt" && activeProject != null && (
          <GanttPanel scenarioId={sid} projectId={activeProject} />
        )}
        {view === "deps" && activeProject != null && (
          <DepsPanel scenarioId={sid} projectId={activeProject} />
        )}
        {view === "board" && activeProject != null && (
          <BoardPanel scenarioId={sid} projectId={activeProject} />
        )}
        {view === "burndown" && activeProject != null && (
          <BurndownPanel scenarioId={sid} projectId={activeProject} />
        )}
        {view === "alerts" && activeProject != null && (
          <AlertsPanel scenarioId={sid} projectId={activeProject} />
        )}
        {SCENARIO_NEEDS_PROJECT.includes(view) && projects.length === 0 && (
          <p className="text-sm text-slate-500">This initiative has no projects.</p>
        )}
      </div>
    </div>
  );
}

function GanttPanel({ scenarioId, projectId }: { scenarioId: number; projectId: number }) {
  const q = useQuery({
    queryKey: ["scenario-gantt", scenarioId, projectId],
    queryFn: () =>
      api.get<GanttResponse>(`/scenarios/${scenarioId}/gantt?project_id=${projectId}`),
  });
  return q.data ? <GanttChart data={q.data} /> : <Loading />;
}

function DepsPanel({ scenarioId, projectId }: { scenarioId: number; projectId: number }) {
  const q = useQuery({
    queryKey: ["scenario-gantt", scenarioId, projectId],
    queryFn: () =>
      api.get<GanttResponse>(`/scenarios/${scenarioId}/gantt?project_id=${projectId}`),
  });
  return q.data ? (
    <Suspense fallback={<Loading />}>
      <DependencyGraph data={q.data} />
    </Suspense>
  ) : (
    <Loading />
  );
}

function CapacityPanel({ scenarioId }: { scenarioId: number }) {
  const q = useQuery({
    queryKey: ["scenario-capacity", scenarioId],
    queryFn: () => api.get<CapacityResponse>(`/scenarios/${scenarioId}/capacity`),
  });
  return q.data ? <CapacityHeatmap data={q.data} /> : <Loading />;
}

function BurndownPanel({ scenarioId, projectId }: { scenarioId: number; projectId: number }) {
  const q = useQuery({
    queryKey: ["scenario-burndown", scenarioId, projectId],
    queryFn: () =>
      api.get<import("../api/types").BurndownResponse>(
        `/scenarios/${scenarioId}/burndown?project_id=${projectId}`,
      ),
  });
  return q.data ? (
    <Suspense fallback={<Loading />}>
      <BurndownChart data={q.data} />
    </Suspense>
  ) : (
    <Loading />
  );
}

function CriticalPathPanel({ scenarioId }: { scenarioId: number }) {
  const q = useQuery({
    queryKey: ["scenario-cp", scenarioId],
    queryFn: () => api.get<InitiativeCriticalPath>(`/scenarios/${scenarioId}/critical-path`),
  });
  if (!q.data) return <Loading />;
  const cp = q.data;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center gap-2">
        <h2 className="font-semibold">Cross-project critical path</h2>
        <span className="text-xs text-slate-400">{cp.total_working_days} working days</span>
        {cp.spans_projects && (
          <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
            {cp.handoffs.length} hand-off{cp.handoffs.length === 1 ? "" : "s"}
          </span>
        )}
      </div>
      <ol className="mt-3 flex flex-wrap items-center gap-1">
        {cp.tasks.map((t, idx) => {
          const handoff = idx > 0 && cp.tasks[idx - 1].project_key !== t.project_key;
          return (
            <li key={t.task_id} className="flex items-center gap-1">
              {idx > 0 && <span className={handoff ? "text-amber-500" : "text-slate-300"}>→</span>}
              <span
                className={`rounded border px-2 py-1 text-xs ${
                  handoff ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-slate-50"
                }`}
              >
                <span className="font-mono text-[10px] text-slate-400">{t.project_key}</span>{" "}
                {t.name}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function ForecastPanel({ scenarioId }: { scenarioId: number }) {
  const q = useQuery({
    queryKey: ["scenario-forecast", scenarioId],
    queryFn: () => api.get<ForecastResponse>(`/scenarios/${scenarioId}/forecast`),
  });
  if (!q.data) return <Loading />;
  const f = q.data;
  if (!f.sufficient) {
    return <p className="text-sm text-slate-500">Not enough throughput history: {f.reason}</p>;
  }
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="text-xs uppercase text-slate-400">Remaining</div>
        <div className="text-2xl font-bold">{f.remaining_items}</div>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="text-xs uppercase text-slate-400">P50</div>
        <div className="text-2xl font-bold">{f.p50_date ?? "—"}</div>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="text-xs uppercase text-slate-400">P85</div>
        <div className="text-2xl font-bold">{f.p85_date ?? "—"}</div>
      </div>
    </div>
  );
}

function BoardPanel({ scenarioId, projectId }: { scenarioId: number; projectId: number }) {
  const q = useQuery({
    queryKey: ["scenario-board", scenarioId, projectId],
    queryFn: () =>
      api.get<BoardResponse>(`/scenarios/${scenarioId}/board?project_id=${projectId}`),
  });
  if (!q.data) return <Loading />;
  return (
    <div className="flex gap-3 overflow-auto">
      {q.data.lanes.map((lane) => (
        <div key={lane.status} className="w-56 shrink-0 rounded-lg border border-slate-200 bg-white p-3">
          <div className="mb-2 flex items-center justify-between text-sm font-medium">
            <span>{lane.status || "(no status)"}</span>
            <span className="text-xs text-slate-400">{lane.wip}</span>
          </div>
          <ul className="space-y-1">
            {lane.tasks.map((t) => (
              <li
                key={t.id}
                className={`rounded border px-2 py-1 text-xs ${
                  t.aging ? "border-amber-300 bg-amber-50" : "border-slate-200"
                }`}
              >
                {t.name}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function AlertsPanel({ scenarioId, projectId }: { scenarioId: number; projectId: number }) {
  const q = useQuery({
    queryKey: ["scenario-alerts", scenarioId, projectId],
    queryFn: () =>
      api.get<AlertsResponse>(`/scenarios/${scenarioId}/alerts?project_id=${projectId}`),
  });
  if (!q.data) return <Loading />;
  if (q.data.alerts.length === 0) {
    return <p className="text-sm text-slate-500">No alerts in this scenario.</p>;
  }
  return (
    <ul className="space-y-1 text-sm">
      {q.data.alerts.map((a, i) => (
        <li
          key={i}
          className={`rounded border px-3 py-2 ${
            a.severity === "error"
              ? "border-red-300 bg-red-50 text-red-700"
              : a.severity === "warning"
                ? "border-amber-300 bg-amber-50 text-amber-700"
                : "border-slate-200 bg-white text-slate-600"
          }`}
        >
          {a.message}
        </li>
      ))}
    </ul>
  );
}
