import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Scenario } from "../api/types";
import { isPlanner } from "../lib/permissions";
import { useCurrentUser } from "../lib/useCurrentUser";

export default function ScenarioList() {
  const { initiativeId } = useParams();
  const id = Number(initiativeId);
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const mayPlan = isPlanner(me?.role);
  const [title, setTitle] = useState("");

  const scenarios = useQuery({
    queryKey: ["scenarios", id],
    queryFn: () => api.get<Scenario[]>(`/initiatives/${id}/scenarios`),
  });

  const create = useMutation({
    mutationFn: () => api.post<Scenario>(`/initiatives/${id}/scenarios`, { title }),
    onSuccess: () => {
      setTitle("");
      qc.invalidateQueries({ queryKey: ["scenarios", id] });
    },
  });

  return (
    <div className="space-y-4">
      <div>
        <Link to={`/initiatives/${id}`} className="text-xs text-slate-400 hover:text-slate-600">
          ← Initiative
        </Link>
        <h1 className="text-2xl font-bold">Scenarios</h1>
        <p className="text-sm text-slate-500">
          What-if branches of this initiative — change team, availability, milestones, deadlines,
          and scope, then compare every view before applying.
        </p>
      </div>

      {mayPlan && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim()) create.mutate();
          }}
          className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-4"
        >
          <input
            placeholder="New scenario title…"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="grow rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <button
            disabled={create.isPending}
            className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {create.isPending ? "Snapshotting…" : "New scenario"}
          </button>
        </form>
      )}

      {scenarios.data && scenarios.data.length === 0 ? (
        <p className="text-sm text-slate-500">No scenarios yet.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {(scenarios.data ?? []).map((s) => (
            <li key={s.id}>
              <Link
                to={`/initiatives/${id}/scenarios/${s.id}`}
                className="block rounded-lg border border-slate-200 bg-white p-4 hover:bg-slate-50"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{s.title}</span>
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-medium ${
                      s.status === "applied"
                        ? "bg-canopy-100 text-canopy-700"
                        : "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {s.status}
                  </span>
                </div>
                {s.description && <p className="mt-1 text-sm text-slate-500">{s.description}</p>}
                <p className="mt-1 text-xs text-slate-400">
                  captured {s.base_captured_at.slice(0, 10)}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
