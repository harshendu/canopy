import { lazy, Suspense, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  BurndownResponse,
  GanttResponse,
  Project,
  ReplanResult,
  Task,
  TaskType,
} from "../api/types";
import GanttChart from "../components/GanttChart";
import CapacityView from "../components/CapacityView";
import RoadmapView from "../components/RoadmapView";
import { useCurrentUser } from "../lib/useCurrentUser";
import { canWriteProjects, isPlanner } from "../lib/permissions";

// Heavy (React Flow / Recharts) — code-split.
const DependencyGraph = lazy(() => import("../components/DependencyGraph"));
const ArchitectureView = lazy(() => import("../components/ArchitectureView"));
const DecisionsView = lazy(() => import("../components/DecisionsView"));
const RiskView = lazy(() => import("../components/RiskView"));
const BurndownChart = lazy(() => import("../components/BurndownChart"));

type Tab =
  | "gantt"
  | "deps"
  | "capacity"
  | "decisions"
  | "architecture"
  | "roadmap"
  | "burndown"
  | "risk";

const TABS: Tab[] = [
  "gantt",
  "deps",
  "capacity",
  "decisions",
  "architecture",
  "roadmap",
  "burndown",
  "risk",
];

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
  const [tab, setTab] = useState<Tab>(initialTab);
  const { data: me } = useCurrentUser();
  const mayPlan = isPlanner(me?.role);
  const mayWriteProject = canWriteProjects(me?.role);

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

  const baseline = useMutation({
    mutationFn: () => api.post(`/projects/${id}/baseline`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["gantt", id] }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">
          {project.data ? project.data.name : "Project"}
        </h1>
        <div className="flex items-center gap-3">
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
              <button
                onClick={() => baseline.mutate()}
                disabled={baseline.isPending}
                className="rounded border border-canopy-500 px-4 py-2 text-sm font-medium text-canopy-700 disabled:opacity-50"
              >
                {baseline.isPending ? "Saving…" : "Set baseline"}
              </button>
              <button
                onClick={() => replan.mutate()}
                disabled={replan.isPending}
                className="rounded bg-canopy-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {replan.isPending ? "Scheduling…" : "Schedule (CPM)"}
              </button>
            </>
          )}
        </div>
      </div>

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

      <div className="flex gap-1 border-b border-slate-200">
        {([
          ["gantt", "Gantt"],
          ["deps", "Dependencies"],
          ["capacity", "Capacity"],
          ["decisions", "Decisions"],
          ["architecture", "Architecture"],
          ["roadmap", "Roadmap"],
          ["burndown", "Burndown"],
          ["risk", "Risk"],
        ] as [Tab, string][]).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
              tab === key
                ? "border-canopy-500 text-canopy-700"
                : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "gantt" &&
        (gantt.data && gantt.data.tasks.length > 0 ? (
          <GanttChart data={gantt.data} />
        ) : (
          <p className="text-sm text-slate-500">
            No tasks yet — add tasks below, then run “Schedule (CPM)”.
          </p>
        ))}

      {tab === "deps" &&
        (gantt.data && gantt.data.tasks.length > 0 ? (
          <Suspense fallback={<p className="text-sm text-slate-500">Loading graph…</p>}>
            <DependencyGraph data={gantt.data} />
          </Suspense>
        ) : (
          <p className="text-sm text-slate-500">No tasks to graph yet.</p>
        ))}

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

      {tab === "roadmap" && <RoadmapView projectId={id} />}

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
          <RiskView projectId={id} />
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
    </div>
  );
}
