import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { ADR, MyWorkspace as Workspace } from "../api/types";
import { STATUS_LABELS } from "../lib/decisions";
import { roleLabel } from "../lib/roles";
import { functionLabel } from "../lib/persona";

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
              <Link
                to={`/projects/${a.project_id}?tab=decisions`}
                className="flex items-center gap-2 rounded px-2 py-1 hover:bg-slate-50"
              >
                <span className="font-mono text-xs text-slate-400">{adrLabel(a.number)}</span>
                <span className="truncate">{a.title}</span>
                <span className="ml-auto shrink-0 text-xs text-slate-400">
                  {STATUS_LABELS[a.status]}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function MyWorkspace() {
  const qc = useQueryClient();
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
      <div>
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">{user.full_name || user.email}</h1>
          <Link to="/me/today" className="text-sm text-canopy-700 hover:underline">
            Today →
          </Link>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-500">
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
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-2 font-semibold">My tasks</h2>
        {assigned_tasks.length === 0 ? (
          <p className="text-sm text-slate-400">No open tasks assigned to you.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {assigned_tasks.map((t) => (
              <li key={t.id}>
                <Link
                  to={`/projects/${t.project_id}`}
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
                </Link>
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
    </div>
  );
}
