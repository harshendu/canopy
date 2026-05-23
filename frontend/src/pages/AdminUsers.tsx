import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { User, UserRole } from "../api/types";
import { ASSIGNABLE_ROLES, roleLabel } from "../lib/roles";

export default function AdminUsers() {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<UserRole>("engineer");

  const users = useQuery({
    queryKey: ["users"],
    queryFn: () => api.get<User[]>("/auth/users"),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["users"] });

  const invite = useMutation({
    mutationFn: () =>
      api.post("/auth/register", {
        email,
        password,
        full_name: fullName || null,
        role,
      }),
    onSuccess: () => {
      setEmail("");
      setPassword("");
      setFullName("");
      setRole("engineer");
      invalidate();
    },
  });
  const update = useMutation({
    mutationFn: (vars: { id: number; body: Partial<User> }) =>
      api.patch(`/auth/users/${vars.id}`, vars.body),
    onSuccess: invalidate,
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Users</h1>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (email && password) invite.mutate();
        }}
        className="grid grid-cols-1 gap-2 rounded-lg border border-slate-200 bg-white p-4 md:grid-cols-5"
      >
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          type="email"
          placeholder="Email"
          className="rounded border border-slate-300 px-3 py-2 text-sm md:col-span-2"
        />
        <input
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          placeholder="Full name (optional)"
          className="rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          type="password"
          placeholder="Temp password"
          className="rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <div className="flex gap-2">
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as UserRole)}
            className="flex-1 rounded border border-slate-300 px-2 py-2 text-sm"
          >
            {ASSIGNABLE_ROLES.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </select>
          <button
            disabled={invite.isPending}
            className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Invite
          </button>
        </div>
        {invite.isError && (
          <p className="text-xs text-red-600 md:col-span-5">{(invite.error as Error).message}</p>
        )}
      </form>

      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {(users.data ?? []).map((u) => (
          <li key={u.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
            <span className="font-medium">{u.full_name || u.email}</span>
            {u.full_name && <span className="text-xs text-slate-400">{u.email}</span>}
            {!u.is_active && (
              <span className="rounded bg-slate-200 px-2 py-0.5 text-xs text-slate-500">
                deactivated
              </span>
            )}
            <div className="ml-auto flex items-center gap-2">
              <select
                value={ASSIGNABLE_ROLES.includes(u.role) ? u.role : ""}
                onChange={(e) => update.mutate({ id: u.id, body: { role: e.target.value as UserRole } })}
                className="rounded border border-slate-300 px-2 py-1 text-xs"
              >
                {!ASSIGNABLE_ROLES.includes(u.role) && (
                  <option value="">{roleLabel(u.role)}</option>
                )}
                {ASSIGNABLE_ROLES.map((r) => (
                  <option key={r} value={r}>
                    {roleLabel(r)}
                  </option>
                ))}
              </select>
              <button
                onClick={() => update.mutate({ id: u.id, body: { is_active: !u.is_active } })}
                className="text-xs text-slate-400 hover:text-slate-700"
              >
                {u.is_active ? "deactivate" : "reactivate"}
              </button>
            </div>
          </li>
        ))}
        {users.data?.length === 0 && (
          <li className="px-4 py-6 text-center text-sm text-slate-400">No users.</li>
        )}
      </ul>
    </div>
  );
}
