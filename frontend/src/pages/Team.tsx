import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { CapacityResponse, Engineer, Role, User } from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";
import { isPlanner } from "../lib/permissions";
import AvailabilityEditor from "../components/AvailabilityEditor";
import CapacityHeatmap from "../components/CapacityHeatmap";

export default function Team() {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const mayWrite = isPlanner(me?.role);
  const [engName, setEngName] = useState("");
  const [engTitle, setEngTitle] = useState("");
  const [engGithub, setEngGithub] = useState("");
  const [engTz, setEngTz] = useState("");
  const [engHours, setEngHours] = useState("");
  const [engSkills, setEngSkills] = useState("");
  const [roleName, setRoleName] = useState("");

  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });
  const roles = useQuery({
    queryKey: ["roles"],
    queryFn: () => api.get<Role[]>("/team/roles"),
  });
  // Org-wide: capacity summed across every project, so cross-project overload shows.
  const capacity = useQuery({
    queryKey: ["capacity", "org"],
    queryFn: () => api.get<CapacityResponse>("/team/capacity"),
  });
  // Only admins can list users; fail quietly so the link control just hides for others.
  const users = useQuery({
    queryKey: ["users"],
    queryFn: () => api.get<User[]>("/auth/users"),
    retry: false,
  });

  const skillsToArray = (s: string) =>
    s.split(",").map((x) => x.trim()).filter(Boolean);

  const addEngineer = useMutation({
    mutationFn: () =>
      api.post("/team/engineers", {
        name: engName,
        title: engTitle || null,
        github_login: engGithub || null,
        timezone: engTz || null,
        committed_hours_per_week: engHours ? Number(engHours) : null,
        skill_tags: skillsToArray(engSkills),
      }),
    onSuccess: () => {
      setEngName("");
      setEngTitle("");
      setEngGithub("");
      setEngTz("");
      setEngHours("");
      setEngSkills("");
      qc.invalidateQueries({ queryKey: ["engineers"] });
    },
  });
  const removeEngineer = useMutation({
    mutationFn: (id: number) => api.del(`/team/engineers/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["engineers"] }),
  });
  const linkUser = useMutation({
    mutationFn: (vars: { id: number; userId: number | null }) =>
      api.patch(`/team/engineers/${vars.id}`, { user_id: vars.userId }),
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
  const userList = users.data ?? [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Team</h1>

      {mayWrite && (
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (engName) addEngineer.mutate();
          }}
          className="space-y-2 rounded-lg border border-slate-200 bg-white p-4"
        >
          <h2 className="font-semibold">Add engineer</h2>
          <div className="flex gap-2">
            <input
              value={engName}
              onChange={(e) => setEngName(e.target.value)}
              placeholder="Name"
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <input
              value={engTitle}
              onChange={(e) => setEngTitle(e.target.value)}
              placeholder="Title"
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div className="flex gap-2">
            <input
              value={engGithub}
              onChange={(e) => setEngGithub(e.target.value)}
              placeholder="GitHub login"
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <input
              value={engTz}
              onChange={(e) => setEngTz(e.target.value)}
              placeholder="Timezone (e.g. UTC+1)"
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <input
              value={engHours}
              onChange={(e) => setEngHours(e.target.value)}
              type="number"
              min={0}
              placeholder="h/wk"
              className="w-20 rounded border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div className="flex gap-2">
            <input
              value={engSkills}
              onChange={(e) => setEngSkills(e.target.value)}
              placeholder="Skills (comma-separated)"
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
      )}

      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {(engineers.data ?? []).map((e) => (
          <li key={e.id} className="flex flex-wrap items-center gap-2 px-4 py-3">
            <span className="font-medium">{e.name}</span>
            {e.title && <span className="text-sm text-slate-400">{e.title}</span>}
            {e.github_login && <span className="text-xs text-slate-400">@{e.github_login}</span>}
            {roleName_(e.role_id) && (
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                {roleName_(e.role_id)}
              </span>
            )}
            {e.skill_tags.map((t) => (
              <span key={t} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                {t}
              </span>
            ))}
            {e.committed_hours_per_week != null && (
              <span className="text-xs text-slate-400">{e.committed_hours_per_week}h/wk</span>
            )}
            <div className="ml-auto flex items-center gap-2">
              {userList.length > 0 && (
                <select
                  value={e.user_id ?? ""}
                  onChange={(ev) =>
                    linkUser.mutate({
                      id: e.id,
                      userId: ev.target.value ? Number(ev.target.value) : null,
                    })
                  }
                  className="rounded border border-slate-300 px-2 py-1 text-xs"
                  title="Link to a login"
                >
                  <option value="">no login</option>
                  {userList.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.email}
                    </option>
                  ))}
                </select>
              )}
              {mayWrite && (
                <button
                  onClick={() => removeEngineer.mutate(e.id)}
                  className="text-xs text-slate-400 hover:text-red-600"
                >
                  remove
                </button>
              )}
            </div>
          </li>
        ))}
        {engineers.data?.length === 0 && (
          <li className="px-4 py-6 text-center text-sm text-slate-400">No engineers yet.</li>
        )}
      </ul>

      {mayWrite && (
        <section className="space-y-2">
          <div>
            <h2 className="font-semibold">Availability</h2>
            <p className="text-xs text-slate-500">
              PTO / leave / ramp-up windows. A reduced capacity factor lowers the
              over-allocation ceiling on the heatmap (factor 0 = fully out).
            </p>
          </div>
          <AvailabilityEditor />
        </section>
      )}

      <section className="space-y-2">
        <div>
          <h2 className="font-semibold">Capacity across all projects</h2>
          <p className="text-xs text-slate-500">
            Each engineer's allocation summed across every project, per ISO week. Cells over 100%
            (red) are over-allocated — including overload that is hidden inside any single project.
          </p>
        </div>
        {capacity.data ? (
          <CapacityHeatmap
            data={capacity.data}
            emptyHint="No allocations yet — allocate engineers on a project's Capacity tab to see org-wide load."
          />
        ) : (
          <p className="text-sm text-slate-500">Loading capacity…</p>
        )}
      </section>
    </div>
  );
}
