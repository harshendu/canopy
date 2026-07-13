import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { User, UserFunction, UserRole } from "../api/types";
import { functionLabel } from "../lib/persona";
import { ASSIGNABLE_ROLES, roleLabel } from "../lib/roles";
import { PageHeader } from "../components/PageHeader";

const FUNCTIONS: UserFunction[] = [
  "engineering",
  "product",
  "design",
  "architecture",
  "management",
  "leadership",
];

/** Per-row password reset: expands into a small inline form (admin types the new temp one). */
function ResetPassword({ userId }: { userId: number }) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const reset = useMutation({
    mutationFn: () => api.post(`/auth/users/${userId}/password`, { new_password: password }),
    onSuccess: () => {
      setPassword("");
      setDone(true);
      setTimeout(() => {
        setDone(false);
        setOpen(false);
      }, 1500);
    },
  });

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-xs text-slate-400 hover:text-slate-700"
      >
        reset password
      </button>
    );
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (password.length >= 8) reset.mutate();
      }}
      className="flex items-center gap-1.5"
    >
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="New temp password"
        autoComplete="new-password"
        minLength={8}
        className="w-40 rounded border border-slate-300 px-2 py-1 text-xs"
      />
      <button
        disabled={reset.isPending || password.length < 8}
        className="rounded bg-canopy-500 px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
      >
        Set
      </button>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="text-xs text-slate-400 hover:text-slate-600"
      >
        cancel
      </button>
      {reset.isError && (
        <span className="text-[11px] text-red-600">{(reset.error as Error).message}</span>
      )}
      {done && <span className="text-[11px] text-canopy-700">set ✓</span>}
    </form>
  );
}

export default function AdminUsers() {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<UserRole>("engineer");
  const [fn, setFn] = useState<UserFunction>("engineering");

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
        function: fn,
      }),
    onSuccess: () => {
      setEmail("");
      setPassword("");
      setFullName("");
      setRole("engineer");
      setFn("engineering");
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
      <PageHeader
        title="Users"
        subtitle="Provision accounts with a temporary password, set their access role (gates writes) and function (sets their landing page), reset passwords, and deactivate leavers."
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (email && password.length >= 8) invite.mutate();
        }}
        className="grid grid-cols-1 gap-2 rounded-lg border border-slate-200 bg-white p-4 md:grid-cols-6"
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
          placeholder="Temp password (min 8)"
          autoComplete="new-password"
          minLength={8}
          className="rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value as UserRole)}
          className="rounded border border-slate-300 px-2 py-2 text-sm"
        >
          {ASSIGNABLE_ROLES.map((r) => (
            <option key={r} value={r}>
              {roleLabel(r)}
            </option>
          ))}
        </select>
        <div className="flex gap-2">
          <select
            value={fn}
            onChange={(e) => setFn(e.target.value as UserFunction)}
            className="flex-1 rounded border border-slate-300 px-2 py-2 text-sm"
          >
            {FUNCTIONS.map((f) => (
              <option key={f} value={f}>
                {functionLabel(f)}
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
          <p className="text-xs text-red-600 md:col-span-6">{(invite.error as Error).message}</p>
        )}
      </form>

      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {(users.data ?? []).map((u) => (
          <li key={u.id} className="space-y-1 px-4 py-3 text-sm">
            <div className="flex flex-wrap items-center gap-3">
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
                  onChange={(e) =>
                    update.mutate({ id: u.id, body: { role: e.target.value as UserRole } })
                  }
                  title="Access role (gates writes)"
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
                <select
                  value={u.function}
                  onChange={(e) =>
                    update.mutate({
                      id: u.id,
                      body: { function: e.target.value as UserFunction },
                    })
                  }
                  title="Cross-functional persona (sets the landing page)"
                  className="rounded border border-slate-300 px-2 py-1 text-xs"
                >
                  {FUNCTIONS.map((f) => (
                    <option key={f} value={f}>
                      {functionLabel(f)}
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
            </div>
            <div className="flex justify-end">
              <ResetPassword userId={u.id} />
            </div>
          </li>
        ))}
        {users.data?.length === 0 && (
          <li className="px-4 py-6 text-center text-sm text-slate-400">No users.</li>
        )}
      </ul>
      {update.isError && (
        <p className="text-xs text-red-600">{(update.error as Error).message}</p>
      )}
    </div>
  );
}
