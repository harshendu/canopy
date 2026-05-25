import { useState } from "react";

import { useAuth } from "../lib/auth";
import { useSession } from "../lib/useSession";

/** Thin strip across the top of every page while an admin is impersonating another user, with a
 *  one-click exit back to the admin's own account. */
export default function ImpersonationBanner() {
  const { data: session } = useSession();
  const { stopImpersonating } = useAuth();
  const [busy, setBusy] = useState(false);

  const impersonator = session?.impersonator;
  if (!impersonator) return null;
  const target = session.user;

  return (
    <div className="flex items-center justify-center gap-3 bg-amber-500 px-4 py-1.5 text-xs font-medium text-white">
      <span>
        Viewing as <strong>{target.full_name || target.email}</strong> — impersonated by{" "}
        {impersonator.full_name || impersonator.email}
      </span>
      <button
        onClick={async () => {
          setBusy(true);
          try {
            await stopImpersonating();
          } finally {
            setBusy(false);
          }
        }}
        disabled={busy}
        className="rounded bg-amber-700/40 px-2 py-0.5 font-semibold hover:bg-amber-700/60 disabled:opacity-60"
      >
        {busy ? "Exiting…" : `Back to ${impersonator.full_name || impersonator.email}`}
      </button>
    </div>
  );
}
