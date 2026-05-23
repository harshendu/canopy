import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Initiative } from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";
import { canWriteProjects } from "../lib/permissions";

export default function Initiatives() {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [outcome, setOutcome] = useState("");
  const [target, setTarget] = useState("");
  const { data: me } = useCurrentUser();
  const mayCreate = canWriteProjects(me?.role);

  const { data: initiatives = [], isLoading } = useQuery({
    queryKey: ["initiatives"],
    queryFn: () => api.get<Initiative[]>("/initiatives"),
  });

  const create = useMutation({
    mutationFn: () =>
      api.post<Initiative>("/initiatives", {
        key,
        name,
        outcome_statement: outcome || null,
        target_date: target || null,
      }),
    onSuccess: () => {
      setKey("");
      setName("");
      setOutcome("");
      setTarget("");
      qc.invalidateQueries({ queryKey: ["initiatives"] });
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Initiatives</h1>
        <p className="text-sm text-slate-500">
          A program spanning multiple projects executed concurrently. Open one to roll up health
          across its sub-projects.
        </p>
      </div>

      {mayCreate && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (key && name) create.mutate();
          }}
          className="grid grid-cols-1 gap-2 rounded-lg border border-slate-200 bg-white p-4 md:grid-cols-2"
        >
          <div className="flex gap-2">
            <input
              value={key}
              onChange={(e) => setKey(e.target.value.toUpperCase())}
              placeholder="KEY"
              className="w-36 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Initiative name"
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div className="flex gap-2">
            <input
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
              placeholder="Outcome statement (optional)"
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <input
              type="date"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="rounded border border-slate-300 px-2 py-2 text-sm"
            />
            <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
              Add
            </button>
          </div>
        </form>
      )}

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
          {initiatives.map((i) => (
            <li key={i.id}>
              <Link
                to={`/initiatives/${i.id}`}
                className="flex items-center justify-between px-4 py-3 hover:bg-slate-50"
              >
                <span>
                  <span className="font-mono text-xs text-slate-400">{i.key}</span>{" "}
                  <span className="font-medium">{i.name}</span>
                  {i.outcome_statement && (
                    <span className="ml-2 text-sm text-slate-400">{i.outcome_statement}</span>
                  )}
                </span>
                <span className="text-xs text-slate-400">
                  {i.target_date ? `target ${i.target_date}` : "no target"}
                </span>
              </Link>
            </li>
          ))}
          {initiatives.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-slate-400">
              No initiatives yet — create one above, then link projects to it.
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
