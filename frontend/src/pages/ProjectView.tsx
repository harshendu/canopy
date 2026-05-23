import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { GanttResponse, Project, ReplanResult, Task, TaskType } from "../api/types";
import GanttChart from "../components/GanttChart";

export default function ProjectView() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const qc = useQueryClient();

  const [taskName, setTaskName] = useState("");
  const [taskDuration, setTaskDuration] = useState(3);
  const [taskType, setTaskType] = useState<TaskType>("task");
  const [pred, setPred] = useState<number | "">("");
  const [succ, setSucc] = useState<number | "">("");
  const [lastReplan, setLastReplan] = useState<ReplanResult | null>(null);

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
      }),
    onSuccess: () => {
      setTaskName("");
      invalidate();
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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">
          {project.data ? project.data.name : "Project"}
        </h1>
        <button
          onClick={() => replan.mutate()}
          disabled={replan.isPending}
          className="rounded bg-canopy-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {replan.isPending ? "Scheduling…" : "Schedule (CPM)"}
        </button>
      </div>

      {lastReplan && (
        <div className="rounded border border-canopy-500/30 bg-canopy-50 px-4 py-2 text-sm text-canopy-700">
          Scheduled {lastReplan.scheduled_tasks} tasks · critical path:{" "}
          {lastReplan.critical_path.join(" → ") || "none"} · ends{" "}
          {lastReplan.project_end ?? "—"}
        </div>
      )}

      {gantt.data && gantt.data.tasks.length > 0 ? (
        <GanttChart data={gantt.data} />
      ) : (
        <p className="text-sm text-slate-500">
          No tasks yet — add tasks below, then run “Schedule (CPM)”.
        </p>
      )}

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
            <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
              Add
            </button>
          </div>
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
    </div>
  );
}
