import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { ADR, MySprint, MyWorkspace as Workspace } from "../api/types";
import { STATUS_LABELS } from "../lib/decisions";
import { roleLabel } from "../lib/roles";
import { functionLabel } from "../lib/persona";
import { formatSprintDates, localToday, timeLeftLabel } from "../lib/sprints";
import { featureOn, useFeatures } from "../lib/useFeatures";
import { PageHeader } from "../components/PageHeader";
import { PreviewLink } from "../components/PreviewLink";
import { Icon } from "../components/icons";
import MyDocs from "../components/MyDocs";

const adrLabel = (n: number) => `ADR-${String(n).padStart(4, "0")}`;

function DecisionList({ title, decisions }: { title: string; decisions: ADR[] }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="mb-2 font-semibold">{title}</h2>
      {decisions.length === 0 ? (
        <p className="text-sm text-slate-400">Nothing here.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {decisions.map((a) => (
            <li key={a.id}>
              <PreviewLink
                target={{ kind: "project", id: a.project_id, tab: "decisions" }}
                className="flex items-center gap-2 rounded px-2 py-1 hover:bg-slate-50"
              >
                <span className="font-mono text-xs text-slate-400">{adrLabel(a.number)}</span>
                <span className="truncate">{a.title}</span>
                <span className="ml-auto shrink-0 text-xs text-slate-400">
                  {STATUS_LABELS[a.status]}
                </span>
              </PreviewLink>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** "My sprint": each active sprint I have work in — its dates, time left and progress — with
 *  my tasks in it, each linking to its project's board (USER_FLOWS §C11). */
function MySprints({ sprints }: { sprints: MySprint[] }) {
  const today = localToday();
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="mb-2 font-semibold">My sprint</h2>
      <div className="space-y-4">
        {sprints.map(({ sprint, tasks }) => {
          const left = timeLeftLabel(sprint, today);
          const mineDone = tasks.filter((t) => t.status_category === "done").length;
          const pct = sprint.task_count ? Math.round((sprint.done_count / sprint.task_count) * 100) : 0;
          return (
            <section key={sprint.id} aria-label={sprint.name} className="space-y-1.5">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm">
                <span className="font-medium text-slate-800">{sprint.name}</span>
                <span className="text-xs text-slate-500">
                  {formatSprintDates(sprint)}
                  {left && <> · {left}</>}
                </span>
                <span className="ml-auto text-xs text-slate-500">
                  {sprint.done_count}/{sprint.task_count} done · yours {mineDone}/{tasks.length}
                </span>
              </div>
              <div
                role="progressbar"
                aria-label={`${sprint.name} progress`}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={pct}
                className="h-1.5 overflow-hidden rounded-full bg-slate-100"
              >
                <div className="h-full rounded-full bg-canopy-500" style={{ width: `${pct}%` }} />
              </div>
              {sprint.goal && <p className="text-xs text-slate-500">Goal: {sprint.goal}</p>}
              <ul className="space-y-1 text-sm">
                {tasks.map((t) => (
                  <li key={t.id}>
                    <PreviewLink
                      target={{ kind: "project", id: t.project_id, tab: "board" }}
                      className="flex items-center gap-2 rounded px-2 py-1 hover:bg-slate-50"
                    >
                      {t.key && <span className="font-mono text-xs text-slate-400">{t.key}</span>}
                      <span
                        className={`truncate ${t.status_category === "done" ? "text-slate-400 line-through" : ""}`}
                      >
                        {t.name}
                      </span>
                      <span className="ml-auto shrink-0 text-xs text-slate-400">
                        {t.status ?? "no status"}
                      </span>
                    </PreviewLink>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}

export default function MyWorkspace() {
  const qc = useQueryClient();
  const features = useFeatures();
  const [blockTask, setBlockTask] = useState<number | "">("");
  const [blockReason, setBlockReason] = useState("");
  const { data, isLoading } = useQuery({
    queryKey: ["my-workspace"],
    queryFn: () => api.get<Workspace>("/me/workspace"),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["my-workspace"] });
  const raiseBlocker = useMutation({
    mutationFn: (vars: { taskId: number; reason: string }) =>
      api.post(`/tasks/${vars.taskId}/blockers`, { reason: vars.reason }),
    onSuccess: () => {
      setBlockTask("");
      setBlockReason("");
      invalidate();
    },
  });
  const resolveBlocker = useMutation({
    mutationFn: (id: number) => api.patch(`/blockers/${id}`, { resolved: true }),
    onSuccess: invalidate,
  });

  if (isLoading || !data) {
    return <p className="text-sm text-slate-500">Loading your workspace…</p>;
  }
  const { user, engineer, assigned_tasks, blockers } = data;
  const taskName = (id: number) =>
    assigned_tasks.find((t) => t.id === id)?.name ?? `task #${id}`;

  return (
    <div className="space-y-6">
      <PageHeader
        title={user.full_name || user.email}
        actions={
          <Link
            to="/me/today"
            className="inline-flex items-center gap-1 rounded border border-slate-300 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
          >
            Today
            <Icon name="arrow-right" size={15} />
          </Link>
        }
        subtitle={
          <div className="flex flex-wrap items-center gap-2 text-sm text-slate-500">
          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">{roleLabel(user.role)}</span>
          <span className="rounded bg-canopy-50 px-2 py-0.5 text-xs text-canopy-700">
            {functionLabel(user.function)}
          </span>
          {engineer ? (
            <>
              {engineer.github_login && <span>@{engineer.github_login}</span>}
              {engineer.timezone && <span>· {engineer.timezone}</span>}
              {engineer.committed_hours_per_week != null && (
                <span>· {engineer.committed_hours_per_week}h/wk committed</span>
              )}
              {engineer.skill_tags.length > 0 && (
                <span className="flex flex-wrap gap-1">
                  {engineer.skill_tags.map((t) => (
                    <span key={t} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">
                      {t}
                    </span>
                  ))}
                </span>
              )}
            </>
          ) : (
            <span className="text-amber-600">
              No engineer profile linked to your account — ask an admin to link one on the Team
              page so your assigned work shows up here.
            </span>
          )}
          </div>
        }
      />

      {featureOn(features, "tracking.sprints") && data.my_sprints.length > 0 && (
        <MySprints sprints={data.my_sprints} />
      )}

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-2 font-semibold">My tasks</h2>
        {assigned_tasks.length === 0 ? (
          <p className="text-sm text-slate-400">No open tasks assigned to you.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {assigned_tasks.map((t) => (
              <li key={t.id}>
                <PreviewLink
                  target={{ kind: "project", id: t.project_id }}
                  className="flex items-center gap-2 rounded px-2 py-1 hover:bg-slate-50"
                >
                  {t.is_critical && (
                    <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-700">
                      critical
                    </span>
                  )}
                  <span className="truncate">{t.name}</span>
                  <span className="ml-auto shrink-0 text-xs text-slate-400">
                    {t.end ? `due ${t.end}` : "unscheduled"}
                  </span>
                </PreviewLink>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-2 font-semibold">
          Blockers <span className="text-xs font-normal text-slate-400">(impediments to clear)</span>
        </h2>
        {blockers.length === 0 ? (
          <p className="text-sm text-slate-400">Nothing blocked. Flag an impediment below.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {blockers.map((b) => (
              <li
                key={b.id}
                className="flex items-center gap-2 rounded border border-amber-200 bg-amber-50 px-2 py-1"
              >
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-700">
                  blocked
                </span>
                <span className="truncate">
                  <span className="text-slate-500">{taskName(b.task_id)}:</span> {b.reason}
                </span>
                <button
                  onClick={() => resolveBlocker.mutate(b.id)}
                  className="ml-auto shrink-0 text-xs text-canopy-700 hover:underline"
                >
                  resolve
                </button>
              </li>
            ))}
          </ul>
        )}
        {assigned_tasks.length > 0 && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (blockTask && blockReason.trim())
                raiseBlocker.mutate({ taskId: Number(blockTask), reason: blockReason });
            }}
            className="mt-3 flex flex-wrap items-center gap-2"
          >
            <select
              value={blockTask}
              onChange={(e) => setBlockTask(e.target.value ? Number(e.target.value) : "")}
              className="rounded border border-slate-300 px-2 py-1 text-sm"
            >
              <option value="">Flag a blocker on…</option>
              {assigned_tasks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            <input
              value={blockReason}
              onChange={(e) => setBlockReason(e.target.value)}
              placeholder="What's blocking it?"
              className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
            />
            <button className="rounded bg-amber-500 px-3 py-1 text-sm font-medium text-white">
              Flag
            </button>
          </form>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <DecisionList title="Decisions I own" decisions={data.owned_decisions} />
        <DecisionList title="Decisions to review" decisions={data.stakeholder_decisions} />
      </div>

      {featureOn(features, "governance.docs") && <MyDocs />}
    </div>
  );
}
