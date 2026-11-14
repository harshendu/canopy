import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import {
  TRACKERS_KEY,
  finalizeDraftPlan,
  getProjectTracking,
  getTrackers,
  trackingKey,
} from "../api/trackers";
import type {
  Connection,
  DraftFinalizeResult,
  DraftPlan,
  DraftPlanDetail,
  Task,
  TaskType,
} from "../api/types";
import { trackingFailure } from "../lib/board";
import {
  finalizeBlocker,
  finalizeConfirm,
  finalizeLabel,
  finalizeModeOf,
  finalizeSplit,
  type FinalizeBlocker,
  type FinalizeMode,
} from "../lib/drafts";
import { isPlanner } from "../lib/permissions";
import { trackingLabel } from "../lib/tracking";
import { useCurrentUser } from "../lib/useCurrentUser";
import { featureOn, useFeatures } from "../lib/useFeatures";

function typeLabel(type: TaskType): string {
  if (type === "summary") return "epic";
  if (type === "milestone") return "milestone";
  return "story";
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "synced"
      ? "bg-canopy-50 text-canopy-700"
      : status === "archived"
        ? "bg-slate-100 text-slate-500"
        : "bg-amber-100 text-amber-700";
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${tone}`}>{status}</span>;
}

/** How finalising works for this project: its mode, the tracker it writes to, what stops it. */
interface FinalizeTarget {
  mode: FinalizeMode;
  trackerLabel: string;
  blocker: FinalizeBlocker | null;
}

/**
 * Draft plans (USER_FLOWS §C10): stage a proposed plan, review it, then finalise it into real
 * work — canopy tasks in a native project, or the bound tracker's tickets (content only, never
 * status) in a mirrored one. The project's tracking mode decides.
 */
export default function DraftPlanView({ projectId, mayPlan: mayPlanProp }: { projectId: number; mayPlan?: boolean }) {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const features = useFeatures();
  const mayPlan = mayPlanProp ?? isPlanner(me?.role);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("");

  const plans = useQuery({
    queryKey: ["draft-plans", projectId],
    queryFn: () => api.get<DraftPlan[]>(`/projects/${projectId}/draft-plans`),
  });
  const tracking = useQuery({ queryKey: trackingKey(projectId), queryFn: () => getProjectTracking(projectId) });
  const catalog = useQuery({ queryKey: TRACKERS_KEY, queryFn: getTrackers, staleTime: 5 * 60 * 1000 });
  const t = tracking.data;
  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<Connection[]>("/connectors/connections"),
    enabled: featureOn(features, "integrations") && t?.mode === "mirrored",
  });

  let target: FinalizeTarget | null = null;
  if (t) {
    const connectionId = t.binding?.connection_id ?? t.legacy_connection_id;
    const connection = (connections.data ?? []).find((c) => c.id === connectionId) ?? null;
    const mode = finalizeModeOf(t);
    const trackerLabel = trackingLabel(t, connection?.provider ?? null, catalog.data) ?? "tracker";
    target = {
      mode,
      trackerLabel,
      blocker: finalizeBlocker({ mode, tracking: t, trackerLabel, capabilities: t.capabilities, connection }),
    };
  }

  const createPlan = useMutation({
    mutationFn: () =>
      api.post<DraftPlan>(`/projects/${projectId}/draft-plans`, {
        title,
        source: source || null,
      }),
    onSuccess: (plan) => {
      setTitle("");
      setSource("");
      void qc.invalidateQueries({ queryKey: ["draft-plans", projectId] });
      setSelectedId(plan.id);
    },
  });

  const planList = plans.data ?? [];

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="font-semibold">Draft plans</h2>
        <p className="mt-1 text-sm text-slate-500">
          {target?.mode === "tracker" ? (
            <>
              Stage a proposed plan here and review it, then create the {target.trackerLabel} tickets from
              it. canopy writes ticket <strong>content</strong> (summary / description / story points) —
              never status — and the next sync pulls the new items back as tasks.
            </>
          ) : (
            <>
              Stage a proposed plan here and review it, then create its tasks. Nothing reaches the board
              or the schedule until you do; finalising again updates the tasks it made.
            </>
          )}
        </p>
        {tracking.isError && (
          <p role="alert" className="mt-2 text-sm text-red-700">
            Couldn’t read how this project is tracked: {trackingFailure(tracking.error).message}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          {plans.data && planList.length === 0 && (
            <p className="text-sm text-slate-500">No drafts yet — create one to start planning.</p>
          )}
          <ul className="space-y-2">
            {planList.map((p) => (
              <li key={p.id}>
                <button
                  onClick={() => setSelectedId(selectedId === p.id ? null : p.id)}
                  aria-expanded={selectedId === p.id}
                  className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${
                    selectedId === p.id
                      ? "border-canopy-500 bg-canopy-50"
                      : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{p.title}</span>
                    <StatusBadge status={p.status} />
                  </div>
                  {p.source && <div className="mt-0.5 text-xs text-slate-400">{p.source}</div>}
                </button>
                {selectedId === p.id && (
                  <DraftPlanDetailPanel
                    planId={p.id}
                    projectId={projectId}
                    mayPlan={mayPlan}
                    target={target}
                  />
                )}
              </li>
            ))}
          </ul>
        </div>

        {mayPlan && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (title.trim()) createPlan.mutate();
            }}
            className="h-fit space-y-2 rounded-lg border border-slate-200 bg-white p-4"
          >
            <h2 className="font-semibold">New draft plan</h2>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Plan title…"
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <input
              value={source}
              onChange={(e) => setSource(e.target.value)}
              placeholder="Source (design doc / PRD url, optional)"
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
              Create draft
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

function DraftPlanDetailPanel({
  planId,
  projectId,
  mayPlan,
  target,
}: {
  planId: number;
  projectId: number;
  mayPlan: boolean;
  target: FinalizeTarget | null;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [type, setType] = useState<TaskType>("task");
  const [estimate, setEstimate] = useState(1);
  const [points, setPoints] = useState<number | "">("");
  const [parentId, setParentId] = useState<number | "">("");
  const [result, setResult] = useState<DraftFinalizeResult | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["draft-plan", planId],
    queryFn: () => api.get<DraftPlanDetail>(`/draft-plans/${planId}`),
  });
  const madeTasks = (detail.data?.tasks ?? []).some((t) => t.task_id != null);
  // The keys of the tasks a native finalise made (same cache as the project's task list).
  const projectTasks = useQuery({
    queryKey: ["tasks", projectId],
    queryFn: () => api.get<Task[]>(`/tasks?project_id=${projectId}`),
    enabled: madeTasks,
  });
  const taskKey = new Map((projectTasks.data ?? []).map((t) => [t.id, t.key] as const));

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["draft-plan", planId] });
    void qc.invalidateQueries({ queryKey: ["draft-plans", projectId] });
  };

  const addTask = useMutation({
    mutationFn: () =>
      api.post(`/draft-plans/${planId}/tasks`, {
        name,
        type,
        estimate_days: estimate,
        story_points: points === "" ? null : points,
        parent_id: parentId === "" ? null : parentId,
      }),
    onSuccess: () => {
      setName("");
      setPoints("");
      setParentId("");
      setType("task");
      setEstimate(1);
      invalidate();
    },
  });

  const delTask = useMutation({
    mutationFn: (id: number) => api.del(`/draft-tasks/${id}`),
    onSuccess: invalidate,
  });

  const finalize = useMutation({
    mutationFn: () => finalizeDraftPlan(planId),
    onSuccess: (res) => {
      setResult(res);
      setFailure(null);
      invalidate();
      if (res.mode === "native") {
        // The tasks joined the plan and the project replanned.
        for (const key of ["tasks", "gantt", "board", "burndown", "tracking"]) {
          void qc.invalidateQueries({ queryKey: [key, projectId] });
        }
      }
    },
    onError: (e) => setFailure(trackingFailure(e).message),
  });

  if (!detail.data) return <div className="mt-1 text-xs text-slate-400">Loading…</div>;
  const plan = detail.data;
  const tasks = plan.tasks;
  const summaries = tasks.filter((t) => t.type === "summary");
  const split = target ? finalizeSplit(tasks, target.mode) : null;
  const label = target && split ? finalizeLabel(target.mode, target.trackerLabel, split) : "Finalise";

  // Pre-flight before the write: what is created and what is updated, stated before it happens
  // (a tracker write is irreversible — §C10.3).
  const confirmFinalize = () => {
    if (!target || !split) return;
    if (window.confirm(finalizeConfirm(plan.title, target.mode, target.trackerLabel, split))) {
      setFailure(null);
      finalize.mutate();
    }
  };

  return (
    <div className="mt-1 space-y-3 rounded-lg border border-canopy-500/30 bg-white p-3 text-sm">
      {plan.description && <p className="text-slate-600">{plan.description}</p>}

      <ul className="space-y-1">
        {tasks.length === 0 && <li className="text-xs text-slate-400">No tasks yet.</li>}
        {tasks.map((t) => {
          const ticket = t.external_key ?? t.jira_key;
          return (
            <li key={t.id} className="flex flex-wrap items-center gap-2">
              <span
                className={
                  t.type === "summary" ? "font-semibold" : t.parent_id != null ? "pl-4" : undefined
                }
              >
                {t.name}
              </span>
              <span className="text-xs text-slate-400">
                {typeLabel(t.type)} · {t.estimate_days}d
                {t.story_points != null ? ` · ${t.story_points} pts` : ""}
              </span>
              {ticket && (
                <span className="rounded bg-canopy-50 px-1.5 py-0.5 text-xs text-canopy-700">{ticket}</span>
              )}
              {t.task_id != null && (
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                  {taskKey.get(t.task_id) ?? `task #${t.task_id}`}
                </span>
              )}
              {mayPlan && (
                <button
                  onClick={() => delTask.mutate(t.id)}
                  className="ml-auto text-xs text-red-600 hover:text-red-800"
                >
                  remove
                </button>
              )}
            </li>
          );
        })}
      </ul>

      {mayPlan && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) addTask.mutate();
          }}
          className="space-y-2 rounded border border-slate-200 p-2"
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Task name…"
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={type}
              onChange={(e) => setType(e.target.value as TaskType)}
              className="rounded border border-slate-300 px-2 py-1 text-sm"
            >
              <option value="task">Story / task</option>
              <option value="summary">Epic / phase</option>
              <option value="milestone">Milestone</option>
            </select>
            <label className="flex items-center gap-1 text-xs text-slate-500">
              est
              <input
                type="number"
                min={0}
                value={estimate}
                onChange={(e) => setEstimate(Number(e.target.value))}
                className="w-16 rounded border border-slate-300 px-2 py-1 text-sm"
              />
              d
            </label>
            <label className="flex items-center gap-1 text-xs text-slate-500">
              pts
              <input
                type="number"
                min={0}
                value={points}
                onChange={(e) => setPoints(e.target.value === "" ? "" : Number(e.target.value))}
                className="w-16 rounded border border-slate-300 px-2 py-1 text-sm"
              />
            </label>
            <select
              value={parentId}
              onChange={(e) => setParentId(e.target.value === "" ? "" : Number(e.target.value))}
              className="rounded border border-slate-300 px-2 py-1 text-sm"
            >
              <option value="">No parent</option>
              {summaries.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            <button className="ml-auto rounded bg-canopy-500 px-3 py-1 text-sm font-medium text-white">
              Add
            </button>
          </div>
        </form>
      )}

      {mayPlan && (
        <div className="space-y-2 rounded border border-slate-200 p-2">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={confirmFinalize}
              disabled={!target || target.blocker !== null || tasks.length === 0 || finalize.isPending}
              className="rounded bg-canopy-700 px-3 py-1 text-sm font-medium text-white disabled:opacity-50"
            >
              {finalize.isPending ? (target?.mode === "tracker" ? "Pushing…" : "Creating…") : label}
            </button>
            {split && tasks.length > 0 && (
              <span className="text-xs text-slate-500">
                {split.creates} new · {split.updates} already {target?.mode === "tracker" ? "in " + target.trackerLabel : "created"}
              </span>
            )}
          </div>
          {target?.blocker && (
            <p className="text-xs text-amber-800">
              {target.blocker.message}{" "}
              {target.blocker.fix === "tracking" && (
                <Link to={`/projects/${projectId}?tab=tracking`} className="font-medium text-canopy-700 hover:underline">
                  Open Tracking
                </Link>
              )}
              {target.blocker.fix === "connectors" && (
                <Link to="/connectors" className="font-medium text-canopy-700 hover:underline">
                  Open Connectors
                </Link>
              )}
            </p>
          )}
          {failure && (
            <p role="alert" className="text-xs text-red-700">
              Couldn’t finalise: {failure}
            </p>
          )}
          {result && (
            <div role="status" className="space-y-1 text-xs">
              <div className="text-slate-600">
                {result.mode === "native" ? "canopy tasks" : `${target?.trackerLabel ?? "Tracker"} tickets`}:{" "}
                {result.created} created · {result.updated} updated · {result.failed} failed
              </div>
              <ul className="space-y-0.5">
                {result.results.map((r) => {
                  const key = r.external_key ?? r.jira_key;
                  return (
                    <li key={r.draft_task_id} className={r.action === "failed" ? "text-red-700" : "text-slate-500"}>
                      {r.name}: {r.action}
                      {key ? ` (${key})` : ""}
                      {r.error ? ` — ${r.error}` : ""}
                    </li>
                  );
                })}
              </ul>
              {result.failed === 0 &&
                (result.mode === "native" ? (
                  <p className="text-slate-500">They’re on the board and the Gantt now.</p>
                ) : (
                  <p className="text-slate-500">
                    The next sync pulls these in as tasks —{" "}
                    <Link to={`/projects/${projectId}?tab=tracking`} className="font-medium text-canopy-700 hover:underline">
                      sync now from Tracking
                    </Link>
                    .
                  </p>
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
