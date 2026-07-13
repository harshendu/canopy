import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Blocker, BlockerSeverity, Engineer } from "../api/types";

const SEVERITY_RANK: Record<BlockerSeverity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};
const SEVERITY_TONE: Record<BlockerSeverity, string> = {
  critical: "bg-red-100 text-red-700",
  high: "bg-orange-100 text-orange-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-slate-100 text-slate-600",
};

/**
 * A manager-facing queue of open blockers — the leading "work has stalled" signal (§D0), which was
 * otherwise only raisable/visible on the engineer's own /me. Sorted worst-severity then
 * soonest-needed-by, resolvable in place. `projectId` omitted = org-wide (every project's tasks).
 */
export default function BlockerQueue({
  projectId,
  engineers,
}: {
  projectId?: number;
  engineers: Engineer[];
}) {
  const qc = useQueryClient();
  const key = projectId ?? "org";
  const blockers = useQuery({
    queryKey: ["blockers", key],
    queryFn: () =>
      api.get<Blocker[]>(
        `/blockers?open_only=true${projectId ? `&project_id=${projectId}` : ""}`,
      ),
  });
  const resolve = useMutation({
    mutationFn: (id: number) => api.patch(`/blockers/${id}`, { resolved: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["blockers", key] }),
  });

  const nameFor = useMemo(() => {
    const m = new Map(engineers.map((e) => [e.id, e.name]));
    return (id: number | null) => (id != null ? m.get(id) : undefined);
  }, [engineers]);

  const rows = useMemo(() => {
    const list = [...(blockers.data ?? [])];
    return list.sort((a, b) => {
      const sr =
        SEVERITY_RANK[a.severity ?? "low"] - SEVERITY_RANK[b.severity ?? "low"];
      if (sr !== 0) return sr;
      return (a.needed_by ?? "9999").localeCompare(b.needed_by ?? "9999");
    });
  }, [blockers.data]);

  if (blockers.isLoading) return <p className="text-sm text-slate-400">Loading blockers…</p>;
  if (rows.length === 0) {
    return (
      <p className="flex items-center gap-1.5 text-sm text-slate-500">
        <span className="h-2 w-2 rounded-full bg-emerald-500" />
        No open blockers.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-slate-100">
      {rows.map((b) => (
        <li key={b.id} className="flex items-start gap-3 py-2 text-sm">
          <span
            className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-xs font-medium ${
              SEVERITY_TONE[b.severity ?? "low"]
            }`}
          >
            {b.severity ?? "—"}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-slate-700">{b.reason}</span>
            <span className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-slate-400">
              {b.category && <span>{b.category}</span>}
              {nameFor(b.owner_engineer_id) && <span>owner: {nameFor(b.owner_engineer_id)}</span>}
              {b.needed_by && <span className="text-amber-600">needed by {b.needed_by}</span>}
            </span>
          </span>
          <button
            onClick={() => resolve.mutate(b.id)}
            disabled={resolve.isPending}
            className="shrink-0 text-xs text-slate-400 hover:text-emerald-700 disabled:opacity-50"
          >
            resolve
          </button>
        </li>
      ))}
    </ul>
  );
}
