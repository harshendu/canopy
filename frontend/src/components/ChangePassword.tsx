import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { api } from "../api/client";

/** Self-service password rotation (sidebar): POST /auth/me/password with the current one. */
export default function ChangePassword() {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [done, setDone] = useState(false);

  const change = useMutation({
    mutationFn: () =>
      api.post("/auth/me/password", { current_password: current, new_password: next }),
    onSuccess: () => {
      setCurrent("");
      setNext("");
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
        className="text-xs text-slate-400 hover:text-slate-600"
      >
        Change password
      </button>
    );
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (current && next) change.mutate();
      }}
      className="w-full space-y-1.5 rounded border border-slate-200 bg-slate-50 p-2"
    >
      <div className="text-xs font-medium text-slate-500">Change password</div>
      <input
        type="password"
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
        placeholder="Current password"
        autoComplete="current-password"
        className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
      />
      <input
        type="password"
        value={next}
        onChange={(e) => setNext(e.target.value)}
        placeholder="New password (min 8 chars)"
        autoComplete="new-password"
        minLength={8}
        className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
      />
      {change.isError && (
        <p className="text-[11px] text-red-600">{(change.error as Error).message}</p>
      )}
      {done && <p className="text-[11px] text-canopy-700">Password updated.</p>}
      <div className="flex gap-2">
        <button
          disabled={change.isPending || !current || next.length < 8}
          className="rounded bg-canopy-500 px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
        >
          Save
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="text-xs text-slate-400 hover:text-slate-600"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
