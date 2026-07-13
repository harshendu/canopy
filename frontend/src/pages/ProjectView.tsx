import { lazy, Suspense, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import type {
  Baseline,
  BurndownResponse,
  DependencyType,
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
import ProjectOverview from "../components/ProjectOverview";
import RiskRegister from "../components/RiskRegister";
import JiraLinksPanel from "../components/JiraLinksPanel";
import TaskDetailPanel from "../components/TaskDetailPanel";
import HolidaysEditor from "../components/HolidaysEditor";
import { PageHeader } from "../components/PageHeader";
import { Icon } from "../components/icons";
import {
  TAB_ICONS,
  TAB_LABELS,
  defaultTabForGroup,
  resolveProjectTab,
  visibleProjectNav,
  type ProjectGroupKey,
  type ProjectTab,
} from "../lib/projectNav";
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

export default function ProjectView() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const qc = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  const [taskName, setTaskName] = useState("");
  const [taskDuration, setTaskDuration] = useState(3);
  const [taskType, setTaskType] = useState<TaskType>("task");
  const [taskDeadline, setTaskDeadline] = useState("");
  const [taskParent, setTaskParent] = useState<number | "">("");
  const [pred, setPred] = useState<number | "">("");
  const [succ, setSucc] = useState<number | "">("");
  const [depType, setDepType] = useState<DependencyType>("FS");
  const [depLag, setDepLag] = useState(0);
  const [lastReplan, setLastReplan] = useState<ReplanResult | null>(null);
  const [replanError, setReplanError] = useState<string | null>(null);
  const [baselining, setBaselining] = useState(false);
  const [baselineNote, setBaselineNote] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const { data: me } = useCurrentUser();
  const features = useFeatures();
  const isOn = (key: string) => featureOn(features, key);

  // The active workspace is derived from the URL (`?tab=<leaf>`), so tab state is deep-linkable,
  // shareable, and survives back/forward. A known, enabled leaf selects it + its parent group;
  // anything else (absent / unknown / gated-off) lands on the Overview. `?tab=` leaf keys are
  // unchanged from the old flat bar, so every existing deep link keeps working.
  const { group: activeGroup, tab: activeTab } = resolveProjectTab(searchParams.get("tab"), isOn);
  const nav = visibleProjectNav(isOn);
  const activeSub = nav.find((n) => n.group.key === activeGroup)?.tabs ?? [];

  const goToTab = (t: ProjectTab) => setSearchParams({ tab: t }, { replace: true });
  const goToGroup = (key: ProjectGroupKey) => {
    if (key === "overview") {
      setSearchParams({}, { replace: true });
      return;
    }
    const def = defaultTabForGroup(key, isOn);
    if (def) goToTab(def);
  };

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
    enabled: activeTab === "burndown",
  });

  // Map task id → name so the replan banner reads names, not raw ids (the API returns id lists).
  const taskName_ = useMemo(
    () => new Map((tasks.data ?? []).map((t) => [t.id, t.name] as const)),
    [tasks.data],
  );
  const labelFor = (tid: number): string => taskName_.get(tid) ?? `#${tid}`;

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["gantt", id] });
    qc.invalidateQueries({ queryKey: ["tasks", id] });
  };
  // A structural/duration edit invalidates CPM output (start/end/critical path). Re-run the
  // scheduler automatically so the plan never silently goes stale (was: user had to remember to
  // click "Schedule (CPM)"). The delta banner shows what moved.
  const replanAfterEdit = () => {
    if (mayPlan) replan.mutate();
  };

  const addTask = useMutation({
    mutationFn: () =>
      api.post<Task>("/tasks", {
        project_id: id,
        name: taskName,
        duration: taskDuration,
        type: taskType,
        deadline: taskDeadline || null,
        parent_id: taskParent === "" ? null : taskParent,
      }),
    onSuccess: () => {
      setTaskName("");
      setTaskDeadline("");
      setTaskParent("");
      invalidate();
      replanAfterEdit();
    },
    onError: (e) => setReplanError(e instanceof ApiError ? e.message : "Couldn’t add the task."),
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
      api.post("/dependencies", {
        predecessor_id: pred,
        successor_id: succ,
        type: depType,
        lag: depLag,
      }),
    onSuccess: () => {
      setPred("");
      setSucc("");
      setDepType("FS");
      setDepLag(0);
      invalidate();
      replanAfterEdit();
    },
    onError: (e) =>
      setReplanError(e instanceof ApiError ? e.message : "Couldn’t link the dependency."),
  });

  const deleteDependency = useMutation({
    mutationFn: (depId: number) => api.del(`/dependencies/${depId}`),
    onSuccess: () => {
      invalidate();
      replanAfterEdit();
    },
    onError: (e) =>
      setReplanError(e instanceof ApiError ? e.message : "Couldn’t remove the dependency."),
  });

  const replan = useMutation({
    mutationFn: () => api.post<ReplanResult>(`/projects/${id}/replan`),
    onSuccess: (res) => {
      setLastReplan(res);
      setReplanError(null);
      invalidate();
    },
    // Surface scheduling failures (e.g. a cyclic dependency → 409) instead of failing silently.
    onError: (e) =>
      setReplanError(
        e instanceof ApiError
          ? e.status === 409
            ? "Scheduling failed: the dependencies form a cycle. Remove the circular link and retry."
            : e.message
          : "Scheduling failed.",
      ),
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
    enabled: activeTab === "gantt" && baselinesOn,
  });
  const forecast = useQuery({
    queryKey: ["forecast", id],
    queryFn: () => api.get<ForecastResponse>(`/projects/${id}/forecast`),
    enabled: activeTab === "gantt" && forecastOn,
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

      {replanError && (
        <div
          role="alert"
          className="flex items-start justify-between gap-3 rounded border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-700"
        >
          <span>⚠ {replanError}</span>
          <button
            onClick={() => setReplanError(null)}
            className="text-red-500 hover:text-red-800"
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      )}

      {lastReplan && (
        <div className="space-y-1">
          <div className="rounded border border-canopy-500/30 bg-canopy-50 px-4 py-2 text-sm text-canopy-700">
            Scheduled {lastReplan.scheduled_tasks} tasks · critical path:{" "}
            {lastReplan.critical_path.map(labelFor).join(" → ") || "none"} · ends{" "}
            {lastReplan.project_end ?? "—"}
          </div>
          {lastReplan.deadline_violations.length > 0 && (
            <div className="rounded border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-700">
              ⚠ {lastReplan.deadline_violations.length} task(s) miss their deadline:{" "}
              {lastReplan.deadline_violations.map(labelFor).join(", ")}
            </div>
          )}
        </div>
      )}

      {/* Two-level workspace navigation: the six domain groups (primary), then the active group's
          views (secondary). Collapses to Miller's ~7 primary choices instead of a 17-tab scroll. */}
      <div>
        <div
          role="tablist"
          aria-label="Project workspaces"
          className="flex gap-1 overflow-x-auto border-b border-slate-200"
        >
          {nav.map(({ group }) => (
            <button
              key={group.key}
              role="tab"
              aria-selected={activeGroup === group.key}
              onClick={() => goToGroup(group.key)}
              className={`-mb-px flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-4 py-2 text-sm font-medium ${
                activeGroup === group.key
                  ? "border-canopy-500 text-canopy-700"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              <Icon name={group.icon} size={15} />
              {group.label}
            </button>
          ))}
        </div>
        {activeSub.length > 0 && (
          <div role="tablist" aria-label="Views" className="mt-2 flex flex-wrap gap-1">
            {activeSub.map((t) => (
              <button
                key={t}
                role="tab"
                aria-selected={activeTab === t}
                onClick={() => goToTab(t)}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium ${
                  activeTab === t
                    ? "bg-canopy-50 text-canopy-700"
                    : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
                }`}
              >
                <Icon name={TAB_ICONS[t]} size={14} />
                {TAB_LABELS[t]}
              </button>
            ))}
          </div>
        )}
      </div>

      {activeGroup === "overview" && (
        <ProjectOverview projectId={id} mayPlan={mayPlan} isOn={isOn} onOpenTab={goToTab} />
      )}

      {activeTab === "gantt" && (
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

      {activeTab === "board" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading board…</p>}>
          <FlowBoard projectId={id} onTaskClick={setSelectedTaskId} />
        </Suspense>
      )}

      {activeTab === "deps" &&
        (gantt.data && gantt.data.tasks.length > 0 ? (
          <Suspense fallback={<p className="text-sm text-slate-500">Loading graph…</p>}>
            <DependencyGraph data={gantt.data} />
          </Suspense>
        ) : (
          <p className="text-sm text-slate-500">No tasks to graph yet.</p>
        ))}

      {activeTab === "specs" && (
        <SpecsView projectId={id} mayPlan={mayPlan} mayContribute={mayContribute} />
      )}

      {activeTab === "docs" && <DocsView scope="project" scopeId={id} mayWrite={mayPlan} />}

      {activeTab === "delivery" && <DeliveryView scope="project" id={id} />}

      {activeTab === "capacity" && <CapacityView projectId={id} />}

      {activeTab === "decisions" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading decisions…</p>}>
          <DecisionsView projectId={id} />
        </Suspense>
      )}

      {activeTab === "architecture" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading architecture…</p>}>
          <ArchitectureView projectId={id} />
        </Suspense>
      )}

      {activeTab === "drift" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading drift…</p>}>
          <DriftView projectId={id} />
        </Suspense>
      )}

      {activeTab === "roadmap" && <RoadmapView projectId={id} />}

      {activeTab === "drafts" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading drafts…</p>}>
          <DraftPlanView projectId={id} />
        </Suspense>
      )}

      {activeTab === "jiralinks" && <JiraLinksPanel targetType="project" targetId={id} />}

      {activeTab === "burndown" &&
        (burndown.data ? (
          <Suspense fallback={<p className="text-sm text-slate-500">Loading chart…</p>}>
            <BurndownChart data={burndown.data} />
          </Suspense>
        ) : (
          <p className="text-sm text-slate-500">Loading burndown…</p>
        ))}

      {activeTab === "risk" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading risk…</p>}>
          {/* The computed 0–100 score dashboard (leading indicators + acknowledgements + the
              lagging alerts). The human-tracked RAID register is its own sub-view ("raid"). */}
          <RiskView projectId={id} />
        </Suspense>
      )}

      {activeTab === "raid" && (
        <RiskRegister scope="project" scopeId={id} mayWrite={mayPlan} />
      )}

      {activeTab === "retros" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading retros…</p>}>
          <RetrosView projectId={id} />
        </Suspense>
      )}

      {activeTab === "activity" && (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading activity…</p>}>
          <ActivityView projectId={id} />
        </Suspense>
      )}

      {/* The plan-editing forms live with the schedule they edit (the Gantt view), not on every
          workspace. Planner-only. */}
      {mayPlan && activeTab === "gantt" && (
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
          <select
            value={taskParent}
            onChange={(e) => setTaskParent(e.target.value ? Number(e.target.value) : "")}
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            title="Nest this task under a phase — builds the WBS tree"
          >
            <option value="">No parent (top-level)</option>
            {(tasks.data ?? [])
              .filter((t) => t.type === "summary")
              .map((t) => (
                <option key={t.id} value={t.id}>
                  Under: {t.name}
                </option>
              ))}
          </select>
          <label className="flex items-center gap-2 text-xs text-slate-500">
            Deadline (optional)
            <input
              type="date"
              value={taskDeadline}
              onChange={(e) => setTaskDeadline(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1 text-sm"
            />
            <button
              disabled={addTask.isPending}
              className="ml-auto rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {addTask.isPending ? "Adding…" : "Add"}
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
          <h2 className="font-semibold">Add dependency</h2>
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
          <select
            value={succ}
            onChange={(e) => setSucc(Number(e.target.value))}
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="">Successor…</option>
            {(tasks.data ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <div className="flex gap-2">
            <select
              value={depType}
              onChange={(e) => setDepType(e.target.value as DependencyType)}
              className="rounded border border-slate-300 px-3 py-2 text-sm"
              title="FS: predecessor finishes before successor starts (default) · SS: both start together · FF: both finish together · SF: predecessor finishes when successor starts"
            >
              <option value="FS">Finish → start</option>
              <option value="SS">Start → start</option>
              <option value="FF">Finish → finish</option>
              <option value="SF">Start → finish</option>
            </select>
            <label className="flex items-center gap-1.5 text-xs text-slate-500">
              lag (days)
              <input
                type="number"
                value={depLag}
                onChange={(e) => setDepLag(Number(e.target.value))}
                className="w-16 rounded border border-slate-300 px-2 py-2 text-sm"
              />
            </label>
            <button
              disabled={addDependency.isPending}
              className="ml-auto rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {addDependency.isPending ? "Linking…" : "Link"}
            </button>
          </div>

          {(gantt.data?.links.length ?? 0) > 0 && (
            <div className="border-t border-slate-100 pt-2">
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                Existing dependencies
              </h3>
              <ul className="max-h-40 space-y-1 overflow-y-auto">
                {gantt.data!.links.map((l) => (
                  <li key={l.id} className="flex items-center gap-1.5 text-xs text-slate-600">
                    <span className="min-w-0 flex-1 truncate">
                      {labelFor(l.source)} → {labelFor(l.target)}
                      <span className="ml-1 text-slate-400">
                        ({l.type}
                        {l.lag ? `, +${l.lag}d` : ""})
                      </span>
                    </span>
                    <button
                      type="button"
                      onClick={() => deleteDependency.mutate(l.id)}
                      disabled={deleteDependency.isPending}
                      className="shrink-0 text-slate-400 hover:text-red-600 disabled:opacity-50"
                    >
                      remove
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </form>
      </div>
      )}

      {mayWriteProject && activeTab === "gantt" && (
        <HolidaysEditor projectId={id} mayWrite={mayWriteProject} onChanged={replanAfterEdit} />
      )}

      {selectedTaskId !== null && (
        <TaskDetailPanel
          taskId={selectedTaskId}
          projectId={id}
          mayPlan={mayPlan}
          mayContribute={mayContribute}
          onClose={() => setSelectedTaskId(null)}
          onStructuralChange={replanAfterEdit}
        />
      )}
    </div>
  );
}
