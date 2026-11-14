import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  Blocker,
  BlockerCategory,
  BlockerSeverity,
  DocSource,
  Engineer,
  Sprint,
  Task,
  TaskExternalLinks,
  TeamDelivery,
  WorkflowRead,
} from "../api/types";
import {
  CANOPY_OWNER,
  boardQueryKey,
  canMove,
  fold,
  trackerName,
  trackingFailure,
  viewerForRole,
  workflowPath,
  workflowQueryKey,
} from "../lib/board";
import { spreadConfidence, spreadTone } from "../lib/estimates";
import { canContribute, isPlanner } from "../lib/permissions";
import { invalidateSprintData } from "../lib/sprintCache";
import { STATE_LABELS, formatSprintDates, liveSprints, usesSprints } from "../lib/sprints";
import { useCurrentUser } from "../lib/useCurrentUser";
import { featureOn, useFeatures } from "../lib/useFeatures";
import { useMoveCard } from "../lib/useMoveCard";
import { useProjectTeam } from "../lib/useProjectTeam";
import { Icon } from "./icons";
import RiskRegister from "./RiskRegister";
import TagEditor from "./TagEditor";

const DOC_SOURCE_LABEL: Record<DocSource, string> = {
  jira_epic: "Jira",
  manual: "manual",
  repo: "GitHub",
  drive: "Drive",
};

const numOrNull = (s: string): number | null => (s.trim() === "" ? null : Number(s));

/** A right-side drawer to view/edit a task's delivery metadata: progress, 3-point estimate,
 *  tags, blockers, and the task-scoped risk register. Opened from the Gantt / Board. */
export default function TaskDetailPanel({
  taskId,
  projectId,
  mayPlan,
  mayContribute,
  onClose,
  onStructuralChange,
}: {
  taskId: number;
  projectId: number;
  mayPlan: boolean;
  mayContribute: boolean;
  onClose: () => void;
  /** Called after a save that changed a scheduling input (duration) — lets the parent re-run CPM. */
  onStructuralChange?: () => void;
}) {
  const qc = useQueryClient();
  const task = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.get<Task>(`/tasks/${taskId}`),
  });
  const features = useFeatures();

  const deleteTask = useMutation({
    mutationFn: () => api.del(`/tasks/${taskId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks", projectId] });
      qc.invalidateQueries({ queryKey: ["gantt", projectId] });
      qc.invalidateQueries({ queryKey: ["board", projectId] });
      onClose();
      // The delete cascades deps/history/etc. server-side; re-plan so the schedule reflects it.
      onStructuralChange?.();
    },
  });
  const handleDelete = () => {
    const name = task.data?.name ?? `task #${taskId}`;
    if (window.confirm(`Delete "${name}"? This also removes its dependencies and history.`)) {
      deleteTask.mutate();
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" onClick={onClose} aria-hidden />
      <aside className="fixed right-0 top-0 z-50 flex h-full w-[440px] max-w-full flex-col overflow-y-auto border-l border-slate-200 bg-white shadow-xl">
        <div className="flex items-start justify-between border-b border-slate-100 p-4">
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-400">
              {task.data?.type ?? "task"}
            </div>
            <h2 className="text-lg font-semibold">{task.data?.name ?? `Task #${taskId}`}</h2>
            {task.data && (
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                {task.data.key && <span className="font-mono text-slate-400">{task.data.key}</span>}
                <TaskStatusField task={task.data} projectId={projectId} mayPlan={mayPlan} />
                {task.data.is_critical ? (
                  <span className="rounded bg-red-100 px-1.5 py-0.5 text-red-700">critical</span>
                ) : (
                  <span>float {task.data.total_float}d</span>
                )}
              </div>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {mayPlan && (
              <button
                onClick={handleDelete}
                disabled={deleteTask.isPending}
                className="text-xs font-medium text-slate-400 hover:text-red-600 disabled:opacity-50"
              >
                {deleteTask.isPending ? "Deleting…" : "Delete"}
              </button>
            )}
            <button onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Close">
              ✕
            </button>
          </div>
        </div>
        {deleteTask.isError && (
          <p role="alert" className="border-b border-red-100 bg-red-50 px-4 py-2 text-sm text-red-700">
            Couldn’t delete: {(deleteTask.error as Error).message}
          </p>
        )}

        <div className="space-y-6 p-4">
          {task.data && <TaskSprintField task={task.data} projectId={projectId} mayPlan={mayPlan} />}
          {task.data && (
            <TaskFields
              task={task.data}
              projectId={projectId}
              canEdit={mayPlan}
              onStructuralChange={onStructuralChange}
            />
          )}

          <section>
            <h3 className="mb-2 text-sm font-semibold text-slate-700">External links</h3>
            <ExternalLinksSection taskId={taskId} />
          </section>

          {featureOn(features, "tracking.blockers") && (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-slate-700">Blockers</h3>
              <BlockerSection taskId={taskId} projectId={projectId} mayContribute={mayContribute} />
            </section>
          )}

          {featureOn(features, "governance.risk") && (
            <section>
              <RiskRegister scope="task" scopeId={taskId} mayWrite={mayPlan} />
            </section>
          )}
        </div>
      </aside>
    </>
  );
}

/** The task's status. A canopy-owned task changes status here through the same move as the
 *  board (`POST /tasks/{id}/move`, guarded by the status it was read with — never a PATCH); a
 *  mirrored task's status belongs to its tracker, so it shows locked with a link out. */
function TaskStatusField({
  task,
  projectId,
  mayPlan,
}: {
  task: Task;
  projectId: number;
  mayPlan: boolean;
}) {
  const features = useFeatures();
  const { data: me } = useCurrentUser();
  const [failure, setFailure] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const source = { kind: "project", id: projectId } as const;
  const canopyOwned = task.status_owner === CANOPY_OWNER;

  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });
  const myEngineerId = me ? (engineers.data?.find((e) => e.user_id === me.id)?.id ?? null) : null;
  const viewer = viewerForRole(
    {
      can_plan: mayPlan,
      engineer_id: myEngineerId,
      native_enabled: featureOn(features, "tracking.native"),
    },
    me ? { planner: isPlanner(me.role), contributor: canContribute(me.role) } : null,
  );
  const editable =
    task.type !== "summary" &&
    canopyOwned &&
    canMove({ movable: true, assignee_engineer_id: task.assignee_engineer_id }, viewer, {
      changesStatus: true,
    });

  const workflow = useQuery({
    queryKey: workflowQueryKey(source),
    queryFn: () => api.get<WorkflowRead>(workflowPath(source)),
    enabled: editable,
  });
  // Shared with the External links section below — the mirrored item's page.
  const links = useQuery({
    queryKey: ["task-links", task.id],
    queryFn: () => api.get<TaskExternalLinks>(`/tasks/${task.id}/links`),
    enabled: !canopyOwned,
  });
  const move = useMoveCard(boardQueryKey(source), {
    onSuccess: (res) =>
      setWarning(
        res.warnings.includes("wip_limit_exceeded")
          ? `“${res.task.status}” is now over its WIP limit.`
          : null,
      ),
    onError: (err) => setFailure(trackingFailure(err).message),
  });

  if (task.type === "summary") return null;

  if (!canopyOwned) {
    const item = links.data?.tracker ?? null;
    const tracker = item?.label ?? trackerName(task.status_owner);
    const url = item?.url;
    return (
      <>
        <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">
          <Icon name="lock" size={11} />
          {task.status ?? "no status"}
        </span>
        <span className="inline-flex items-center gap-1 rounded bg-blue-50 px-1.5 py-0.5 text-blue-700">
          Status owned by {tracker}
          {url && (
            <a href={url} target="_blank" rel="noreferrer" className="font-medium hover:underline">
              · open in {tracker} ↗
            </a>
          )}
        </span>
      </>
    );
  }

  if (!editable) {
    return task.status ? (
      <span className="rounded bg-slate-100 px-1.5 py-0.5">{task.status}</span>
    ) : null;
  }

  const columns = workflow.data?.columns ?? [];
  const current = columns.find((c) => fold(c.name) === fold(task.status ?? ""))?.name;
  return (
    <>
      <label className="inline-flex items-center">
        <span className="sr-only">Status</span>
        <select
          value={current ?? task.status ?? ""}
          disabled={move.isPending || !workflow.data}
          onChange={(e) => {
            setFailure(null);
            setWarning(null);
            move.mutate({
              taskId: task.id,
              projectId,
              to_status: e.target.value,
              expected_status: task.status ?? "",
            });
          }}
          className="rounded border border-slate-300 bg-white px-1.5 py-0.5 text-xs text-slate-700 focus:border-canopy-500 focus:outline-none disabled:opacity-60"
        >
          {!current && (
            <option value={task.status ?? ""} disabled>
              {task.status ? `${task.status} (not a column)` : "No status"}
            </option>
          )}
          {columns.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      {failure && (
        <span role="alert" className="basis-full text-red-700">
          {failure}
        </span>
      )}
      {warning && (
        <span role="status" className="basis-full text-amber-700">
          {warning}
        </span>
      )}
    </>
  );
}

/** The task's sprint, for a team that runs sprints (USER_FLOWS §C11.3). Changing it is a sprint
 *  membership move (`POST /sprints/{id}/tasks`, `DELETE /sprints/{id}/tasks/{task}`) — never a
 *  PATCH; a tracker that owns the membership refuses it (409), and the reason shows here. */
function TaskSprintField({
  task,
  projectId,
  mayPlan,
}: {
  task: Task;
  projectId: number;
  mayPlan: boolean;
}) {
  const qc = useQueryClient();
  const features = useFeatures();
  const { teamId } = useProjectTeam(projectId);
  const delivery = useQuery({
    queryKey: ["team-delivery", teamId],
    queryFn: () => api.get<TeamDelivery>(`/teams/${teamId}/delivery`),
    enabled: teamId != null,
  });
  const on =
    teamId != null &&
    featureOn(features, "tracking.sprints") &&
    usesSprints(delivery.data?.effective_method);
  const sprints = useQuery({
    queryKey: ["sprints", teamId],
    queryFn: () => api.get<Sprint[]>(`/teams/${teamId}/sprints`),
    enabled: on,
  });
  const [error, setError] = useState<string | null>(null);
  const change = useMutation({
    mutationFn: async (target: number | null): Promise<void> => {
      if (target !== null) {
        await api.post(`/sprints/${target}/tasks`, { task_ids: [task.id] });
      } else if (task.sprint_id != null) {
        await api.del(`/sprints/${task.sprint_id}/tasks/${task.id}`);
      }
    },
    onSuccess: () => setError(null),
    onError: (err) => setError(trackingFailure(err).message),
    onSettled: () => (teamId != null ? invalidateSprintData(qc, teamId) : undefined),
  });

  if (!on || task.type === "summary") return null;
  const list = sprints.data ?? [];
  const live = liveSprints(list);
  const current = list.find((s) => s.id === task.sprint_id);
  const label = (s: Sprint) =>
    `${s.name} · ${STATE_LABELS[s.state].toLowerCase()} · ${formatSprintDates(s)}`;

  return (
    <section className="space-y-1">
      <label className="block text-xs text-slate-500">
        Sprint
        {mayPlan ? (
          <select
            value={task.sprint_id ?? ""}
            disabled={change.isPending || !sprints.data}
            onChange={(e) => change.mutate(e.target.value ? Number(e.target.value) : null)}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
          >
            <option value="">Backlog (no sprint)</option>
            {current && !live.includes(current) && (
              <option value={current.id} disabled>
                {label(current)}
              </option>
            )}
            {live.map((s) => (
              <option key={s.id} value={s.id}>
                {label(s)}
              </option>
            ))}
          </select>
        ) : (
          <span className="mt-1 block text-sm text-slate-700">
            {current
              ? label(current)
              : task.sprint_id == null
                ? "Backlog (no sprint)"
                : sprints.data
                  ? `Sprint #${task.sprint_id}`
                  : "Loading…"}
          </span>
        )}
      </label>
      {error && (
        <p role="alert" className="text-xs text-red-700">
          {error}
        </p>
      )}
    </section>
  );
}

function TaskFields({
  task: t,
  projectId,
  canEdit,
  onStructuralChange,
}: {
  task: Task;
  projectId: number;
  canEdit: boolean;
  onStructuralChange?: () => void;
}) {
  const qc = useQueryClient();
  const [progress, setProgress] = useState(String(t.percent_complete));
  const [duration, setDuration] = useState(String(t.duration));
  const [points, setPoints] = useState(t.story_points?.toString() ?? "");
  const [opt, setOpt] = useState(t.estimate_optimistic?.toString() ?? "");
  const [likely, setLikely] = useState(t.estimate_likely?.toString() ?? "");
  const [pess, setPess] = useState(t.estimate_pessimistic?.toString() ?? "");
  const [tags, setTags] = useState<string[]>(t.tags);
  const [assignee, setAssignee] = useState(t.assignee_engineer_id?.toString() ?? "");

  useEffect(() => {
    setProgress(String(t.percent_complete));
    setDuration(String(t.duration));
    setPoints(t.story_points?.toString() ?? "");
    setOpt(t.estimate_optimistic?.toString() ?? "");
    setLikely(t.estimate_likely?.toString() ?? "");
    setPess(t.estimate_pessimistic?.toString() ?? "");
    setTags(t.tags);
    setAssignee(t.assignee_engineer_id?.toString() ?? "");
  }, [t]);

  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });

  const save = useMutation({
    mutationFn: () =>
      api.patch(`/tasks/${t.id}`, {
        // Clamp to the field's valid range — min/max only bind the spinner arrows, not typed input.
        percent_complete: Math.min(100, Math.max(0, Number(progress) || 0)),
        duration: Math.max(0, Number(duration) || 0),
        // Sprint planning size (§C11) — a points team sizes its sprints with it.
        story_points: points.trim() === "" ? null : Math.max(0, Number(points) || 0),
        estimate_optimistic: numOrNull(opt),
        estimate_likely: numOrNull(likely),
        estimate_pessimistic: numOrNull(pess),
        tags,
        assignee_engineer_id: assignee === "" ? null : Number(assignee),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["task", t.id] });
      qc.invalidateQueries({ queryKey: ["tasks", projectId] });
      qc.invalidateQueries({ queryKey: ["gantt", projectId] });
      qc.invalidateQueries({ queryKey: ["board", projectId] });
      qc.invalidateQueries({ queryKey: ["team-board"] });
      // Story points size sprints: the planning view and its capacity.
      qc.invalidateQueries({ queryKey: ["sprint"] });
      // Duration is a CPM input — let the parent re-plan so dates/critical path don't go stale.
      onStructuralChange?.();
    },
  });

  const o = numOrNull(opt);
  const m = numOrNull(likely);
  const p = numOrNull(pess);
  const fullEstimate = o != null && m != null && p != null;
  const confidence = fullEstimate ? spreadConfidence(o, m, p) : null;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
      className="space-y-4"
    >
      <label className="block text-xs text-slate-500">
        Owner
        <select
          value={assignee}
          disabled={!canEdit}
          onChange={(e) => setAssignee(e.target.value)}
          className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
        >
          <option value="">Unassigned</option>
          {(engineers.data ?? [])
            .filter((e) => e.active || e.id === t.assignee_engineer_id)
            .map((e) => (
              <option key={e.id} value={String(e.id)}>
                {e.name}
              </option>
            ))}
        </select>
      </label>

      <div className="grid grid-cols-3 gap-3">
        <label className="text-xs text-slate-500">
          Progress %
          <input
            type="number"
            min={0}
            max={100}
            value={progress}
            disabled={!canEdit}
            onChange={(e) => setProgress(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
          />
        </label>
        <label className="text-xs text-slate-500">
          Duration (days)
          <input
            type="number"
            min={0}
            value={duration}
            disabled={!canEdit}
            onChange={(e) => setDuration(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
          />
        </label>
        <label className="text-xs text-slate-500">
          Story points
          <input
            type="number"
            min={0}
            step="any"
            value={points}
            disabled={!canEdit}
            onChange={(e) => setPoints(e.target.value)}
            placeholder="—"
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
          />
        </label>
      </div>

      <div>
        <div className="mb-1 flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-600">3-point estimate (days)</span>
          <span className="text-xs text-slate-400">advisory — doesn’t move the schedule</span>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {(
            [
              ["aggressive", opt, setOpt],
              ["practical", likely, setLikely],
              ["buffered", pess, setPess],
            ] as [string, string, (v: string) => void][]
          ).map(([label, value, setter]) => (
            <label key={label} className="text-[11px] text-slate-500">
              {label}
              <input
                type="number"
                min={0}
                value={value}
                disabled={!canEdit}
                onChange={(e) => setter(e.target.value)}
                className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
              />
            </label>
          ))}
        </div>
        {fullEstimate && confidence && (
          <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
            <span>
              PERT mean {((o + 4 * m + p) / 6).toFixed(1)}d · spread {p - o}d
            </span>
            <span className={`rounded px-1.5 py-0.5 ${spreadTone(confidence)}`}>{confidence}</span>
          </div>
        )}
      </div>

      <div>
        <span className="mb-1 block text-xs font-semibold text-slate-600">Tags</span>
        <TagEditor tags={tags} onChange={setTags} disabled={!canEdit} />
      </div>

      {save.isError && (
        <p role="alert" className="text-sm text-red-700">
          Couldn’t save: {(save.error as Error).message}
        </p>
      )}
      {canEdit && (
        <button
          type="submit"
          disabled={save.isPending}
          className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Save"}
        </button>
      )}
    </form>
  );
}

/** A task's links out to the systems that own the work: its tracker item, the GitHub PRs
 *  implementing it, and the design docs (GitHub/Drive) scoped to it. Read-only — canopy links,
 *  it never stores the resources (doc CRUD lives on the project Docs tab). */
function ExternalLinksSection({ taskId }: { taskId: number }) {
  const links = useQuery({
    queryKey: ["task-links", taskId],
    queryFn: () => api.get<TaskExternalLinks>(`/tasks/${taskId}/links`),
  });

  const data = links.data;
  if (!data) return <p className="text-xs text-slate-400">Loading…</p>;

  const item = data.tracker;
  const empty = !item && data.pull_requests.length === 0 && data.docs.length === 0;
  if (empty)
    return <p className="text-xs text-slate-400">No linked tracker item, pull requests, or docs.</p>;

  return (
    <div className="space-y-3 text-sm">
      {item && (
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Tracker item
          </div>
          {item.url ? (
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded bg-blue-50 px-2 py-0.5 font-medium text-blue-700 hover:underline"
            >
              {item.label}: {item.key} ↗
            </a>
          ) : (
            <span className="rounded bg-slate-100 px-2 py-0.5 font-medium text-slate-600">
              {item.label}: {item.key}
            </span>
          )}
        </div>
      )}

      {data.pull_requests.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Pull requests
          </div>
          <ul className="space-y-1">
            {data.pull_requests.map((pr) => (
              <li key={pr.id} className="flex items-center gap-2">
                <a
                  href={pr.url ?? undefined}
                  target="_blank"
                  rel="noreferrer"
                  className="truncate text-canopy-700 hover:underline"
                  title={`${pr.repo} #${pr.number}`}
                >
                  #{pr.number} {pr.title}
                </a>
                <span
                  className={`rounded px-1 py-0.5 text-[10px] uppercase ${
                    pr.state === "open"
                      ? "bg-emerald-100 text-emerald-700"
                      : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {pr.state}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.docs.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Documents
          </div>
          <ul className="space-y-1">
            {data.docs.map((d) => (
              <li key={d.id} className="flex items-center gap-2">
                <a
                  href={d.url}
                  target="_blank"
                  rel="noreferrer"
                  className="truncate text-canopy-700 hover:underline"
                  title={d.url}
                >
                  {d.title || d.url}
                </a>
                <span className="rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-500">
                  {DOC_SOURCE_LABEL[d.source]}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

const BLOCKER_CATEGORIES: BlockerCategory[] = [
  "dependency",
  "resource",
  "decision",
  "external",
  "technical",
];
const BLOCKER_SEVERITIES: BlockerSeverity[] = ["low", "medium", "high", "critical"];

function BlockerSection({
  taskId,
  projectId,
  mayContribute,
}: {
  taskId: number;
  projectId: number;
  mayContribute: boolean;
}) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const [category, setCategory] = useState<BlockerCategory | "">("");
  const [severity, setSeverity] = useState<BlockerSeverity | "">("");
  const [neededBy, setNeededBy] = useState("");

  const blockers = useQuery({
    queryKey: ["task-blockers", taskId],
    queryFn: () => api.get<Blocker[]>(`/tasks/${taskId}/blockers`),
  });
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["task-blockers", taskId] });
    qc.invalidateQueries({ queryKey: ["alerts", projectId] });
  };

  const raise = useMutation({
    mutationFn: () =>
      api.post(`/tasks/${taskId}/blockers`, {
        reason,
        category: category || null,
        severity: severity || null,
        needed_by: neededBy || null,
      }),
    onSuccess: () => {
      setReason("");
      setCategory("");
      setSeverity("");
      setNeededBy("");
      invalidate();
    },
  });
  const resolve = useMutation({
    mutationFn: (id: number) => api.patch(`/blockers/${id}`, { resolved: true }),
    onSuccess: invalidate,
  });

  const open = (blockers.data ?? []).filter((b) => b.resolved_at === null);

  return (
    <div className="space-y-2">
      {open.length === 0 ? (
        <p className="text-xs text-slate-400">No open blockers.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {open.map((b) => (
            <li
              key={b.id}
              className="flex items-start justify-between gap-2 rounded bg-amber-50 px-2 py-1"
            >
              <span className="text-slate-700">
                {b.severity && (
                  <span className="mr-1 font-medium uppercase text-amber-700">{b.severity}</span>
                )}
                {b.reason}
                {b.needed_by && <span className="text-xs text-slate-400"> · by {b.needed_by}</span>}
              </span>
              {mayContribute && (
                <button
                  onClick={() => resolve.mutate(b.id)}
                  className="text-xs text-slate-400 hover:text-emerald-600"
                >
                  resolve
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {mayContribute && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (reason.trim()) raise.mutate();
          }}
          className="space-y-2 rounded border border-slate-200 bg-slate-50 p-2"
        >
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Blocker reason"
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <div className="flex flex-wrap gap-2 text-xs">
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as BlockerCategory | "")}
              className="rounded border border-slate-300 px-2 py-1"
            >
              <option value="">category…</option>
              {BLOCKER_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value as BlockerSeverity | "")}
              className="rounded border border-slate-300 px-2 py-1"
            >
              <option value="">severity…</option>
              {BLOCKER_SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <input
              type="date"
              value={neededBy}
              onChange={(e) => setNeededBy(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1"
            />
            <button className="ml-auto rounded bg-amber-500 px-3 py-1 font-medium text-white">
              Flag blocker
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
