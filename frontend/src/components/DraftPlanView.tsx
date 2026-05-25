import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  Connection,
  DraftPlan,
  DraftPlanDetail,
  DraftPushResult,
  TaskType,
} from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";
import { isPlanner } from "../lib/permissions";

function typeLabel(type: TaskType): string {
  if (type === "summary") return "epic";
  if (type === "milestone") return "milestone";
  return "story";
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "synced"
      ? "bg-canopy-100 text-canopy-700"
      : status === "archived"
        ? "bg-slate-100 text-slate-500"
        : "bg-amber-100 text-amber-700";
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${tone}`}>{status}</span>;
}

export default function DraftPlanView({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const mayPlan = isPlanner(me?.role);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("");

  const plans = useQuery({
    queryKey: ["draft-plans", projectId],
    queryFn: () => api.get<DraftPlan[]>(`/projects/${projectId}/draft-plans`),
  });

  const createPlan = useMutation({
    mutationFn: () =>
      api.post<DraftPlan>(`/projects/${projectId}/draft-plans`, {
        title,
        source: source || null,
      }),
    onSuccess: (plan) => {
      setTitle("");
      setSource("");
      qc.invalidateQueries({ queryKey: ["draft-plans", projectId] });
      setSelectedId(plan.id);
    },
  });

  const planList = plans.data ?? [];

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="font-semibold">Plan drafts → Jira</h2>
        <p className="mt-1 text-sm text-slate-500">
          Stage a proposed plan here and review it, then create the Jira tickets from it. canopy
          writes ticket <strong>content</strong> (summary / description / story points) — never
          status. After pushing, run a Jira sync to pull the new issues back in as tasks.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          {planList.length === 0 && (
            <p className="text-sm text-slate-500">No drafts yet — create one to start planning.</p>
          )}
          <ul className="space-y-2">
            {planList.map((p) => (
              <li key={p.id}>
                <button
                  onClick={() => setSelectedId(selectedId === p.id ? null : p.id)}
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
                  <DraftPlanDetailPanel planId={p.id} projectId={projectId} mayPlan={mayPlan} />
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
}: {
  planId: number;
  projectId: number;
  mayPlan: boolean;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [type, setType] = useState<TaskType>("task");
  const [estimate, setEstimate] = useState(1);
  const [points, setPoints] = useState<number | "">("");
  const [parentId, setParentId] = useState<number | "">("");
  const [connId, setConnId] = useState<number | "">("");
  const [pushResult, setPushResult] = useState<DraftPushResult | null>(null);
  const [pushError, setPushError] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["draft-plan", planId],
    queryFn: () => api.get<DraftPlanDetail>(`/draft-plans/${planId}`),
  });
  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<Connection[]>(`/connectors/connections`),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["draft-plan", planId] });
    qc.invalidateQueries({ queryKey: ["draft-plans", projectId] });
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

  const jiraConns = (connections.data ?? []).filter(
    (c) => c.provider === "jira" && c.active && Number(c.config.project_id) === projectId,
  );
  const resolvedConnId = connId === "" && jiraConns.length === 1 ? jiraConns[0].id : connId;
  const resolvedConn = jiraConns.find((c) => c.id === resolvedConnId);
  // The direct push path is only available when the provider's writes are `direct`. Under
  // `mcp`/`disabled`, canopy refuses (Claude creates the tickets and records them back instead).
  const writeDirect = resolvedConn?.write_strategy === "direct";
  const canPush = mayPlan && jiraConns.length > 0 && resolvedConnId !== "" && writeDirect;

  const push = useMutation({
    mutationFn: () =>
      api.post<DraftPushResult>(`/draft-plans/${planId}/push-to-jira`, {
        connection_id: resolvedConnId === "" ? null : resolvedConnId,
      }),
    onSuccess: (res) => {
      setPushResult(res);
      setPushError(null);
      invalidate();
    },
    onError: (e: Error) => setPushError(e.message),
  });

  if (!detail.data) return <div className="mt-1 text-xs text-slate-400">Loading…</div>;
  const tasks = detail.data.tasks;
  const summaries = tasks.filter((t) => t.type === "summary");

  return (
    <div className="mt-1 space-y-3 rounded-lg border border-canopy-200 bg-white p-3 text-sm">
      {detail.data.description && <p className="text-slate-600">{detail.data.description}</p>}

      <ul className="space-y-1">
        {tasks.length === 0 && <li className="text-xs text-slate-400">No tasks yet.</li>}
        {tasks.map((t) => (
          <li key={t.id} className="flex items-center gap-2">
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
            {t.jira_key && (
              <span className="rounded bg-canopy-100 px-1.5 py-0.5 text-xs text-canopy-700">
                {t.jira_key}
              </span>
            )}
            {mayPlan && (
              <button
                onClick={() => delTask.mutate(t.id)}
                className="ml-auto text-xs text-red-500 hover:text-red-700"
              >
                remove
              </button>
            )}
          </li>
        ))}
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
            {jiraConns.length > 1 && (
              <select
                value={connId}
                onChange={(e) => setConnId(e.target.value === "" ? "" : Number(e.target.value))}
                className="rounded border border-slate-300 px-2 py-1 text-sm"
              >
                <option value="">Pick a Jira connection…</option>
                {jiraConns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            )}
            <button
              onClick={() => push.mutate()}
              disabled={!canPush || push.isPending}
              className="rounded bg-canopy-700 px-3 py-1 text-sm font-medium text-white disabled:opacity-50"
            >
              {push.isPending
                ? "Pushing…"
                : detail.data.status === "synced"
                  ? "Update Jira tickets"
                  : "Create Jira tickets"}
            </button>
            {jiraConns.length === 0 && (
              <span className="text-xs text-slate-400">
                No Jira connection is configured for this project.
              </span>
            )}
            {jiraConns.length > 0 && resolvedConnId !== "" && !writeDirect && (
              <span className="text-xs text-amber-700">
                Jira writes are {resolvedConn?.write_strategy}-managed — create the tickets via
                Claude, then record them back (canopy won't push directly).
              </span>
            )}
          </div>
          {pushError && <p className="text-xs text-red-600">Push failed: {pushError}</p>}
          {pushResult && (
            <div className="space-y-1 text-xs">
              <div className="text-slate-600">
                {pushResult.created} created · {pushResult.updated} updated · {pushResult.failed}{" "}
                failed
              </div>
              <ul className="space-y-0.5">
                {pushResult.results.map((r) => (
                  <li
                    key={r.draft_task_id}
                    className={r.action === "failed" ? "text-red-600" : "text-slate-500"}
                  >
                    {r.name}: {r.action}
                    {r.jira_key ? ` (${r.jira_key})` : ""}
                    {r.error ? ` — ${r.error}` : ""}
                  </li>
                ))}
              </ul>
              {pushResult.failed === 0 && (
                <p className="text-slate-400">
                  Now run a Jira sync (Connectors) to pull these in as canopy tasks.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
