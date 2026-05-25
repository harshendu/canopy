import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Outcome, OutcomeScope, OutcomeStatus } from "../api/types";

const STATUSES: OutcomeStatus[] = [
  "pending",
  "on_track",
  "at_risk",
  "validated",
  "invalidated",
];

const STATUS_BADGE: Record<OutcomeStatus, string> = {
  pending: "bg-slate-100 text-slate-500",
  on_track: "bg-blue-100 text-blue-700",
  at_risk: "bg-amber-100 text-amber-700",
  validated: "bg-emerald-100 text-emerald-700",
  invalidated: "bg-red-100 text-red-700",
};

function clampPct(ratio: number | null): number {
  if (ratio === null) return 0;
  return Math.max(0, Math.min(100, Math.round(ratio * 100)));
}

/** Outcomes over output: the measurable bet(s) a project / initiative is making — hypothesis +
 *  success metric tracked baseline→target→current with a verdict. */
export default function OutcomesPanel({
  scope,
  scopeId,
  mayWrite,
}: {
  scope: OutcomeScope;
  scopeId: number;
  mayWrite: boolean;
}) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);

  const outcomes = useQuery({
    queryKey: ["outcomes", scope, scopeId],
    queryFn: () => api.get<Outcome[]>(`/outcomes?scope_level=${scope}&scope_id=${scopeId}`),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["outcomes", scope, scopeId] });

  const patch = useMutation({
    mutationFn: (vars: { id: number; body: Partial<Outcome> }) =>
      api.patch(`/outcomes/${vars.id}`, vars.body),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/outcomes/${id}`),
    onSuccess: invalidate,
  });

  const items = outcomes.data ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700">
          Outcomes
          <span className="ml-2 text-xs font-normal text-slate-400">
            outcomes over output — the bet, measured
          </span>
        </h3>
        {mayWrite && (
          <button
            onClick={() => setAdding((v) => !v)}
            className="rounded border border-canopy-500 px-3 py-1 text-xs font-medium text-canopy-700"
          >
            {adding ? "Cancel" : "Add outcome"}
          </button>
        )}
      </div>

      {adding && (
        <AddOutcomeForm
          scope={scope}
          scopeId={scopeId}
          onDone={() => {
            setAdding(false);
            invalidate();
          }}
        />
      )}

      {items.length === 0 ? (
        <p className="text-sm text-slate-500">
          No outcomes yet — what bet is this {scope} making, and how will you know it worked?
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((o) => (
            <li key={o.id} className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{o.statement}</span>
                {mayWrite ? (
                  <select
                    value={o.status}
                    onChange={(e) =>
                      patch.mutate({ id: o.id, body: { status: e.target.value as OutcomeStatus } })
                    }
                    className={`ml-auto rounded px-1.5 py-0.5 text-xs font-medium ${STATUS_BADGE[o.status]}`}
                  >
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span
                    className={`ml-auto rounded px-1.5 py-0.5 text-xs font-medium ${STATUS_BADGE[o.status]}`}
                  >
                    {o.status}
                  </span>
                )}
              </div>
              {o.metric && <p className="text-xs text-slate-500">metric: {o.metric}</p>}
              <div className="mt-1 flex items-center gap-2">
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full bg-emerald-500" style={{ width: `${clampPct(o.progress_ratio)}%` }} />
                </div>
                <span className="text-xs tabular-nums text-slate-500">
                  {o.current_value ?? "—"} / {o.target_value ?? "—"}
                  {o.unit ? ` ${o.unit}` : ""}
                  {o.progress_ratio !== null && ` · ${Math.round(o.progress_ratio * 100)}%`}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                {o.target_date && <span>by {o.target_date}</span>}
                {mayWrite && (
                  <label className="flex items-center gap-1">
                    record current
                    <input
                      type="number"
                      defaultValue={o.current_value ?? ""}
                      onBlur={(e) => {
                        const v = e.target.value;
                        patch.mutate({
                          id: o.id,
                          body: { current_value: v === "" ? null : Number(v) },
                        });
                      }}
                      className="w-20 rounded border border-slate-300 px-1.5 py-0.5"
                    />
                  </label>
                )}
                {mayWrite && (
                  <button
                    onClick={() => remove.mutate(o.id)}
                    className="ml-auto hover:text-red-600"
                  >
                    delete
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AddOutcomeForm({
  scope,
  scopeId,
  onDone,
}: {
  scope: OutcomeScope;
  scopeId: number;
  onDone: () => void;
}) {
  const [statement, setStatement] = useState("");
  const [metric, setMetric] = useState("");
  const [unit, setUnit] = useState("");
  const [baseline, setBaseline] = useState("");
  const [target, setTarget] = useState("");
  const [targetDate, setTargetDate] = useState("");

  const num = (v: string) => (v === "" ? null : Number(v));

  const create = useMutation({
    mutationFn: () =>
      api.post("/outcomes", {
        scope_level: scope,
        scope_id: scopeId,
        statement,
        metric: metric || null,
        unit: unit || null,
        baseline_value: num(baseline),
        target_value: num(target),
        target_date: targetDate || null,
      }),
    onSuccess: onDone,
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (statement.trim()) create.mutate();
      }}
      className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm"
    >
      <input
        value={statement}
        onChange={(e) => setStatement(e.target.value)}
        placeholder="We believe X will yield Y…"
        className="w-full rounded border border-slate-300 px-3 py-2"
      />
      <input
        value={metric}
        onChange={(e) => setMetric(e.target.value)}
        placeholder="Success metric (how we'll know)"
        className="w-full rounded border border-slate-300 px-3 py-2"
      />
      <div className="flex flex-wrap gap-2">
        <input
          type="number"
          value={baseline}
          onChange={(e) => setBaseline(e.target.value)}
          placeholder="baseline"
          className="w-24 rounded border border-slate-300 px-2 py-1"
        />
        <input
          type="number"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="target"
          className="w-24 rounded border border-slate-300 px-2 py-1"
        />
        <input
          value={unit}
          onChange={(e) => setUnit(e.target.value)}
          placeholder="unit"
          className="w-20 rounded border border-slate-300 px-2 py-1"
        />
        <label className="flex items-center gap-1 text-xs text-slate-500">
          by
          <input
            type="date"
            value={targetDate}
            onChange={(e) => setTargetDate(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1"
          />
        </label>
      </div>
      <button
        type="submit"
        disabled={create.isPending}
        className="rounded bg-canopy-500 px-4 py-2 text-xs font-medium text-white disabled:opacity-50"
      >
        {create.isPending ? "Saving…" : "Add outcome"}
      </button>
    </form>
  );
}
