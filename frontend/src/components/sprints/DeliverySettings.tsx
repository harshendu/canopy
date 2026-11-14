import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { DeliveryMethod, EstimateUnit, TeamDelivery, TeamDeliveryUpdate } from "../../api/types";
import { trackingFailure } from "../../lib/board";
import { invalidateSprintData } from "../../lib/sprintCache";
import { DELIVERY_METHODS, ESTIMATE_UNITS, METHOD_LABELS } from "../../lib/sprints";

/** How a team runs its work (USER_FLOWS §C11.1): Kanban, sprints or both — for all of its
 *  projects — plus the sprint length and what sprints are sized in. The team's directors and
 *  managers (or an admin) change it; everyone else sees it read-only. */
export default function DeliverySettings({
  teamId,
  delivery,
}: {
  teamId: number;
  delivery: TeamDelivery;
}) {
  const qc = useQueryClient();
  const [method, setMethod] = useState<DeliveryMethod>(delivery.delivery_method);
  const [length, setLength] = useState(String(delivery.sprint_length_days));
  const [unit, setUnit] = useState<EstimateUnit>(delivery.estimate_unit);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const days = Number(length);
  const lengthOk = Number.isInteger(days) && days >= 1 && days <= 90;
  const changes: TeamDeliveryUpdate = {};
  if (method !== delivery.delivery_method) changes.delivery_method = method;
  if (lengthOk && days !== delivery.sprint_length_days) changes.sprint_length_days = days;
  if (unit !== delivery.estimate_unit) changes.estimate_unit = unit;
  const dirty = Object.keys(changes).length > 0;
  const readOnly = !delivery.can_manage;

  const save = useMutation({
    mutationFn: (body: TeamDeliveryUpdate) =>
      api.put<TeamDelivery>(`/teams/${teamId}/delivery`, body),
    onSuccess: (res) => {
      qc.setQueryData(["team-delivery", teamId], res);
      void qc.invalidateQueries({ queryKey: ["teams"] });
      void invalidateSprintData(qc, teamId);
      setSaved(true);
    },
    onError: (err) => setError(trackingFailure(err).message),
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (dirty && lengthOk) {
          setError(null);
          setSaved(false);
          save.mutate(changes);
        }
      }}
      className="max-w-2xl space-y-5 rounded-lg border border-slate-200 bg-white p-5"
    >
      {readOnly && (
        <p className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
          Only the team’s directors and managers (or an admin) can change how the team works.
        </p>
      )}
      {!delivery.sprints_enabled && (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Sprints are turned off in this workspace (feature <code>tracking.sprints</code>), so
          every team works as Kanban for now — whatever is chosen here applies once they are
          turned on.
        </p>
      )}

      <fieldset disabled={readOnly} className="space-y-2">
        <legend className="mb-1 font-semibold text-slate-800">Delivery method</legend>
        <p className="text-sm text-slate-500">
          One choice for every project the team runs. It switches surfaces and metrics on; the
          tasks and their history stay the same. Currently{" "}
          <span className="font-medium text-slate-700">{METHOD_LABELS[delivery.effective_method]}</span>.
        </p>
        {DELIVERY_METHODS.map((m) => (
          <label
            key={m.value}
            className={`flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2 ${
              method === m.value ? "border-canopy-500 bg-canopy-50" : "border-slate-200"
            } ${readOnly ? "cursor-default opacity-80" : ""}`}
          >
            <input
              type="radio"
              name="delivery-method"
              value={m.value}
              checked={method === m.value}
              onChange={() => setMethod(m.value)}
              className="mt-1"
            />
            <span>
              <span className="block text-sm font-medium text-slate-800">{m.label}</span>
              <span className="block text-xs text-slate-500">{m.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <fieldset disabled={readOnly} className="space-y-3">
        <legend className="mb-1 font-semibold text-slate-800">Sprints</legend>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          Sprint length
          <input
            type="number"
            min={1}
            max={90}
            value={length}
            onChange={(e) => setLength(e.target.value)}
            aria-invalid={!lengthOk}
            className="w-20 rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
          />
          days
          {!lengthOk && <span className="text-xs text-red-700">1–90 days</span>}
        </label>
        <div>
          <span className="block text-sm text-slate-600">Size sprints in</span>
          <div className="mt-1 space-y-1">
            {ESTIMATE_UNITS.map((u) => (
              <label key={u.value} className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="estimate-unit"
                  value={u.value}
                  checked={unit === u.value}
                  onChange={() => setUnit(u.value)}
                  className="mt-1"
                />
                <span>
                  <span className="font-medium text-slate-700">{u.label}</span>
                  <span className="text-slate-500"> — {u.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </div>
      </fieldset>

      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}
      {saved && !dirty && !error && (
        <p role="status" className="text-sm text-canopy-700">
          Saved.
        </p>
      )}
      {!readOnly && (
        <button
          type="submit"
          disabled={!dirty || !lengthOk || save.isPending}
          className="rounded bg-canopy-700 px-4 py-2 text-sm font-medium text-white hover:bg-canopy-500 disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Save"}
        </button>
      )}
    </form>
  );
}
