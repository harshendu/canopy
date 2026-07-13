import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import type { GanttTask, ReplanResult } from "../api/types";

/** Whole-day index since epoch (UTC) — matches GanttChart's date math for a stable day delta. */
function parseDay(s: string): number {
  const [y, m, d] = s.split("-").map(Number);
  return Math.floor(Date.UTC(y, m - 1, d) / 86_400_000);
}

/**
 * A non-persisting scheduling sandbox: override a few task durations and see the projected finish,
 * critical-path size, and deadline hits without touching the live plan. Backed by
 * `POST /projects/{id}/whatif` (computed, never saved). Meaningful now that replan no longer
 * ratchets end dates (BUG-05), so the projection is a clean function of the overrides.
 */
export default function WhatIfPanel({
  projectId,
  tasks,
  currentEnd,
}: {
  projectId: number;
  tasks: GanttTask[];
  currentEnd: string | null;
}) {
  // Only leaf work tasks carry a duration the scheduler will honor (summaries/milestones don't).
  const leaves = useMemo(
    () => tasks.filter((t) => t.type !== "summary" && t.type !== "milestone"),
    [tasks],
  );
  const durationOf = useMemo(
    () => new Map(leaves.map((t) => [t.id, t.duration] as const)),
    [leaves],
  );
  const nameOf = useMemo(() => new Map(leaves.map((t) => [t.id, t.text] as const)), [leaves]);

  const [pick, setPick] = useState<number | "">("");
  const [dur, setDur] = useState(1);
  const [overrides, setOverrides] = useState<Map<number, number>>(new Map());
  const [result, setResult] = useState<ReplanResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const project = useMutation({
    mutationFn: (o: Map<number, number>) =>
      api.post<ReplanResult>(`/projects/${projectId}/whatif`, {
        duration_overrides: Object.fromEntries(o),
      }),
    onSuccess: (res) => {
      setResult(res);
      setError(null);
    },
    onError: (e) =>
      setError(e instanceof ApiError ? e.message : "Couldn’t project the scenario."),
  });

  const addOverride = () => {
    if (pick === "") return;
    setOverrides((prev) => new Map(prev).set(pick, dur));
    setResult(null); // overrides changed — the shown projection is now stale
  };
  const removeOverride = (id: number) => {
    setOverrides((prev) => {
      const next = new Map(prev);
      next.delete(id);
      return next;
    });
    setResult(null);
  };
  const reset = () => {
    setOverrides(new Map());
    setResult(null);
    setError(null);
  };

  if (leaves.length === 0) return null;

  const endDelta =
    result?.project_end && currentEnd
      ? parseDay(result.project_end) - parseDay(currentEnd)
      : null;

  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center gap-2">
        <h2 className="font-semibold">What-if</h2>
        <span className="text-xs text-slate-400">
          Try duration changes — projected only, the live plan is never touched
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-slate-500">
          Task
          <select
            value={pick}
            onChange={(e) => {
              const v = e.target.value === "" ? "" : Number(e.target.value);
              setPick(v);
              if (v !== "") setDur(durationOf.get(v) ?? 1);
            }}
            className="w-56 rounded border border-slate-300 px-2 py-1.5 text-sm text-slate-700"
          >
            <option value="">Select a task…</option>
            {leaves.map((t) => (
              <option key={t.id} value={t.id}>
                {t.text} ({t.duration}d)
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-500">
          New duration (days)
          <input
            type="number"
            min={0}
            value={dur}
            onChange={(e) => setDur(Math.max(0, Number(e.target.value)))}
            className="w-28 rounded border border-slate-300 px-2 py-1.5 text-sm text-slate-700"
          />
        </label>
        <button
          onClick={addOverride}
          disabled={pick === ""}
          className="rounded border border-canopy-500 px-3 py-1.5 text-sm font-medium text-canopy-700 disabled:opacity-40"
        >
          Add override
        </button>
      </div>

      {overrides.size > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {[...overrides.entries()].map(([id, d]) => (
            <span
              key={id}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600"
            >
              <span className="font-medium">{nameOf.get(id) ?? `#${id}`}</span>
              <span className="tabular-nums text-slate-400">
                {durationOf.get(id)}d → {d}d
              </span>
              <button
                onClick={() => removeOverride(id)}
                className="text-slate-400 hover:text-slate-700"
                aria-label="Remove override"
              >
                ✕
              </button>
            </span>
          ))}
          <button onClick={reset} className="ml-1 text-xs text-slate-400 hover:text-slate-600">
            clear all
          </button>
        </div>
      )}

      <div className="mt-3 flex items-center gap-3">
        <button
          onClick={() => project.mutate(overrides)}
          disabled={overrides.size === 0 || project.isPending}
          className="rounded bg-canopy-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {project.isPending ? "Projecting…" : "Project"}
        </button>
        {error && <span className="text-sm text-red-600">⚠ {error}</span>}
      </div>

      {result && (
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <div className="rounded-lg border border-slate-200 p-3">
            <div className="text-[11px] uppercase tracking-wide text-slate-400">Projected end</div>
            <div className="mt-0.5 text-lg font-bold tabular-nums">
              {result.project_end ?? "—"}
            </div>
          </div>
          <div className="rounded-lg border border-slate-200 p-3">
            <div className="text-[11px] uppercase tracking-wide text-slate-400">
              Δ vs current
            </div>
            <div
              className={`mt-0.5 text-lg font-bold tabular-nums ${
                endDelta == null
                  ? ""
                  : endDelta > 0
                    ? "text-red-600"
                    : endDelta < 0
                      ? "text-canopy-700"
                      : "text-slate-500"
              }`}
            >
              {endDelta == null
                ? "—"
                : endDelta === 0
                  ? "no change"
                  : endDelta > 0
                    ? `+${endDelta}d`
                    : `${endDelta}d`}
            </div>
          </div>
          <div className="rounded-lg border border-slate-200 p-3">
            <div className="text-[11px] uppercase tracking-wide text-slate-400">
              Critical tasks
            </div>
            <div className="mt-0.5 text-lg font-bold tabular-nums">
              {result.critical_path.length}
            </div>
          </div>
          <div className="rounded-lg border border-slate-200 p-3">
            <div className="text-[11px] uppercase tracking-wide text-slate-400">
              Deadline misses
            </div>
            <div
              className={`mt-0.5 text-lg font-bold tabular-nums ${
                result.deadline_violations.length > 0 ? "text-red-600" : "text-slate-500"
              }`}
            >
              {result.deadline_violations.length}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
