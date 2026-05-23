import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { MyToday as Today } from "../api/types";
import { STATUS_LABELS } from "../lib/decisions";

const adrLabel = (n: number) => `ADR-${String(n).padStart(4, "0")}`;

export default function MyToday() {
  const { data, isLoading } = useQuery({
    queryKey: ["my-today"],
    queryFn: () => api.get<Today>("/me/today"),
  });

  if (isLoading || !data) {
    return <p className="text-sm text-slate-500">Loading…</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Today</h1>
        <Link to="/me" className="text-sm text-canopy-700 hover:underline">
          ← My work
        </Link>
      </div>
      <p className="text-sm text-slate-500">
        Your daily focus: the most-pressing assigned work, and the decisions to push on.
      </p>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-2 font-semibold">Focus — critical or due soon</h2>
        {data.focus_tasks.length === 0 ? (
          <p className="text-sm text-slate-400">Nothing pressing today.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {data.focus_tasks.map((t) => (
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
        <h2 className="mb-2 font-semibold">Decisions to push</h2>
        {data.decisions_to_push.length === 0 ? (
          <p className="text-sm text-slate-400">No decisions waiting on you.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {data.decisions_to_push.map((a) => (
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
    </div>
  );
}
