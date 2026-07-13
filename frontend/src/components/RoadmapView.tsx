import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Milestone } from "../api/types";
import { horizon, type Horizon } from "../lib/horizon";
import { useCurrentUser } from "../lib/useCurrentUser";
import { isPlanner } from "../lib/permissions";

const COLUMNS: { key: Horizon; label: string; hint: string }[] = [
  { key: "now", label: "Now", hint: "≤ 30 days / overdue" },
  { key: "next", label: "Next", hint: "31–90 days" },
  { key: "later", label: "Later", hint: "90+ days / undated" },
];

export default function RoadmapView({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const mayWrite = isPlanner(me?.role); // milestone writes are planner-gated (§A3a)
  const [name, setName] = useState("");
  const [targetDate, setTargetDate] = useState("");

  const { data } = useQuery({
    queryKey: ["milestones", projectId],
    queryFn: () => api.get<Milestone[]>(`/milestones?project_id=${projectId}`),
  });
  const milestones = data ?? [];

  const addMilestone = useMutation({
    mutationFn: () =>
      api.post("/milestones", {
        project_id: projectId,
        name,
        target_date: targetDate || null,
      }),
    onSuccess: () => {
      setName("");
      setTargetDate("");
      qc.invalidateQueries({ queryKey: ["milestones", projectId] });
    },
  });

  return (
    <div className="space-y-4">
      {mayWrite && (
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name) addMilestone.mutate();
        }}
        className="flex gap-2 rounded-lg border border-slate-200 bg-white p-4"
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Milestone name"
          className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <input
          type="date"
          value={targetDate}
          onChange={(e) => setTargetDate(e.target.value)}
          className="rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
          Add milestone
        </button>
      </form>
      )}

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
    </div>
  );
}
