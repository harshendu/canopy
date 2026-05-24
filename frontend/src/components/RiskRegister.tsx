import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  Engineer,
  RiskCategory,
  RiskGrade,
  RiskItem,
  RiskItemCreate,
  RiskScope,
  RiskStatus,
} from "../api/types";
import { riskTone } from "../lib/risk";

const CATEGORIES: RiskCategory[] = [
  "schedule",
  "scope",
  "technical",
  "resource",
  "external",
  "quality",
  "security",
];
const GRADES: RiskGrade[] = ["low", "medium", "high"];
const STATUSES: RiskStatus[] = ["open", "mitigating", "accepted", "resolved", "occurred"];

const STATUS_BADGE: Record<RiskStatus, string> = {
  open: "bg-red-100 text-red-700",
  mitigating: "bg-amber-100 text-amber-700",
  accepted: "bg-purple-100 text-purple-700",
  resolved: "bg-emerald-100 text-emerald-700",
  occurred: "bg-slate-200 text-slate-600",
};

/** The human risk register (RAID) for a task / project / initiative. Distinct from the
 *  computed risk score — these are qualitative risks an architect tracks by hand. */
export default function RiskRegister({
  scope,
  scopeId,
  mayWrite,
}: {
  scope: RiskScope;
  scopeId: number;
  mayWrite: boolean;
}) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);

  const risks = useQuery({
    queryKey: ["risks", scope, scopeId],
    queryFn: () => api.get<RiskItem[]>(`/risks?scope_level=${scope}&scope_id=${scopeId}`),
  });
  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });
  const names = new Map((engineers.data ?? []).map((e) => [e.id, e.name]));

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["risks", scope, scopeId] });
    qc.invalidateQueries({ queryKey: ["portfolio"] });
  };

  const patch = useMutation({
    mutationFn: (vars: { id: number; body: Partial<RiskItem> }) =>
      api.patch(`/risks/${vars.id}`, vars.body),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/risks/${id}`),
    onSuccess: invalidate,
  });

  const items = risks.data ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700">
          Risk register (RAID)
          <span className="ml-2 text-xs font-normal text-slate-400">
            tracked separately from the computed risk score
          </span>
        </h3>
        {mayWrite && (
          <button
            onClick={() => setAdding((v) => !v)}
            className="rounded border border-canopy-500 px-3 py-1 text-xs font-medium text-canopy-700"
          >
            {adding ? "Cancel" : "Add risk"}
          </button>
        )}
      </div>

      {adding && (
        <AddRiskForm
          scope={scope}
          scopeId={scopeId}
          engineers={engineers.data ?? []}
          onDone={() => {
            setAdding(false);
            invalidate();
          }}
        />
      )}

      {items.length === 0 ? (
        <p className="text-sm text-slate-500">No risks logged.</p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white text-sm">
          {items.map((r) => {
            const tone = riskTone(r.exposure_level);
            return (
              <li key={r.id} className="space-y-1 px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${tone.badge}`}>
                    {tone.label} · {r.exposure}
                  </span>
                  <span className="font-medium">{r.title}</span>
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                    {r.category}
                  </span>
                  <span className="ml-auto text-xs text-slate-400">
                    P:{r.probability} × I:{r.impact}
                  </span>
                </div>
                {r.description && <p className="text-xs text-slate-500">{r.description}</p>}
                {(r.mitigation || r.contingency) && (
                  <p className="text-xs text-slate-500">
                    {r.mitigation && <>↳ mitigation: {r.mitigation} </>}
                    {r.contingency && <>· contingency: {r.contingency}</>}
                  </p>
                )}
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  {r.owner_engineer_id != null && (
                    <span>owner: {names.get(r.owner_engineer_id) ?? `#${r.owner_engineer_id}`}</span>
                  )}
                  {r.target_resolution_date && <span>· by {r.target_resolution_date}</span>}
                  {mayWrite ? (
                    <select
                      value={r.status}
                      onChange={(e) =>
                        patch.mutate({ id: r.id, body: { status: e.target.value as RiskStatus } })
                      }
                      className={`ml-auto rounded px-1.5 py-0.5 text-xs font-medium ${STATUS_BADGE[r.status]}`}
                    >
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span
                      className={`ml-auto rounded px-1.5 py-0.5 text-xs font-medium ${STATUS_BADGE[r.status]}`}
                    >
                      {r.status}
                    </span>
                  )}
                  {mayWrite && (
                    <button
                      onClick={() => remove.mutate(r.id)}
                      className="text-slate-400 hover:text-red-600"
                    >
                      delete
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function AddRiskForm({
  scope,
  scopeId,
  engineers,
  onDone,
}: {
  scope: RiskScope;
  scopeId: number;
  engineers: Engineer[];
  onDone: () => void;
}) {
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<RiskCategory>("technical");
  const [probability, setProbability] = useState<RiskGrade>("medium");
  const [impact, setImpact] = useState<RiskGrade>("medium");
  const [owner, setOwner] = useState<number | "">("");
  const [mitigation, setMitigation] = useState("");
  const [contingency, setContingency] = useState("");
  const [targetDate, setTargetDate] = useState("");

  const create = useMutation({
    mutationFn: () => {
      const body: RiskItemCreate = {
        scope_level: scope,
        scope_id: scopeId,
        title,
        category,
        probability,
        impact,
        owner_engineer_id: owner === "" ? null : owner,
        mitigation: mitigation || null,
        contingency: contingency || null,
        target_resolution_date: targetDate || null,
      };
      return api.post("/risks", body);
    },
    onSuccess: onDone,
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (title.trim()) create.mutate();
      }}
      className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm"
    >
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Risk (e.g. Vendor API may slip)"
        className="w-full rounded border border-slate-300 px-3 py-2"
      />
      <div className="flex flex-wrap gap-2">
        <label className="flex items-center gap-1 text-xs text-slate-500">
          category
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value as RiskCategory)}
            className="rounded border border-slate-300 px-2 py-1"
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 text-xs text-slate-500">
          probability
          <select
            value={probability}
            onChange={(e) => setProbability(e.target.value as RiskGrade)}
            className="rounded border border-slate-300 px-2 py-1"
          >
            {GRADES.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 text-xs text-slate-500">
          impact
          <select
            value={impact}
            onChange={(e) => setImpact(e.target.value as RiskGrade)}
            className="rounded border border-slate-300 px-2 py-1"
          >
            {GRADES.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 text-xs text-slate-500">
          owner
          <select
            value={owner}
            onChange={(e) => setOwner(e.target.value ? Number(e.target.value) : "")}
            className="rounded border border-slate-300 px-2 py-1"
          >
            <option value="">—</option>
            {engineers.map((eng) => (
              <option key={eng.id} value={eng.id}>
                {eng.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 text-xs text-slate-500">
          resolve by
          <input
            type="date"
            value={targetDate}
            onChange={(e) => setTargetDate(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1"
          />
        </label>
      </div>
      <input
        value={mitigation}
        onChange={(e) => setMitigation(e.target.value)}
        placeholder="Mitigation (lower the probability)"
        className="w-full rounded border border-slate-300 px-3 py-2"
      />
      <input
        value={contingency}
        onChange={(e) => setContingency(e.target.value)}
        placeholder="Contingency (if it occurs anyway)"
        className="w-full rounded border border-slate-300 px-3 py-2"
      />
      <button
        type="submit"
        disabled={create.isPending}
        className="rounded bg-canopy-500 px-4 py-2 text-xs font-medium text-white disabled:opacity-50"
      >
        {create.isPending ? "Saving…" : "Log risk"}
      </button>
    </form>
  );
}
