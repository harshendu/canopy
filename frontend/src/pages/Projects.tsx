import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Project } from "../api/types";

export default function Projects() {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [name, setName] = useState("");

  const { data: projects = [], isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<Project[]>("/projects"),
  });

  const create = useMutation({
    mutationFn: () => api.post<Project>("/projects", { key, name }),
    onSuccess: () => {
      setKey("");
      setName("");
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Projects</h1>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (key && name) create.mutate();
        }}
        className="flex gap-2"
      >
        <input
          value={key}
          onChange={(e) => setKey(e.target.value.toUpperCase())}
          placeholder="KEY"
          className="w-28 rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Project name"
          className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
          Add
        </button>
      </form>

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
          {projects.map((p) => (
            <li key={p.id}>
              <Link
                to={`/projects/${p.id}`}
                className="flex items-center justify-between px-4 py-3 hover:bg-slate-50"
              >
                <span>
                  <span className="font-mono text-xs text-slate-400">{p.key}</span>{" "}
                  <span className="font-medium">{p.name}</span>
                </span>
                <span className="text-xs text-slate-400">
                  {p.target_date ? `due ${p.target_date}` : "no target"}
                </span>
              </Link>
            </li>
          ))}
          {projects.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-slate-400">
              No projects yet — create one above.
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
