import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Availability, Engineer } from "../api/types";

/** Manage engineer availability (PTO / leave / ramp-up). Each window scales the engineer's
 *  over-allocation ceiling on the capacity views (factor 0 = fully out, 0.5 = half). */
export default function AvailabilityEditor() {
  const qc = useQueryClient();
  const [engineerId, setEngineerId] = useState<number | "">("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [factor, setFactor] = useState(0);
  const [note, setNote] = useState("");

  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });
  const availability = useQuery({
    queryKey: ["availability"],
    queryFn: () => api.get<Availability[]>("/team/availability"),
  });
  const names = new Map((engineers.data ?? []).map((e) => [e.id, e.name]));

  const reset = () => {
    setEngineerId("");
    setStart("");
    setEnd("");
    setFactor(0);
    setNote("");
    qc.invalidateQueries({ queryKey: ["availability"] });
    qc.invalidateQueries({ queryKey: ["capacity"] });
  };

  const add = useMutation({
    mutationFn: () =>
      api.post("/team/availability", {
        engineer_id: engineerId,
        start_date: start,
        end_date: end,
        capacity_factor: factor,
        note: note || null,
      }),
    onSuccess: reset,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/team/availability/${id}`),
    onSuccess: reset,
  });

  return (
    <div className="space-y-3">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (engineerId && start && end) add.mutate();
        }}
        className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-4"
      >
        <span className="text-sm font-medium text-slate-600">Availability</span>
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
        <label className="flex items-center gap-1 text-sm text-slate-500">
          capacity
          <input
            type="number"
            min={0}
            max={1}
            step={0.25}
            value={factor}
            onChange={(e) => setFactor(Number(e.target.value))}
            className="w-20 rounded border border-slate-300 px-2 py-2 text-sm"
          />
        </label>
        <input
          type="text"
          placeholder="note (PTO, ramp-up…)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="grow rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
          Add
        </button>
      </form>

      {(availability.data ?? []).length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white text-sm">
          {(availability.data ?? []).map((a) => (
            <li key={a.id} className="flex items-center justify-between px-4 py-2">
              <span>
                <span className="font-medium">{names.get(a.engineer_id) ?? `#${a.engineer_id}`}</span>{" "}
                <span className="text-slate-500">
                  {a.start_date} → {a.end_date} · {Math.round(a.capacity_factor * 100)}% capacity
                </span>
                {a.note && <span className="text-slate-400"> · {a.note}</span>}
              </span>
              <button
                onClick={() => remove.mutate(a.id)}
                className="text-xs text-slate-400 hover:text-red-600"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
