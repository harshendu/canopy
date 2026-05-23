import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { ADR, MyWorkspace as Workspace } from "../api/types";
import { STATUS_LABELS } from "../lib/decisions";
import { roleLabel } from "../lib/roles";

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
  const { data, isLoading } = useQuery({
    queryKey: ["my-workspace"],
    queryFn: () => api.get<Workspace>("/me/workspace"),
  });

  if (isLoading || !data) {
    return <p className="text-sm text-slate-500">Loading your workspace…</p>;
  }
  const { user, engineer, assigned_tasks } = data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{user.full_name || user.email}</h1>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-500">
          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">{roleLabel(user.role)}</span>
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

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <DecisionList title="Decisions I own" decisions={data.owned_decisions} />
        <DecisionList title="Decisions to review" decisions={data.stakeholder_decisions} />
      </div>
    </div>
  );
}
