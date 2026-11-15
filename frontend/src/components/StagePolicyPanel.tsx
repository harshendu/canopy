import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  CheckDoc,
  DecisionDoc,
  Enforcement,
  PipelineRead,
  StageColumn,
  StagePolicyDoc,
  TemplatePreview,
} from "../api/types";
import { refusalText } from "../lib/execution";
import {
  APPROVERS,
  CHECKS,
  CONDITIONS,
  ENFORCEMENTS,
  SCOPE_LABEL,
  checksSummary,
  gateSummary,
  policyPath,
  workedByText,
} from "../lib/policy";

/**
 * The project's pipeline for agents (docs/AGENT_EXECUTION.md §9, Appendix A): each column with
 * who works it, what it requires to enter, and when a person looks — editable (people only) at
 * the scope the columns come from, plus a previewed one-step "agentic delivery" template.
 */
export default function StagePolicyPanel({
  projectId,
  canApplyTemplate,
}: {
  projectId: number;
  canApplyTemplate: boolean;
}) {
  const qc = useQueryClient();
  const pipeline = useQuery({
    queryKey: ["pipeline", projectId],
    queryFn: () => api.get<PipelineRead>(`/projects/${projectId}/workflow/policy`),
  });
  const [editing, setEditing] = useState<StageColumn | null>(null);
  const [preview, setPreview] = useState<TemplatePreview | null>(null);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["pipeline", projectId] });
    void qc.invalidateQueries({ queryKey: ["agents", projectId] });
    void qc.invalidateQueries({ queryKey: ["board", projectId] });
  };
  const previewTemplate = useMutation({
    mutationFn: () =>
      api.post<TemplatePreview>(`/projects/${projectId}/workflow/apply-template`, { dry_run: true }),
    onSuccess: setPreview,
  });
  const applyTemplate = useMutation({
    mutationFn: () =>
      api.post<TemplatePreview>(`/projects/${projectId}/workflow/apply-template`, { dry_run: false }),
    onSuccess: () => {
      setPreview(null);
      refresh();
    },
  });

  if (pipeline.isLoading) return <p className="text-sm text-slate-400">Loading the pipeline…</p>;
  if (pipeline.isError || !pipeline.data) {
    return <p className="text-sm text-red-700">{refusalText(pipeline.error)}</p>;
  }
  const data = pipeline.data;
  const path = policyPath(data.scope, { projectId, teamId: data.team_id });
  const editable = data.can_edit && path !== null;

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="font-semibold">Pipeline</h2>
          <p className="mt-0.5 text-sm text-slate-500">
            {data.configured
              ? `Stage policies from ${SCOPE_LABEL[data.scope]}.`
              : "The built-in default: agents implement in the first in-progress column and hand off to the next."}{" "}
            Roles: {data.roles.join(", ") || "none"}.
          </p>
        </div>
        {canApplyTemplate && (
          <button
            type="button"
            onClick={() => previewTemplate.mutate()}
            disabled={previewTemplate.isPending}
            className="rounded border border-violet-300 px-2.5 py-1 text-sm text-violet-700 hover:bg-violet-50 disabled:opacity-50"
          >
            {data.configured ? "Reset to the agentic delivery template…" : "Start from the agentic delivery template…"}
          </button>
        )}
      </div>
      {(previewTemplate.error ?? applyTemplate.error) && (
        <p role="alert" className="mt-2 text-xs text-red-700">
          {refusalText(previewTemplate.error ?? applyTemplate.error)}
        </p>
      )}
      <ol className="mt-3 divide-y divide-slate-100">
        {data.columns.map((c) => (
          <li key={c.status} className="flex flex-wrap items-start gap-3 py-2 text-sm">
            <div className="w-32 shrink-0">
              <div className="font-medium">{c.status}</div>
              <div className="text-xs text-slate-400">
                {c.category.replace("_", " ")}
                {c.wip_limit != null ? ` · WIP ${c.wip_limit}` : ""}
              </div>
            </div>
            <div className="min-w-0 flex-1 space-y-0.5 text-xs text-slate-600">
              <div className={c.worked_by ? "text-violet-800" : "text-slate-400"}>{workedByText(c)}</div>
              {checksSummary(c.policy).map((line) => (
                <div key={line}>{line}</div>
              ))}
              {gateSummary(c.policy).map((line) => (
                <div key={line} className="text-amber-800">
                  {line}
                </div>
              ))}
            </div>
            {editable && (
              <button
                type="button"
                onClick={() => setEditing(c)}
                className="shrink-0 text-xs text-slate-500 hover:text-canopy-700"
              >
                Edit
              </button>
            )}
          </li>
        ))}
      </ol>
      {!editable && data.configured && (
        <p className="mt-2 text-xs text-slate-400">
          Read-only here — the people who may edit {SCOPE_LABEL[data.scope]} change it.
        </p>
      )}
      {editing && path && (
        <PolicyDrawer
          column={editing}
          pipeline={data}
          path={path}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            refresh();
          }}
        />
      )}
      {preview && (
        <TemplateDialog
          preview={preview}
          busy={applyTemplate.isPending}
          onCancel={() => setPreview(null)}
          onApply={() => applyTemplate.mutate()}
        />
      )}
    </section>
  );
}

function TemplateDialog({
  preview,
  busy,
  onCancel,
  onApply,
}: {
  preview: TemplatePreview;
  busy: boolean;
  onCancel: () => void;
  onApply: () => void;
}) {
  const moving = preview.moves.filter((m) => m.tasks > 0);
  return (
    <div role="dialog" aria-modal aria-label="Apply the agentic delivery template" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-white p-5 shadow-xl">
        <h2 className="text-lg font-semibold">The agentic delivery template</h2>
        <p className="mt-1 text-sm text-slate-500">
          Saves these columns and their stage policies as this project’s own, with WIP limits
          enforced (<code>{preview.wip_enforcement}</code>). WIP limits themselves are yours to set.
        </p>
        <ol className="mt-3 space-y-1 text-sm">
          {preview.columns.map((c) => (
            <li key={c.name} className="flex gap-2">
              <span className="w-24 shrink-0 font-medium">{c.name}</span>
              <span className="text-slate-600">
                {c.worked_by === "human"
                  ? "a person signs off"
                  : c.worked_by
                    ? `worked by ${c.worked_by}`
                    : c.category === "todo"
                      ? "queue"
                      : c.category}
              </span>
            </li>
          ))}
        </ol>
        {moving.length > 0 && (
          <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900">
            <p className="font-medium">Cards that move</p>
            <ul className="mt-1 list-disc pl-5">
              {moving.map((m) => (
                <li key={m.from_status}>
                  {m.tasks} from <strong>{m.from_status}</strong> to <strong>{m.to_status}</strong>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="rounded px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100">
            Cancel
          </button>
          <button
            type="button"
            onClick={onApply}
            disabled={busy}
            className="rounded bg-canopy-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-canopy-700 disabled:opacity-50"
          >
            {busy ? "Applying…" : "Apply the template"}
          </button>
        </div>
      </div>
    </div>
  );
}

const ROLE_CHOICES = ["", "implementer", "reviewer", "qa", "human"];

function PolicyDrawer({
  column,
  pipeline,
  path,
  onClose,
  onSaved,
}: {
  column: StageColumn;
  pipeline: PipelineRead;
  path: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const initial: StagePolicyDoc = column.policy ?? { worked_by: column.worked_by };
  const [doc, setDoc] = useState<StagePolicyDoc>(structuredClone(initial));
  const names = pipeline.columns.map((c) => c.status);
  const save = useMutation({
    mutationFn: (next: StagePolicyDoc | null) => {
      const policies: Record<string, StagePolicyDoc | null> = {};
      for (const c of pipeline.columns) {
        if (c.policy) policies[c.status] = c.policy;
      }
      policies[column.status] = next;
      return api.put<PipelineRead>(path, { policies });
    },
    onSuccess: onSaved,
  });
  const checks = doc.enter?.checks ?? [];
  const setCheck = (name: string, patch: Partial<CheckDoc> | null) => {
    const others = checks.filter((c) => c.check !== name);
    const current = checks.find((c) => c.check === name) ?? { check: name, enforcement: "block" as Enforcement };
    const next = patch === null ? others : [...others, { ...current, ...patch }];
    setDoc({ ...doc, enter: { checks: next } });
  };
  const agentStage = !!doc.worked_by && doc.worked_by !== "human";
  const plan = doc.checkpoints?.plan;
  const planWhen = Array.isArray(plan?.approval_when) ? plan.approval_when : [];
  const decision: DecisionDoc = doc.decision ?? {};

  return (
    <div role="dialog" aria-modal aria-label={`Stage policy: ${column.status}`} className="fixed inset-0 z-50 flex justify-end bg-black/30">
      <div className="h-full w-full max-w-xl overflow-y-auto bg-white p-5 shadow-xl">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold">{column.status}</h2>
            <p className="text-xs text-slate-500">Stage policy · saved for {SCOPE_LABEL[pipeline.scope]}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-slate-700">
            ✕
          </button>
        </div>

        <div className="mt-4 space-y-4 text-sm">
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Who works it</span>
            <select
              value={doc.worked_by ?? ""}
              onChange={(e) => setDoc({ ...doc, worked_by: e.target.value || null })}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            >
              {ROLE_CHOICES.map((r) => (
                <option key={r} value={r}>
                  {r === "" ? "No one (a queue)" : r === "human" ? "People (a decision column)" : `Agents as ${r}`}
                </option>
              ))}
            </select>
          </label>

          {agentStage && (
            <label className="block">
              <span className="text-xs font-medium text-slate-600">Instructions for the session (policy)</span>
              <textarea
                value={doc.instructions ?? ""}
                onChange={(e) => setDoc({ ...doc, instructions: e.target.value })}
                rows={3}
                className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
              />
            </label>
          )}

          <fieldset>
            <legend className="text-xs font-medium text-slate-600">To enter this column</legend>
            <ul className="mt-1 space-y-1">
              {CHECKS.map((def) => {
                const current = checks.find((c) => c.check === def.check);
                return (
                  <li key={def.check} className="flex flex-wrap items-center gap-2">
                    <select
                      aria-label={`${def.label}: enforcement`}
                      value={current?.enforcement ?? ""}
                      onChange={(e) =>
                        setCheck(def.check, e.target.value ? { enforcement: e.target.value as Enforcement } : null)
                      }
                      className="w-20 rounded border border-slate-300 px-1 py-0.5 text-xs"
                    >
                      <option value="">—</option>
                      {ENFORCEMENTS.map((en) => (
                        <option key={en} value={en}>
                          {en}
                        </option>
                      ))}
                    </select>
                    <span className="min-w-0 flex-1 text-xs">
                      {def.label}{" "}
                      <span className="text-slate-400">({def.fact === "observed" ? "canopy sees it" : "someone states it"})</span>
                    </span>
                    {current &&
                      def.params?.map((p) => (
                        <input
                          key={p.name}
                          aria-label={`${def.label}: ${p.label}`}
                          placeholder={p.label}
                          list={p.options ? `${def.check}-${p.name}` : undefined}
                          value={String(current.params?.[p.name] ?? "")}
                          onChange={(e) =>
                            setCheck(def.check, {
                              params: { ...current.params, [p.name]: p.number ? Number(e.target.value) || "" : e.target.value },
                            })
                          }
                          className="w-28 rounded border border-slate-300 px-1 py-0.5 text-xs"
                        />
                      ))}
                    {current && (
                      <label className="flex items-center gap-1 text-[11px] text-slate-500">
                        <input
                          type="checkbox"
                          checked={current.applies_to === "everyone"}
                          onChange={(e) => setCheck(def.check, { applies_to: e.target.checked ? "everyone" : "agents" })}
                        />
                        people too
                      </label>
                    )}
                  </li>
                );
              })}
            </ul>
            {CHECKS.filter((d) => d.params?.some((p) => p.options)).map((d) =>
              d.params?.filter((p) => p.options).map((p) => (
                <datalist key={`${d.check}-${p.name}`} id={`${d.check}-${p.name}`}>
                  {p.options?.map((o) => <option key={o} value={o} />)}
                </datalist>
              )),
            )}
          </fieldset>

          {agentStage && (
            <fieldset>
              <legend className="text-xs font-medium text-slate-600">Plan checkpoint</legend>
              <label className="mt-1 flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={!!plan}
                  onChange={(e) =>
                    setDoc({
                      ...doc,
                      checkpoints: e.target.checked
                        ? { ...doc.checkpoints, plan: { required: true, approval_when: ["one_way_door", "no_spec"] } }
                        : Object.fromEntries(Object.entries(doc.checkpoints ?? {}).filter(([k]) => k !== "plan")),
                    })
                  }
                />
                Require a plan before the hand-off
              </label>
              {plan && (
                <div className="mt-1 space-y-0.5 pl-5">
                  <p className="text-[11px] text-slate-500">A person approves the plan when:</p>
                  {CONDITIONS.map((cond) => (
                    <label key={cond.value} className="flex items-center gap-2 text-xs">
                      <input
                        type="checkbox"
                        checked={planWhen.includes(cond.value)}
                        onChange={(e) => {
                          const next = e.target.checked
                            ? [...planWhen, cond.value]
                            : planWhen.filter((w) => w !== cond.value);
                          setDoc({
                            ...doc,
                            checkpoints: { ...doc.checkpoints, plan: { ...plan, approval_when: next.length ? next : "never" } },
                          });
                        }}
                      />
                      {cond.label}
                    </label>
                  ))}
                </div>
              )}
            </fieldset>
          )}

          {doc.worked_by === "human" && (
            <fieldset className="space-y-2">
              <legend className="text-xs font-medium text-slate-600">The decision</legend>
              <label className="block text-xs">
                Who decides
                <select
                  value={decision.approvers ?? "project_planners"}
                  onChange={(e) => setDoc({ ...doc, decision: { ...decision, approvers: e.target.value } })}
                  className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1"
                >
                  {APPROVERS.map((a) => (
                    <option key={a.value} value={a.value}>
                      {a.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={decision.exclude_requester !== false}
                  onChange={(e) => setDoc({ ...doc, decision: { ...decision, exclude_requester: e.target.checked } })}
                />
                Not the person whose agent did the work
              </label>
              {(["pr_approval", "pr_merge"] as const).map((via) => {
                const satisfied = decision.satisfied_by ?? ["canopy"];
                return (
                  <label key={via} className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={satisfied.includes(via)}
                      onChange={(e) =>
                        setDoc({
                          ...doc,
                          decision: {
                            ...decision,
                            satisfied_by: e.target.checked
                              ? [...new Set([...satisfied, "canopy", via])]
                              : satisfied.filter((s) => s !== via),
                          },
                        })
                      }
                    />
                    {via === "pr_approval" ? "A PR approval from someone else counts" : "The merge counts"}
                  </label>
                );
              })}
              {(["on_approve", "on_changes", "on_reject"] as const).map((key) => (
                <label key={key} className="block text-xs">
                  {key === "on_approve" ? "Approved → " : key === "on_changes" ? "Changes requested → " : "Rejected → "}
                  <select
                    value={decision[key] ?? ""}
                    onChange={(e) => setDoc({ ...doc, decision: { ...decision, [key]: e.target.value || null } })}
                    className="ml-1 rounded border border-slate-300 px-1 py-0.5"
                  >
                    <option value="">(default)</option>
                    {names.map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </fieldset>
          )}

          {agentStage && (
            <div className="grid grid-cols-3 gap-2 text-xs">
              {(["lease_minutes", "max_attempts", "max_rework"] as const).map((key) => (
                <label key={key}>
                  {key === "lease_minutes" ? "Lease (min)" : key === "max_attempts" ? "Attempts" : "Rework rounds"}
                  <input
                    type="number"
                    min={1}
                    value={doc[key] ?? ""}
                    placeholder={key === "lease_minutes" ? "30" : "3"}
                    onChange={(e) => setDoc({ ...doc, [key]: e.target.value ? Number(e.target.value) : undefined })}
                    className="mt-0.5 w-full rounded border border-slate-300 px-1 py-0.5"
                  />
                </label>
              ))}
            </div>
          )}

          {save.isError && (
            <p role="alert" className="rounded bg-red-50 px-2 py-1 text-xs text-red-700">
              {refusalText(save.error)}
            </p>
          )}
          <div className="flex items-center justify-between gap-2 pt-2">
            <button
              type="button"
              onClick={() => save.mutate(null)}
              disabled={save.isPending || !column.policy}
              className="text-xs text-slate-500 hover:text-red-600 disabled:opacity-40"
            >
              Remove this column’s policy
            </button>
            <div className="flex gap-2">
              <button type="button" onClick={onClose} className="rounded px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100">
                Cancel
              </button>
              <button
                type="button"
                onClick={() => save.mutate(doc)}
                disabled={save.isPending}
                className="rounded bg-canopy-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-canopy-700 disabled:opacity-50"
              >
                {save.isPending ? "Saving…" : "Save policy"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
