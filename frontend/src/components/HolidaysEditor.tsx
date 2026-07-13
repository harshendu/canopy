import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Holiday } from "../api/types";

/**
 * The project's working calendar (non-working days, on top of the weekend toggle) — feeds CPM
 * (§C7). Was API-only; project settings are `ArchitectWriter`-gated (admin/architect), so writes
 * here require `mayWrite` from the same gate, not the broader planner set.
 */
export default function HolidaysEditor({
  projectId,
  mayWrite,
  onChanged,
}: {
  projectId: number;
  mayWrite: boolean;
  onChanged?: () => void;
}) {
  const qc = useQueryClient();
  const [day, setDay] = useState("");
  const [name, setName] = useState("");

  const holidays = useQuery({
    queryKey: ["holidays", projectId],
    queryFn: () => api.get<Holiday[]>(`/projects/${projectId}/holidays`),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["holidays", projectId] });
    onChanged?.(); // a holiday shifts the working calendar — CPM dates are now stale
  };

  const add = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/holidays`, { day, name: name || null }),
    onSuccess: () => {
      setDay("");
      setName("");
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/projects/${projectId}/holidays/${id}`),
    onSuccess: invalidate,
  });

  const rows = [...(holidays.data ?? [])].sort((a, b) => a.day.localeCompare(b.day));

  return (
    <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
      <div>
        <h2 className="font-semibold">Holidays</h2>
        <p className="text-xs text-slate-500">
          Non-working days for this project's schedule — on top of the 5-day-week toggle above.
          The scheduler skips these when computing dates.
        </p>
      </div>

      {mayWrite && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (day) add.mutate();
          }}
          className="flex flex-wrap gap-2"
        >
          <input
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            className="rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name (optional)"
            className="min-w-0 flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <button
            disabled={add.isPending}
            className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Add
          </button>
        </form>
      )}
      {add.isError && (
        <p role="alert" className="text-sm text-red-700">
          Couldn’t add: {(add.error as Error).message}
        </p>
      )}

      {holidays.isLoading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-400">No holidays set.</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {rows.map((h) => (
            <li key={h.id} className="flex items-center gap-2 py-1.5 text-sm">
              <span className="font-mono text-xs text-slate-400">{h.day}</span>
              <span className="flex-1 text-slate-700">{h.name || "—"}</span>
              {mayWrite && (
                <button
                  onClick={() => remove.mutate(h.id)}
                  className="text-xs text-slate-400 hover:text-red-600"
                >
                  remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
