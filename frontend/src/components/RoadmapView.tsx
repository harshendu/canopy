import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Milestone } from "../api/types";

type Horizon = "now" | "next" | "later";

function horizon(target: string | null): Horizon {
  if (!target) return "later";
  const days = Math.round((new Date(target).getTime() - Date.now()) / 86_400_000);
  if (days <= 30) return "now";
  if (days <= 90) return "next";
  return "later";
}

const COLUMNS: { key: Horizon; label: string; hint: string }[] = [
  { key: "now", label: "Now", hint: "≤ 30 days / overdue" },
  { key: "next", label: "Next", hint: "31–90 days" },
  { key: "later", label: "Later", hint: "90+ days / undated" },
];

export default function RoadmapView({ projectId }: { projectId: number }) {
  const { data } = useQuery({
    queryKey: ["milestones", projectId],
    queryFn: () => api.get<Milestone[]>(`/milestones?project_id=${projectId}`),
  });
  const milestones = data ?? [];

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {COLUMNS.map((col) => {
        const items = milestones.filter((m) => horizon(m.target_date) === col.key);
        return (
          <div key={col.key} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="mb-2 flex items-baseline justify-between">
              <h2 className="font-semibold">{col.label}</h2>
              <span className="text-xs text-slate-400">{col.hint}</span>
            </div>
            <ul className="space-y-2">
              {items.map((m) => (
                <li key={m.id} className="rounded border border-slate-100 px-3 py-2 text-sm">
                  <div className="font-medium">{m.name}</div>
                  <div className="text-xs text-slate-400">
                    {m.target_date ?? "no date"} · {m.status}
                  </div>
                </li>
              ))}
              {items.length === 0 && <li className="text-xs text-slate-300">—</li>}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
