import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { CapacityResponse, Engineer } from "../api/types";
import CapacityHeatmap from "./CapacityHeatmap";

export default function CapacityView({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const [engineerId, setEngineerId] = useState<number | "">("");
  const [percent, setPercent] = useState(100);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const capacity = useQuery({
    queryKey: ["capacity", projectId],
    queryFn: () => api.get<CapacityResponse>(`/team/capacity?project_id=${projectId}`),
  });
  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });

  const allocate = useMutation({
    mutationFn: () =>
      api.post("/team/allocations", {
        engineer_id: engineerId,
        project_id: projectId,
        percent_allocation: percent,
        start_date: start || null,
        end_date: end || null,
      }),
    onSuccess: () => {
      setEngineerId("");
      qc.invalidateQueries({ queryKey: ["capacity", projectId] });
    },
  });

  return (
    <div className="space-y-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (engineerId) allocate.mutate();
        }}
        className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-4"
      >
        <span className="text-sm font-medium text-slate-600">Allocate</span>
        <select
          value={engineerId}
          onChange={(e) => setEngineerId(e.target.value ? Number(e.target.value) : "")}
          className="rounded border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="">Engineer…</option>
          {(engineers.data ?? []).map((eng) => (
            <option key={eng.id} value={eng.id}>
              {eng.name}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1 text-sm text-slate-500">
          <input
            type="number"
            min={0}
            max={200}
            value={percent}
            onChange={(e) => setPercent(Number(e.target.value))}
            className="w-20 rounded border border-slate-300 px-2 py-2 text-sm"
          />
          %
        </label>
        <input
          type="date"
          value={start}
          onChange={(e) => setStart(e.target.value)}
          className="rounded border border-slate-300 px-2 py-2 text-sm"
        />
        <span className="text-slate-400">→</span>
        <input
          type="date"
          value={end}
          onChange={(e) => setEnd(e.target.value)}
          className="rounded border border-slate-300 px-2 py-2 text-sm"
        />
        <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
          Add
        </button>
      </form>

      {capacity.data ? (
        <CapacityHeatmap data={capacity.data} />
      ) : (
        <p className="text-sm text-slate-500">Loading capacity…</p>
      )}
    </div>
  );
}
