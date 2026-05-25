import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { User } from "../api/types";
import { useAuth } from "../lib/auth";
import { useSession } from "../lib/useSession";
import { roleLabel } from "../lib/roles";

function initials(label: string): string {
  const parts = label
    .replace(/@.*/, "")
    .split(/[.\s_-]+/)
    .filter(Boolean);
  const chars = parts.slice(0, 2).map((p) => p[0]?.toUpperCase() ?? "");
  return chars.join("") || label[0]?.toUpperCase() || "?";
}

/** Current user at the bottom of the left panel. For an admin (incl. the real admin behind an
 *  impersonation) it expands into a switcher over every account — switch to anyone, or back to
 *  yourself. */
export default function UserSwitcher() {
  const { data: session } = useSession();
  const { impersonate } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const user = session?.user;
  // The acting admin is the impersonator when impersonating, else the user themselves.
  const actor = session?.impersonator ?? user;
  const canSwitch = actor?.role === "admin";

  const users = useQuery({
    queryKey: ["switch-targets"],
    queryFn: () => api.get<User[]>("/auth/users"),
    enabled: open && canSwitch,
    staleTime: 60_000,
  });

  if (!user) return null;
  const label = user.full_name || user.email;

  async function switchTo(id: number) {
    setBusy(true);
    try {
      await impersonate(id);
      setOpen(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative border-t border-slate-200 pt-3">
      <button
        type="button"
        onClick={() => canSwitch && setOpen((o) => !o)}
        className={`flex w-full items-center gap-2 rounded px-2 py-2 text-left ${
          canSwitch ? "hover:bg-slate-100" : "cursor-default"
        }`}
        aria-haspopup={canSwitch ? "listbox" : undefined}
        aria-expanded={canSwitch ? open : undefined}
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-canopy-100 text-xs font-semibold text-canopy-700">
          {initials(label)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-slate-700">{label}</span>
          <span className="block truncate text-xs text-slate-400">{roleLabel(user.role)}</span>
        </span>
        {canSwitch && <span className="text-slate-400">⇅</span>}
      </button>

      {open && canSwitch && (
        <div className="absolute bottom-full left-0 z-20 mb-2 max-h-80 w-full overflow-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
          <p className="px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Switch user
          </p>
          {users.isLoading && <p className="px-3 py-2 text-xs text-slate-400">Loading…</p>}
          {users.isError && (
            <p className="px-3 py-2 text-xs text-red-600">Couldn’t load users.</p>
          )}
          {(users.data ?? []).map((u) => {
            const isCurrent = u.id === user.id;
            const isActor = actor != null && u.id === actor.id;
            return (
              <button
                key={u.id}
                type="button"
                disabled={busy || isCurrent || !u.is_active}
                onClick={() => switchTo(u.id)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50 disabled:opacity-60 disabled:hover:bg-transparent"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-slate-700">
                    {u.full_name || u.email}
                    {isActor && " (you)"}
                  </span>
                  <span className="block truncate text-xs text-slate-400">
                    {roleLabel(u.role)}
                    {!u.is_active && " · deactivated"}
                  </span>
                </span>
                {isCurrent && <span className="text-xs text-canopy-600">●</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
