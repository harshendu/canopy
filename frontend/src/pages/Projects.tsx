import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Initiative, Project } from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";
import { canWriteProjects } from "../lib/permissions";
import { PageHeader } from "../components/PageHeader";
import { PreviewLink } from "../components/PreviewLink";

export default function Projects() {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const { data: me } = useCurrentUser();
  const mayCreate = canWriteProjects(me?.role);

  const { data: projects = [], isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<Project[]>("/projects"),
  });
  const { data: initiatives = [] } = useQuery({
    queryKey: ["initiatives"],
    queryFn: () => api.get<Initiative[]>("/initiatives"),
  });

  const setInitiative = useMutation({
    mutationFn: (vars: { projectId: number; initiativeId: number | null }) =>
      api.patch(`/projects/${vars.projectId}`, { initiative_id: vars.initiativeId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
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
      <PageHeader
        title="Projects"
        subtitle="Every project you can see. Open one to plan its schedule, board, and architecture."
      />

      {mayCreate && (
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
      )}

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
          {projects.map((p) => (
            <li
              key={p.id}
              className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-slate-50"
            >
              <PreviewLink target={{ kind: "project", id: p.id }} className="min-w-0 flex-1">
                <span className="font-mono text-xs text-slate-400">{p.key}</span>{" "}
                <span className="font-medium">{p.name}</span>
              </PreviewLink>
              {mayCreate && (
                <select
                  value={p.initiative_id ?? ""}
                  onChange={(e) =>
                    setInitiative.mutate({
                      projectId: p.id,
                      initiativeId: e.target.value ? Number(e.target.value) : null,
                    })
                  }
                  className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600"
                  title="Initiative"
                >
                  <option value="">no initiative</option>
                  {initiatives.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.key}
                    </option>
                  ))}
                </select>
              )}
              <span className="text-xs text-slate-400">
                {p.target_date ? `due ${p.target_date}` : "no target"}
              </span>
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
