import { Link } from "react-router-dom";

import { PageHeader } from "./PageHeader";
import { Icon } from "./icons";

/**
 * First-run guide (NAV-01). A fresh install is otherwise a wall of empty forms with no stated
 * order — and the installing admin's persona defaults to `engineering`, landing them on an empty
 * `/me` that says "ask an admin to link you" (to themselves). This shows the actual path instead.
 * Rendered only when there are no projects AND no engineers yet.
 */
export function GetStarted({ canManage }: { canManage: boolean }) {
  const steps = [
    {
      to: "/projects",
      title: "Create your first project",
      body: "A project is the unit you plan and schedule. Give it a key (e.g. PLATFORM) and a name.",
      icon: "projects" as const,
    },
    {
      to: "/team",
      title: "Add your team",
      body: "Add engineers (skills, timezone, committed hours) and link each to their login so their work shows up on /me.",
      icon: "team" as const,
    },
    {
      to: "/connectors",
      title: "Connect Jira, GitHub & Drive",
      body: "Sync epics/stories from Jira, read PRs from GitHub, and link design docs from Drive. Canopy reads these — Jira stays the source of truth for status.",
      icon: "connectors" as const,
    },
    {
      to: "/projects",
      title: "Break down & schedule the work",
      body: "In a project's Schedule tab, add tasks and dependencies, then run CPM to compute the critical path and dates.",
      icon: "gantt" as const,
    },
  ];

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader
        title="Welcome to canopy"
        subtitle="Let’s get your first project on the board. These four steps set up planning, your team, and your integrations."
      />
      {!canManage && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          This workspace is still empty. An admin or architect needs to create the first project and
          team before there’s anything to see here.
        </p>
      )}
      <ol className="space-y-3">
        {steps.map((s, i) => (
          <li key={s.title}>
            <Link
              to={s.to}
              className="flex items-start gap-4 rounded-xl border border-slate-200 bg-white p-4 transition hover:border-emerald-300 hover:shadow-sm"
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-sm font-bold text-emerald-800">
                {i + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 font-semibold text-slate-800">
                  <Icon name={s.icon} size={16} />
                  {s.title}
                </span>
                <span className="mt-0.5 block text-sm text-slate-500">{s.body}</span>
              </span>
              <span className="self-center text-slate-300">→</span>
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}
