import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { MyToday as Today, MyWorkspace, Proposal } from "../api/types";
import { STATUS_LABELS } from "../lib/decisions";
import { featureOn, useFeatures } from "../lib/useFeatures";
import { PageHeader } from "../components/PageHeader";
import { PreviewLink } from "../components/PreviewLink";

const adrLabel = (n: number) => `ADR-${String(n).padStart(4, "0")}`;

export default function MyToday() {
  const qc = useQueryClient();
  const features = useFeatures();
  const proposalsOn = featureOn(features, "ai.proposals");

  const { data, isLoading } = useQuery({
    queryKey: ["my-today"],
    queryFn: () => api.get<Today>("/me/today"),
  });
  // Blockers are the other time-sensitive daily signal — reuse the workspace payload (§M).
  const workspace = useQuery({
    queryKey: ["my-workspace"],
    queryFn: () => api.get<MyWorkspace>("/me/workspace"),
  });
  const reviews = useQuery({
    queryKey: ["proposals", "open"],
    queryFn: () => api.get<Proposal[]>("/proposals?status=open"),
    enabled: proposalsOn,
  });
  const resolveBlocker = useMutation({
    mutationFn: (id: number) => api.patch(`/blockers/${id}`, { resolved: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["my-workspace"] }),
  });

  if (isLoading || !data) {
    return <p className="text-sm text-slate-500">Loading…</p>;
  }
  const blockers = workspace.data?.blockers ?? [];
  const reviewCount = reviews.data?.length ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Today"
        breadcrumbs={[{ label: "My work", to: "/me" }, { label: "Today" }]}
        subtitle="Your daily focus: pressing work, blockers to clear, decisions to push, and anything awaiting your review."
      />

      {proposalsOn && reviewCount > 0 && (
        <Link
          to="/reviews"
          className="flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 hover:bg-amber-100"
        >
          <span className="rounded-full bg-amber-500 px-1.5 text-xs font-semibold text-white">
            {reviewCount}
          </span>
          staged change {reviewCount === 1 ? "proposal" : "proposals"} await your review
        </Link>
      )}

      {blockers.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 font-semibold">Blockers on your work</h2>
          <ul className="divide-y divide-slate-100 text-sm">
            {blockers.map((b) => (
              <li key={b.id} className="flex items-start gap-3 py-2">
                {b.severity && (
                  <span
                    className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-xs font-medium ${
                      b.severity === "critical" || b.severity === "high"
                        ? "bg-red-100 text-red-700"
                        : "bg-amber-100 text-amber-700"
                    }`}
                  >
                    {b.severity}
                  </span>
                )}
                <span className="min-w-0 flex-1">
                  <span className="block text-slate-700">{b.reason}</span>
                  {b.needed_by && (
                    <span className="text-xs text-amber-600">needed by {b.needed_by}</span>
                  )}
                </span>
                <button
                  onClick={() => resolveBlocker.mutate(b.id)}
                  disabled={resolveBlocker.isPending}
                  className="shrink-0 text-xs text-slate-400 hover:text-emerald-700 disabled:opacity-50"
                >
                  resolve
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-2 font-semibold">Focus — critical or due soon</h2>
        {data.focus_tasks.length === 0 ? (
          <p className="text-sm text-slate-400">Nothing pressing today.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {data.focus_tasks.map((t) => (
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
        <h2 className="mb-2 font-semibold">Decisions to push</h2>
        {data.decisions_to_push.length === 0 ? (
          <p className="text-sm text-slate-400">No decisions waiting on you.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {data.decisions_to_push.map((a) => (
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
    </div>
  );
}
