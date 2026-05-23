import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Engineer, Role } from "../api/types";

export default function Team() {
  const qc = useQueryClient();
  const [engName, setEngName] = useState("");
  const [engTitle, setEngTitle] = useState("");
  const [roleName, setRoleName] = useState("");

  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });
  const roles = useQuery({
    queryKey: ["roles"],
    queryFn: () => api.get<Role[]>("/team/roles"),
  });

  const addEngineer = useMutation({
    mutationFn: () => api.post("/team/engineers", { name: engName, title: engTitle || null }),
    onSuccess: () => {
      setEngName("");
      setEngTitle("");
      qc.invalidateQueries({ queryKey: ["engineers"] });
    },
  });
  const removeEngineer = useMutation({
    mutationFn: (id: number) => api.del(`/team/engineers/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["engineers"] }),
  });
  const addRole = useMutation({
    mutationFn: () => api.post("/team/roles", { name: roleName }),
    onSuccess: () => {
      setRoleName("");
      qc.invalidateQueries({ queryKey: ["roles"] });
    },
  });

  const roleName_ = (id: number | null) =>
    id == null ? "" : (roles.data ?? []).find((r) => r.id === id)?.name ?? "";

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Team</h1>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (engName) addEngineer.mutate();
          }}
          className="space-y-2 rounded-lg border border-slate-200 bg-white p-4"
        >
          <h2 className="font-semibold">Add engineer</h2>
          <input
            value={engName}
            onChange={(e) => setEngName(e.target.value)}
            placeholder="Name"
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <div className="flex gap-2">
            <input
              value={engTitle}
              onChange={(e) => setEngTitle(e.target.value)}
              placeholder="Title (optional)"
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
              Add
            </button>
          </div>
        </form>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (roleName) addRole.mutate();
          }}
          className="space-y-2 rounded-lg border border-slate-200 bg-white p-4"
        >
          <h2 className="font-semibold">Add role</h2>
          <div className="flex gap-2">
            <input
              value={roleName}
              onChange={(e) => setRoleName(e.target.value)}
              placeholder="e.g. Backend, SRE"
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
              Add
            </button>
          </div>
          <div className="flex flex-wrap gap-1 pt-1">
            {(roles.data ?? []).map((r) => (
              <span key={r.id} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                {r.name}
              </span>
            ))}
          </div>
        </form>
      </div>

      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {(engineers.data ?? []).map((e) => (
          <li key={e.id} className="flex items-center justify-between px-4 py-3">
            <span>
              <span className="font-medium">{e.name}</span>
              {e.title && <span className="ml-2 text-sm text-slate-400">{e.title}</span>}
              {roleName_(e.role_id) && (
                <span className="ml-2 rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                  {roleName_(e.role_id)}
                </span>
              )}
            </span>
            <button
              onClick={() => removeEngineer.mutate(e.id)}
              className="text-xs text-slate-400 hover:text-red-600"
            >
              remove
            </button>
          </li>
        ))}
        {engineers.data?.length === 0 && (
          <li className="px-4 py-6 text-center text-sm text-slate-400">No engineers yet.</li>
        )}
      </ul>
    </div>
  );
}
