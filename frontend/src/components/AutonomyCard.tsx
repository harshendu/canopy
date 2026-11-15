import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { AutonomyRead, AutonomySuggestion } from "../api/types";
import { refusalText } from "../lib/execution";
import { FLOOR_LABEL, classEvidenceText } from "../lib/policy";

const KIND = { plan: "plan_approval", handoff: "handoff_approval" } as const;

/**
 * Graduated autonomy (USER_FLOWS §AE6): the change classes people pre-approved at the
 * implementer's checkpoints, and what the evidence suggests adding or removing. People decide;
 * the safety floor always asks a person.
 */
export default function AutonomyCard({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const data = useQuery({
    queryKey: ["autonomy", projectId],
    queryFn: () => api.get<AutonomyRead>(`/projects/${projectId}/autonomy`),
  });
  const change = useMutation({
    mutationFn: (body: { checkpoint: string; change_class: string; action: "add" | "remove" }) =>
      api.post<AutonomyRead>(`/projects/${projectId}/autonomy`, body),
    onSuccess: (next) => {
      qc.setQueryData(["autonomy", projectId], next);
      void qc.invalidateQueries({ queryKey: ["pipeline", projectId] });
    },
  });
  const a = data.data;
  if (!a || !a.stage) return null;
  const apply = (s: AutonomySuggestion) =>
    change.mutate({ checkpoint: s.checkpoint, change_class: s.change_class, action: s.action === "revoke" ? "remove" : "add" });

  return (
    <section aria-label="Graduated autonomy" className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="font-semibold">Graduated autonomy</h2>
      <p className="mt-0.5 text-sm text-slate-500">
        Change classes whose plans no longer need a person in {a.stage}. A pre-approval never skips{" "}
        {a.floor.map((f) => FLOOR_LABEL[f] ?? f).join(", ")}.
      </p>
      {change.error && <p className="mt-2 text-sm text-red-700">{refusalText(change.error)}</p>}
      <div className="mt-3 space-y-2">
        {a.checkpoints.map((cp) => (
          <div key={cp} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-slate-500">{cp === "plan" ? "Plan checkpoint" : "Hand-off checkpoint"}:</span>
            {(a.pre_approved[cp] ?? []).length === 0 ? (
              <span className="text-slate-400">nothing pre-approved</span>
            ) : (
              (a.pre_approved[cp] ?? []).map((cls) => (
                <span key={cls} className="inline-flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-800">
                  {cls}
                  {a.can_edit && (
                    <button
                      type="button"
                      aria-label={`Stop pre-approving ${cls}`}
                      onClick={() => change.mutate({ checkpoint: cp, change_class: cls, action: "remove" })}
                      className="text-emerald-700 hover:text-red-700"
                    >
                      ×
                    </button>
                  )}
                </span>
              ))
            )}
          </div>
        ))}
      </div>
      {a.suggestions.length > 0 && (
        <ul className="mt-3 space-y-2">
          {a.suggestions.map((s) => (
            <li
              key={`${s.action}-${s.checkpoint}-${s.change_class}`}
              className={`rounded border p-2 text-sm ${s.action === "revoke" ? "border-amber-200 bg-amber-50" : "border-emerald-200 bg-emerald-50"}`}
            >
              <p>{s.reason}</p>
              {a.can_edit && (
                <button
                  type="button"
                  onClick={() => apply(s)}
                  disabled={change.isPending}
                  className="mt-1 text-xs font-medium text-canopy-700 hover:underline disabled:opacity-50"
                >
                  {s.action === "revoke" ? `Stop pre-approving ${s.change_class}` : `Pre-approve ${s.change_class} plans`}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {a.classes.length > 0 && (
        <details className="mt-3 text-xs text-slate-600">
          <summary className="cursor-pointer text-slate-500">Evidence by change class (last {a.weeks} weeks)</summary>
          <ul className="mt-1 space-y-0.5">
            {a.classes.slice(0, 12).map((row) => (
              <li key={row.change_class}>
                <code>{row.change_class}</code> — {classEvidenceText(row, KIND[a.checkpoints[0] ?? "plan"])}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
