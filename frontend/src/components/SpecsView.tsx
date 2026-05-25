import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  CriterionStatus,
  Spec,
  SpecCriterion,
  SpecDetail,
  SpecStatus,
} from "../api/types";

const SPEC_STATUSES: SpecStatus[] = ["draft", "approved", "in_progress", "verified", "archived"];
const CRITERION_STATUSES: CriterionStatus[] = ["open", "met", "unmet", "waived"];

const STATUS_BADGE: Record<SpecStatus, string> = {
  draft: "bg-slate-200 text-slate-600",
  approved: "bg-blue-100 text-blue-700",
  in_progress: "bg-amber-100 text-amber-700",
  verified: "bg-emerald-100 text-emerald-700",
  archived: "bg-slate-100 text-slate-400",
};

const CRITERION_BADGE: Record<CriterionStatus, string> = {
  open: "bg-slate-100 text-slate-500",
  met: "bg-emerald-100 text-emerald-700",
  unmet: "bg-red-100 text-red-700",
  waived: "bg-purple-100 text-purple-700",
};

/** Specs (spec-driven development): intent + checkable acceptance criteria, with a self-audit
 *  readiness bar. Spec CRUD is planner-gated; criterion verdicts are contributor-writable. */
export default function SpecsView({
  projectId,
  mayPlan,
  mayContribute,
}: {
  projectId: number;
  mayPlan: boolean;
  mayContribute: boolean;
}) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);

  const specs = useQuery({
    queryKey: ["specs", projectId],
    queryFn: () => api.get<Spec[]>(`/specs?project_id=${projectId}`),
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">
          Specs
          <span className="ml-2 text-xs font-normal text-slate-400">
            intent as the source of truth — problem + checkable acceptance criteria
          </span>
        </h2>
        {mayPlan && (
          <button
            onClick={() => setAdding((v) => !v)}
            className="rounded border border-canopy-500 px-3 py-1 text-xs font-medium text-canopy-700"
          >
            {adding ? "Cancel" : "New spec"}
          </button>
        )}
      </div>

      {adding && (
        <AddSpecForm
          projectId={projectId}
          onDone={() => {
            setAdding(false);
            qc.invalidateQueries({ queryKey: ["specs", projectId] });
          }}
        />
      )}

      {(specs.data ?? []).length === 0 ? (
        <p className="text-sm text-slate-500">No specs yet.</p>
      ) : (
        <ul className="space-y-2">
          {(specs.data ?? []).map((s) => (
            <li key={s.id} className="rounded-lg border border-slate-200 bg-white">
              <button
                onClick={() => setOpenId(openId === s.id ? null : s.id)}
                className="flex w-full items-center gap-2 px-4 py-3 text-left"
              >
                <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${STATUS_BADGE[s.status]}`}>
                  {s.status}
                </span>
                <span className="font-medium">{s.title}</span>
                <span className="ml-auto text-xs text-slate-400">
                  {openId === s.id ? "▲" : "▼"}
                </span>
              </button>
              {openId === s.id && (
                <SpecDetailPanel
                  specId={s.id}
                  projectId={projectId}
                  mayPlan={mayPlan}
                  mayContribute={mayContribute}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SpecDetailPanel({
  specId,
  projectId,
  mayPlan,
  mayContribute,
}: {
  specId: number;
  projectId: number;
  mayPlan: boolean;
  mayContribute: boolean;
}) {
  const qc = useQueryClient();
  const [critText, setCritText] = useState("");
  const detail = useQuery({
    queryKey: ["spec", specId],
    queryFn: () => api.get<SpecDetail>(`/specs/${specId}`),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["spec", specId] });
    qc.invalidateQueries({ queryKey: ["specs", projectId] });
  };

  const setStatus = useMutation({
    mutationFn: (status: SpecStatus) => api.patch(`/specs/${specId}`, { status }),
    onSuccess: invalidate,
  });
  const addCriterion = useMutation({
    mutationFn: (text: string) => api.post(`/specs/${specId}/criteria`, { text }),
    onSuccess: () => {
      setCritText("");
      invalidate();
    },
  });
  const setCriterion = useMutation({
    mutationFn: (vars: { id: number; status: CriterionStatus }) =>
      api.patch(`/criteria/${vars.id}`, { status: vars.status }),
    onSuccess: invalidate,
  });

  if (!detail.data) return <div className="px-4 pb-3 text-sm text-slate-400">Loading…</div>;
  const d = detail.data;
  const pct = Math.round(d.acceptance_ratio * 100);

  return (
    <div className="space-y-3 border-t border-slate-100 px-4 py-3 text-sm">
      <p className="text-slate-700">{d.problem}</p>
      {d.context && <p className="text-xs text-slate-500">Context: {d.context}</p>}
      {d.out_of_scope && <p className="text-xs text-slate-500">Out of scope: {d.out_of_scope}</p>}
      {d.source_url && (
        <a href={d.source_url} target="_blank" rel="noreferrer" className="text-xs text-canopy-700 underline">
          source doc ↗
        </a>
      )}

      <div className="flex items-center gap-2">
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full bg-emerald-500"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-xs tabular-nums text-slate-500">
          {d.criteria_met}/{d.criteria_total} met
        </span>
        {mayPlan && (
          <select
            value={d.status}
            onChange={(e) => setStatus.mutate(e.target.value as SpecStatus)}
            className="rounded border border-slate-300 px-1.5 py-0.5 text-xs"
          >
            {SPEC_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}
      </div>

      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Acceptance criteria
        </h4>
        {d.criteria.length === 0 ? (
          <p className="text-xs text-slate-400">No criteria yet — add the checkable conditions of done.</p>
        ) : (
          <ul className="space-y-1">
            {d.criteria.map((c: SpecCriterion) => (
              <li key={c.id} className="flex items-center gap-2">
                {mayContribute ? (
                  <select
                    value={c.status}
                    onChange={(e) =>
                      setCriterion.mutate({ id: c.id, status: e.target.value as CriterionStatus })
                    }
                    className={`rounded px-1.5 py-0.5 text-xs font-medium ${CRITERION_BADGE[c.status]}`}
                  >
                    {CRITERION_STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${CRITERION_BADGE[c.status]}`}>
                    {c.status}
                  </span>
                )}
                <span className="text-slate-700">{c.text}</span>
              </li>
            ))}
          </ul>
        )}
        {mayPlan && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (critText.trim()) addCriterion.mutate(critText.trim());
            }}
            className="mt-2 flex gap-2"
          >
            <input
              value={critText}
              onChange={(e) => setCritText(e.target.value)}
              placeholder="Add a checkable criterion…"
              className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
            />
            <button className="rounded bg-canopy-500 px-3 py-1 text-xs font-medium text-white">
              Add
            </button>
          </form>
        )}
      </div>

      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Implementing tasks
        </h4>
        {d.linked_tasks.length === 0 ? (
          <p className="text-xs text-slate-400">
            No tasks linked yet (set a task's spec to this one).
          </p>
        ) : (
          <ul className="space-y-0.5 text-xs">
            {d.linked_tasks.map((t) => (
              <li key={t.id} className="flex items-center gap-2">
                <span className={t.is_critical ? "font-medium text-red-600" : ""}>{t.name}</span>
                <span className="text-slate-400">
                  {t.status ?? "—"} · {Math.round(t.percent_complete)}%
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function AddSpecForm({ projectId, onDone }: { projectId: number; onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [problem, setProblem] = useState("");
  const [outOfScope, setOutOfScope] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.post("/specs", {
        project_id: projectId,
        title,
        problem,
        out_of_scope: outOfScope || null,
        source_url: sourceUrl || null,
      }),
    onSuccess: onDone,
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (title.trim() && problem.trim()) create.mutate();
      }}
      className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm"
    >
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Spec title"
        className="w-full rounded border border-slate-300 px-3 py-2"
      />
      <textarea
        value={problem}
        onChange={(e) => setProblem(e.target.value)}
        placeholder="Problem / intent — what and why"
        rows={2}
        className="w-full rounded border border-slate-300 px-3 py-2"
      />
      <input
        value={outOfScope}
        onChange={(e) => setOutOfScope(e.target.value)}
        placeholder="Out of scope (optional)"
        className="w-full rounded border border-slate-300 px-3 py-2"
      />
      <input
        value={sourceUrl}
        onChange={(e) => setSourceUrl(e.target.value)}
        placeholder="PRD / design doc URL (optional)"
        className="w-full rounded border border-slate-300 px-3 py-2"
      />
      <button
        type="submit"
        disabled={create.isPending}
        className="rounded bg-canopy-500 px-4 py-2 text-xs font-medium text-white disabled:opacity-50"
      >
        {create.isPending ? "Saving…" : "Create spec"}
      </button>
    </form>
  );
}
