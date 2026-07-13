import { lazy, Suspense, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  Baseline,
  BurndownResponse,
  ForecastResponse,
  GanttResponse,
  Project,
  Proposal,
  ReplanResult,
  Task,
  TaskType,
} from "../api/types";
import GanttChart from "../components/GanttChart";
import CapacityView from "../components/CapacityView";
import RoadmapView from "../components/RoadmapView";
import DeliveryView from "../components/DeliveryView";
import SpecsView from "../components/SpecsView";
import DocsView from "../components/DocsView";
import ExportMenu from "../components/ExportMenu";
import DeliveryMetaBar from "../components/DeliveryMetaBar";
import OutcomesPanel from "../components/OutcomesPanel";
import RiskRegister from "../components/RiskRegister";
import JiraLinksPanel from "../components/JiraLinksPanel";
import TaskDetailPanel from "../components/TaskDetailPanel";
import { PageHeader } from "../components/PageHeader";
import { Icon, type IconName } from "../components/icons";
import { useCurrentUser } from "../lib/useCurrentUser";
import { canContribute, canWriteProjects, isPlanner } from "../lib/permissions";
import { featureOn, useFeatures } from "../lib/useFeatures";

// Heavy (React Flow / Recharts) — code-split.
const DependencyGraph = lazy(() => import("../components/DependencyGraph"));
const FlowBoard = lazy(() => import("../components/FlowBoard"));
const ArchitectureView = lazy(() => import("../components/ArchitectureView"));
const DecisionsView = lazy(() => import("../components/DecisionsView"));
const RiskView = lazy(() => import("../components/RiskView"));
const DriftView = lazy(() => import("../components/DriftView"));
const RetrosView = lazy(() => import("../components/RetrosView"));
const ActivityView = lazy(() => import("../components/ActivityView"));
const BurndownChart = lazy(() => import("../components/BurndownChart"));
const DraftPlanView = lazy(() => import("../components/DraftPlanView"));

type Tab =
  | "gantt"
  | "board"
  | "specs"
  | "deps"
  | "capacity"
  | "decisions"
  | "docs"
  | "architecture"
  | "drift"
  | "roadmap"
  | "drafts"
  | "jiralinks"
  | "burndown"
  | "delivery"
  | "risk"
  | "retros"
  | "activity";

const TABS: Tab[] = [
  "gantt",
  "board",
  "specs",
  "deps",
  "capacity",
  "decisions",
  "docs",
  "architecture",
  "drift",
  "roadmap",
  "drafts",
  "jiralinks",
  "burndown",
  "delivery",
  "risk",
  "retros",
  "activity",
];

/** The feature gate each tab sits behind (absent = core, always on). A gated-off tab
 *  disappears from the tab bar and an active one snaps back to the Gantt. */
const TAB_FEATURES: Partial<Record<Tab, string>> = {
  board: "tracking.board",
  specs: "governance.specs",
  capacity: "tracking.capacity",
  decisions: "architecture",
  docs: "governance.docs",
  architecture: "architecture",
  drift: "architecture.drift",
  drafts: "planning.draft_plans",
  jiralinks: "integrations",
  burndown: "tracking.burndown",
  delivery: "tracking.delivery",
  risk: "governance.risk",
  retros: "governance.retros",
};

const TAB_ICONS: Record<Tab, IconName> = {
  gantt: "gantt",
  board: "board",
  specs: "specs",
  deps: "deps",
  capacity: "capacity",
  decisions: "decisions",
  docs: "docs",
  architecture: "architecture",
  drift: "drift",
  roadmap: "roadmap",
  drafts: "drafts",
  jiralinks: "jiralinks",
  burndown: "burndown",
  delivery: "delivery",
  risk: "risk",
  retros: "retros",
  activity: "activity",
};

export default function ProjectView() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const initialTab: Tab = TABS.includes(requestedTab as Tab) ? (requestedTab as Tab) : "gantt";

  const [taskName, setTaskName] = useState("");
  const [taskDuration, setTaskDuration] = useState(3);
  const [taskType, setTaskType] = useState<TaskType>("task");
  const [taskDeadline, setTaskDeadline] = useState("");
  const [pred, setPred] = useState<number | "">("");
  const [succ, setSucc] = useState<number | "">("");
  const [lastReplan, setLastReplan] = useState<ReplanResult | null>(null);
  const [baselining, setBaselining] = useState(false);
  const [baselineNote, setBaselineNote] = useState("");
  const [activeTab, setTab] = useState<Tab>(initialTab);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const { data: me } = useCurrentUser();
  const features = useFeatures();
  const tabOn = (key: Tab) => {
    const gate = TAB_FEATURES[key];
    return gate === undefined || featureOn(features, gate);
  };
  // If an admin turns the active tab's feature off mid-session, snap back to the Gantt.
  const tab: Tab = tabOn(activeTab) ? activeTab : "gantt";
  const mayPlan = isPlanner(me?.role);
  const mayWriteProject = canWriteProjects(me?.role);
  const mayContribute = canContribute(me?.role);

  const project = useQuery({
    queryKey: ["project", id],
    queryFn: () => api.get<Project>(`/projects/${id}`),
  });
  const gantt = useQuery({
    queryKey: ["gantt", id],
    queryFn: () => api.get<GanttResponse>(`/projects/${id}/gantt`),
  });
  const tasks = useQuery({
    queryKey: ["tasks", id],
    queryFn: () => api.get<Task[]>(`/tasks?project_id=${id}`),
  });
  const burndown = useQuery({
    queryKey: ["burndown", id],
    queryFn: () => api.get<BurndownResponse>(`/projects/${id}/burndown`),
    enabled: tab === "burndown",
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["gantt", id] });
    qc.invalidateQueries({ queryKey: ["tasks", id] });
  };

  const addTask = useMutation({
    mutationFn: () =>
      api.post<Task>("/tasks", {
        project_id: id,
        name: taskName,
        duration: taskDuration,
        type: taskType,
        deadline: taskDeadline || null,
      }),
    onSuccess: () => {
      setTaskName("");
      setTaskDeadline("");
      invalidate();
    },
  });

  const toggleWeekends = useMutation({
    mutationFn: (skip: boolean) =>
      api.patch<Project>(`/projects/${id}`, { skip_weekends: skip }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", id] });
      qc.invalidateQueries({ queryKey: ["gantt", id] });
    },
  });

  const addDependency = useMutation({
    mutationFn: () =>
      api.post("/dependencies", { predecessor_id: pred, successor_id: succ }),
    onSuccess: () => {
      setPred("");
      setSucc("");
      invalidate();
    },
  });

  const replan = useMutation({
    mutationFn: () => api.post<ReplanResult>(`/projects/${id}/replan`),
    onSuccess: (res) => {
      setLastReplan(res);
      invalidate();
    },
  });

  const baselinesOn = featureOn(features, "planning.baselines");
  const forecastOn = featureOn(features, "tracking.forecast");
  // Staged changes awaiting review for THIS project (agent proposals — §AA).
  const openProposals = useQuery({
    queryKey: ["proposals", "open", "project", id],
    queryFn: () =>
      api.get<Proposal[]>(`/proposals?status=open&scope_level=project&scope_id=${id}`),
    enabled: featureOn(features, "ai.proposals"),
    staleTime: 30 * 1000,
  });
  const pendingReviews = openProposals.data?.length ?? 0;
  const baselines = useQuery({
    queryKey: ["baselines", id],
    queryFn: () => api.get<Baseline[]>(`/projects/${id}/baselines`),
    enabled: tab === "gantt" && baselinesOn,
  });
  const forecast = useQuery({
    queryKey: ["forecast", id],
    queryFn: () => api.get<ForecastResponse>(`/projects/${id}/forecast`),
    enabled: tab === "gantt" && forecastOn,
  });

  const baseline = useMutation({
    mutationFn: (note: string) =>
      api.post(`/projects/${id}/baseline`, { note: note || null }),
    onSuccess: () => {
      setBaselining(false);
      setBaselineNote("");
      qc.invalidateQueries({ queryKey: ["gantt", id] });
      qc.invalidateQueries({ queryKey: ["baselines", id] });
    },
  });

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[
          { label: "Projects", to: "/projects" },
          { label: project.data ? project.data.name : "Project" },
        ]}
        title={project.data ? project.data.name : "Project"}
        actions={
          <>
          {featureOn(features, "reporting.exports") && <ExportMenu scope="project" id={id} />}
          {mayWriteProject && (
            <label className="flex items-center gap-1 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={project.data?.skip_weekends ?? false}
                onChange={(e) => toggleWeekends.mutate(e.target.checked)}
              />
              5-day week
            </label>
          )}
          {mayPlan && (
            <>
              {!baselinesOn ? null : baselining ? (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    baseline.mutate(baselineNote);
                  }}
                  className="flex items-center gap-1"
                >
                  <input
                    autoFocus
                    value={baselineNote}
                    onChange={(e) => setBaselineNote(e.target.value)}
                    placeholder="Why re-baseline? (optional)"
                    className="w-56 rounded border border-slate-300 px-2 py-2 text-sm"
                  />
                  <button
                    type="submit"
                    disabled={baseline.isPending}
                    className="rounded bg-canopy-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
                  >
                    {baseline.isPending ? "Saving…" : "Save baseline"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setBaselining(false)}
                    className="px-2 py-2 text-sm text-slate-500"
                  >
                    Cancel
                  </button>
                </form>
              ) : (
                <button
                  onClick={() => setBaselining(true)}
                  className="rounded border border-canopy-500 px-4 py-2 text-sm font-medium text-canopy-700"
                >
                  Set baseline
                </button>
              )}
              <button
                onClick={() => replan.mutate()}
                disabled={replan.isPending}
                className="rounded bg-canopy-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {replan.isPending ? "Scheduling…" : "Schedule (CPM)"}
              </button>
            </>
          )}
          </>
        }
      />

      {pendingReviews > 0 && (
        <Link
          to="/reviews"
          className="flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 hover:bg-amber-100"
        >
          <span className="rounded-full bg-amber-500 px-1.5 text-xs font-semibold text-white">
            {pendingReviews}
          </span>
          staged change {pendingReviews === 1 ? "proposal" : "proposals"} for this project
          await your review — nothing touches the plan until you apply them.
        </Link>
      )}

      {project.data && (
        <DeliveryMetaBar
          scope="project"
          id={id}
          health={project.data.health}
          statusNote={project.data.status_note}
          tags={project.data.tags}
          mayWrite={mayWriteProject}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ["project", id] });
            qc.invalidateQueries({ queryKey: ["portfolio"] });
          }}
        />
      )}

      {featureOn(features, "portfolio.outcomes") && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <OutcomesPanel scope="project" scopeId={id} mayWrite={mayPlan} />
        </div>
      )}

      {lastReplan && (
        <div className="space-y-1">
          <div className="rounded border border-canopy-500/30 bg-canopy-50 px-4 py-2 text-sm text-canopy-700">
            Scheduled {lastReplan.scheduled_tasks} tasks · critical path:{" "}
            {lastReplan.critical_path.join(" → ") || "none"} · ends{" "}
            {lastReplan.project_end ?? "—"}
          </div>
          {lastReplan.deadline_violations.length > 0 && (
            <div className="rounded border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-700">
              ⚠ {lastReplan.deadline_violations.length} task(s) miss their deadline:{" "}
              {lastReplan.deadline_violations.join(", ")}
            </div>
          )}
        </div>
      )}

      <div className="flex gap-1 overflow-x-auto border-b border-slate-200">
        {([
          ["gantt", "Gantt"],
          ["board", "Board"],
          ["specs", "Specs"],
          ["deps", "Dependencies"],
          ["capacity", "Capacity"],
          ["decisions", "Decisions"],
          ["docs", "Docs"],
          ["architecture", "Architecture"],
          ["drift", "Drift"],
          ["roadmap", "Roadmap"],
          ["drafts", "Plan → Jira"],
          ["jiralinks", "Jira Links"],
          ["burndown", "Burndown"],
          ["delivery", "Delivery"],
          ["risk", "Risk"],
          ["retros", "Retros"],
          ["activity", "Activity"],
        ] as [Tab, string][])
          .filter(([key]) => tabOn(key))
          .map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`-mb-px flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-4 py-2 text-sm font-medium ${
                tab === key
                  ? "border-canopy-500 text-canopy-700"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              <Icon name={TAB_ICONS[key]} size={15} />
              {label}
            </button>
          ))}
      </div>

      {tab === "gantt" && (
        <>
          {gantt.data && gantt.data.tasks.length > 0 ? (
            <GanttChart data={gantt.data} onTaskClick={setSelectedTaskId} />
          ) : (
            <p className="text-sm text-slate-500">
              No tasks yet — add tasks below, then run “Schedule (CPM)”.
            </p>
          )}
          {forecast.data && (
            <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
              <div className="flex items-center gap-2">
                <h2 className="font-semibold">Probabilistic forecast</h2>
                <span className="text-xs text-slate-400">
                  Monte-Carlo from past throughput — the honest answer next to the CPM date
                </span>
              </div>
              {forecast.data.sufficient ? (
                <div className="mt-2 flex flex-wrap gap-6 text-sm">
                  <div>
                    <span className="text-xs uppercase tracking-wide text-slate-400">
                      P50 (likely)
                    </span>
                    <div className="text-lg font-bold tabular-nums">
                      {forecast.data.p50_date}
                    </div>
                    <div className="text-xs text-slate-400">~{forecast.data.p50_weeks} wk</div>
                  </div>
                  <div>
                    <span className="text-xs uppercase tracking-wide text-slate-400">
                      P85 (safe)
                    </span>
                    <div className="text-lg font-bold tabular-nums text-amber-700">
                      {forecast.data.p85_date}
                    </div>
                    <div className="text-xs text-slate-400">~{forecast.data.p85_weeks} wk</div>
                  </div>
                  <div className="self-center text-xs text-slate-400">
                    {forecast.data.remaining_items} items left · {forecast.data.history_weeks} weeks
                    of throughput
                  </div>
                </div>
              ) : (
                <p className="mt-2 text-sm text-slate-500">{forecast.data.reason}</p>
              )}
            </div>
          )}
          {(baselines.data?.length ?? 0) > 0 && (
            <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
              <h2 className="mb-1 font-semibold">Baseline history</h2>
              <p className="mb-2 text-xs text-slate-500">
                The Gantt shows current-vs-baseline as <strong>schedule variance</strong>.
                Re-baselining is a deliberate reset of the plan-of-record — here’s when and why.
              </p>
              <ul className="space-y-1 text-sm">
                {(baselines.data ?? []).map((b) => (
                  <li key={b.id} className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-medium tabular-nums">
                      {new Date(b.created_at).toLocaleDateString()}
                    </span>
                    <span className="text-slate-600">{b.note || "(no reason given)"}</span>
                    <span className="ml-auto text-xs text-slate-400">
                      {b.task_count} tasks{b.project_end ? ` · ends ${b.project_end}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {tab === "board" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading board…</p>}>
          <FlowBoard projectId={id} onTaskClick={setSelectedTaskId} />
        </Suspense>
      )}

      {tab === "deps" &&
        (gantt.data && gantt.data.tasks.length > 0 ? (
          <Suspense fallback={<p className="text-sm text-slate-500">Loading graph…</p>}>
            <DependencyGraph data={gantt.data} />
          </Suspense>
        ) : (
          <p className="text-sm text-slate-500">No tasks to graph yet.</p>
        ))}

      {tab === "specs" && (
        <SpecsView projectId={id} mayPlan={mayPlan} mayContribute={mayContribute} />
      )}

      {tab === "docs" && <DocsView scope="project" scopeId={id} mayWrite={mayPlan} />}

      {tab === "delivery" && <DeliveryView scope="project" id={id} />}

      {tab === "capacity" && <CapacityView projectId={id} />}

      {tab === "decisions" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading decisions…</p>}>
          <DecisionsView projectId={id} />
        </Suspense>
      )}

      {tab === "architecture" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading architecture…</p>}>
          <ArchitectureView projectId={id} />
        </Suspense>
      )}

      {tab === "drift" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading drift…</p>}>
          <DriftView projectId={id} />
        </Suspense>
      )}

      {tab === "roadmap" && <RoadmapView projectId={id} />}

      {tab === "drafts" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading drafts…</p>}>
          <DraftPlanView projectId={id} />
        </Suspense>
      )}

      {tab === "jiralinks" && <JiraLinksPanel targetType="project" targetId={id} />}

      {tab === "burndown" &&
        (burndown.data ? (
          <Suspense fallback={<p className="text-sm text-slate-500">Loading chart…</p>}>
            <BurndownChart data={burndown.data} />
          </Suspense>
        ) : (
          <p className="text-sm text-slate-500">Loading burndown…</p>
        ))}

      {tab === "risk" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading risk…</p>}>
          <div className="space-y-6">
            <RiskView projectId={id} />
            <RiskRegister scope="project" scopeId={id} mayWrite={mayPlan} />
          </div>
        </Suspense>
      )}

      {tab === "retros" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading retros…</p>}>
          <RetrosView projectId={id} />
        </Suspense>
      )}

      {tab === "activity" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading activity…</p>}>
          <ActivityView projectId={id} />
        </Suspense>
      )}

      {mayPlan && (
      <div className="grid grid-cols-2 gap-6">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (taskName) addTask.mutate();
          }}
          className="space-y-2 rounded-lg border border-slate-200 bg-white p-4"
        >
          <h2 className="font-semibold">Add task</h2>
          <input
            value={taskName}
            onChange={(e) => setTaskName(e.target.value)}
            placeholder="Task name"
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <div className="flex gap-2">
            <input
              type="number"
              min={0}
              value={taskDuration}
              onChange={(e) => setTaskDuration(Number(e.target.value))}
              className="w-24 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <select
              value={taskType}
              onChange={(e) => setTaskType(e.target.value as TaskType)}
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="task">Task</option>
              <option value="milestone">Milestone</option>
              <option value="summary">Summary / phase</option>
            </select>
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-500">
            Deadline (optional)
            <input
              type="date"
              value={taskDeadline}
              onChange={(e) => setTaskDeadline(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1 text-sm"
            />
            <button className="ml-auto rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
              Add
            </button>
          </label>
        </form>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (pred && succ && pred !== succ) addDependency.mutate();
          }}
          className="space-y-2 rounded-lg border border-slate-200 bg-white p-4"
        >
          <h2 className="font-semibold">Add dependency (finish → start)</h2>
          <select
            value={pred}
            onChange={(e) => setPred(Number(e.target.value))}
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="">Predecessor…</option>
            {(tasks.data ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <div className="flex gap-2">
            <select
              value={succ}
              onChange={(e) => setSucc(Number(e.target.value))}
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">Successor…</option>
              {(tasks.data ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
              Link
            </button>
          </div>
        </form>
      </div>
      )}

      {selectedTaskId !== null && (
        <TaskDetailPanel
          taskId={selectedTaskId}
          projectId={id}
          mayPlan={mayPlan}
          mayContribute={mayContribute}
          onClose={() => setSelectedTaskId(null)}
        />
      )}
    </div>
  );
}
