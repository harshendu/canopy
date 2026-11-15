// Decision-to-code traceability (PROPOSED_FLOWS §T, AGENT_EXECUTION.md Phase 4): for a decision,
// what implemented it and is it still honored. Read-only — the verdict is computed by the
// backend from the tasks, PRs, reviews, fitness rules and drift it joins.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { DecisionTrace, Task, TraceLedgerRow, TracedTask } from "../api/types";
import {
  attentionCount,
  fitnessSentence,
  httpUrl,
  ledgerFacts,
  prState,
  splitTasks,
  taskLabel,
  verdictMeta,
} from "../lib/traceability";

const adrLabel = (n: number) => `ADR-${String(n).padStart(4, "0")}`;

function VerdictBadge({ verdict }: { verdict: string }) {
  const meta = verdictMeta(verdict);
  return (
    <span className={`shrink-0 rounded px-2 py-0.5 text-xs ${meta.tone}`} title={meta.hint}>
      {meta.label}
    </span>
  );
}

/** The project's ledger: one row per decision, worst verdict first. */
export function TraceabilityLedger({
  projectId,
  onPick,
}: {
  projectId: number;
  onPick: (adrId: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const ledger = useQuery({
    queryKey: ["traceability", projectId],
    queryFn: () =>
      api.get<TraceLedgerRow[]>(`/architecture/traceability?project_id=${projectId}`),
  });
  const rows = ledger.data ?? [];
  if (ledger.isLoading || rows.length === 0) return null;
  const attention = attentionCount(rows);
  const shown = open ? rows : rows.slice(0, 5);

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-semibold">Traceability ledger</h2>
        <span className="text-xs text-slate-500">
          {attention > 0
            ? `${attention} decision${attention === 1 ? "" : "s"} need${attention === 1 ? "s" : ""} attention`
            : "Every binding decision is honored or on its way"}
        </span>
      </div>
      <p className="mb-2 text-xs text-slate-500">
        Each decision joined to the work that implements it or touches what it governs, the
        pull requests and reviews behind that work, its fitness rules and open drift.
      </p>
      <ul className="divide-y divide-slate-100">
        {shown.map((r) => {
          const facts = ledgerFacts(r);
          return (
            <li key={r.adr_id}>
              <button
                onClick={() => onPick(r.adr_id)}
                className="flex w-full flex-wrap items-center gap-2 px-1 py-2 text-left text-sm hover:bg-slate-50"
              >
                <span className="font-mono text-xs text-slate-400">{adrLabel(r.number)}</span>
                <span className="min-w-0 flex-1 truncate">{r.title}</span>
                <VerdictBadge verdict={r.verdict} />
                <span className="basis-full pl-1 text-xs text-slate-500">
                  {r.reason}
                  {facts.length > 0 && (
                    <span className="text-slate-400"> · {facts.join(" · ")}</span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {rows.length > 5 && (
        <button
          onClick={() => setOpen(!open)}
          className="mt-1 text-xs text-canopy-700 underline"
        >
          {open ? "Show fewer" : `Show all ${rows.length}`}
        </button>
      )}
    </section>
  );
}

function TaskList({
  title,
  tasks,
  onUnlink,
}: {
  title: string;
  tasks: TracedTask[];
  onUnlink?: (taskId: number) => void;
}) {
  if (tasks.length === 0) return null;
  return (
    <div>
      <div className="text-xs text-slate-400">{title}</div>
      <ul className="mt-0.5 space-y-0.5 text-xs text-slate-600">
        {tasks.map((t) => (
          <li key={t.task_id} className="flex items-center gap-2">
            <span className="font-mono text-slate-400">{taskLabel(t)}</span>
            <span className="truncate">{t.name}</span>
            <span
              className={`ml-auto shrink-0 rounded px-1.5 py-0.5 ${
                t.done ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"
              }`}
            >
              {t.status ?? (t.done ? "done" : "open")}
            </span>
            {onUnlink && (
              <button
                onClick={() => onUnlink(t.task_id)}
                className="shrink-0 text-slate-400 hover:text-red-600"
                title="This task does not implement the decision"
              >
                unlink
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Planners record which task implements the decision (`Task.implements_adr_id`). */
function LinkTask({
  adrId,
  projectId,
  linked,
}: {
  adrId: number;
  projectId: number;
  linked: Set<number>;
}) {
  const qc = useQueryClient();
  const [taskId, setTaskId] = useState<number | "">("");
  const tasks = useQuery({
    queryKey: ["tasks", projectId],
    queryFn: () => api.get<Task[]>(`/tasks?project_id=${projectId}`),
  });
  const link = useMutation({
    mutationFn: (id: number) => api.patch(`/tasks/${id}`, { implements_adr_id: adrId }),
    onSuccess: () => {
      setTaskId("");
      qc.invalidateQueries({ queryKey: ["traceability-adr", adrId] });
      qc.invalidateQueries({ queryKey: ["traceability", projectId] });
      qc.invalidateQueries({ queryKey: ["tasks", projectId] });
    },
  });
  const options = (tasks.data ?? []).filter((t) => t.type !== "summary" && !linked.has(t.id));
  if (options.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        value={taskId}
        onChange={(e) => setTaskId(e.target.value ? Number(e.target.value) : "")}
        className="max-w-xs rounded border border-slate-300 px-2 py-1 text-xs"
        aria-label="Task that implements this decision"
      >
        <option value="">Link a task that implements it…</option>
        {options.map((t) => (
          <option key={t.id} value={t.id}>
            {t.key ? `${t.key} · ` : ""}
            {t.name}
            {t.implements_adr_id ? " (implements another decision)" : ""}
          </option>
        ))}
      </select>
      <button
        disabled={taskId === "" || link.isPending}
        onClick={() => taskId !== "" && link.mutate(taskId)}
        className="rounded bg-canopy-500 px-2 py-1 text-xs font-medium text-white disabled:opacity-40"
      >
        Link
      </button>
      {link.isError && (
        <span className="text-xs text-red-600">{(link.error as Error).message}</span>
      )}
    </div>
  );
}

/** One decision's trace, inside the ADR detail. */
export function TraceabilityPanel({
  adrId,
  projectId,
  mayLink,
}: {
  adrId: number;
  projectId: number;
  mayLink: boolean;
}) {
  const qc = useQueryClient();
  const trace = useQuery({
    queryKey: ["traceability-adr", adrId],
    queryFn: () => api.get<DecisionTrace>(`/architecture/adrs/${adrId}/traceability`),
  });
  const unlink = useMutation({
    mutationFn: (taskId: number) => api.patch(`/tasks/${taskId}`, { implements_adr_id: null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["traceability-adr", adrId] });
      qc.invalidateQueries({ queryKey: ["traceability", projectId] });
      qc.invalidateQueries({ queryKey: ["tasks", projectId] });
    },
  });
  const t = trace.data;
  if (!t) {
    return trace.isError ? null : (
      <p className="text-xs text-slate-400">Tracing the decision to code…</p>
    );
  }
  const { implementing, governed } = splitTasks(t);
  const checked = t.reviews.filter((r) => r.checked);
  const labelOf = (taskId: number | null) => {
    const task = t.tasks.find((x) => x.task_id === taskId);
    return task ? taskLabel(task) : null;
  };

  return (
    <div className="space-y-2 border-t border-slate-100 pt-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Traceability
        </span>
        <VerdictBadge verdict={t.verdict} />
        <span className="text-xs text-slate-500">{t.reason}</span>
      </div>
      {t.components.length > 0 && (
        <div className="text-xs text-slate-500">Governs: {t.components.join(", ")}</div>
      )}
      <TaskList
        title="Implements it"
        tasks={implementing}
        onUnlink={mayLink ? (id) => unlink.mutate(id) : undefined}
      />
      <TaskList title="Touches what it governs" tasks={governed} />
      {mayLink && (
        <LinkTask
          adrId={adrId}
          projectId={projectId}
          linked={new Set(implementing.map((x) => x.task_id))}
        />
      )}
      {t.pull_requests.length > 0 && (
        <div>
          <div className="text-xs text-slate-400">Pull requests</div>
          <ul className="mt-0.5 space-y-0.5 text-xs text-slate-600">
            {t.pull_requests.map((pr) => {
              const href = httpUrl(pr.url);
              const name = `${pr.repo}#${pr.number}`;
              const task = labelOf(pr.task_id);
              return (
                <li key={`${pr.repo}#${pr.number}`} className="flex items-center gap-2">
                  {href ? (
                    <a href={href} target="_blank" rel="noreferrer" className="text-canopy-700 underline">
                      {name}
                    </a>
                  ) : (
                    <span>{name}</span>
                  )}
                  {task && <span className="font-mono text-slate-400">{task}</span>}
                  <span className="ml-auto shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-slate-500">
                    {prState(pr)}
                    {pr.checks_state ? ` · checks ${pr.checks_state}` : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {checked.length > 0 && (
        <div className="text-xs text-slate-600">
          <span className="text-slate-400">Reviews that checked the work against it: </span>
          {checked
            .map((r) => `${labelOf(r.task_id) ?? `#${r.task_id}`} ${r.verdict ?? "no verdict"}`)
            .join(" · ")}
        </div>
      )}
      {t.fitness.length > 0 && (
        <ul className="space-y-0.5 text-xs">
          {t.fitness.map((f) => (
            <li key={f.fitness_id} className={f.violated ? "text-red-700" : "text-slate-600"}>
              {f.violated ? "Broken: " : "No open violation: "}
              {fitnessSentence(f)}
            </li>
          ))}
        </ul>
      )}
      {t.drift.length > 0 && (
        <ul className="space-y-0.5 text-xs text-amber-700">
          {t.drift.map((d) => (
            <li key={d.drift_id}>Open drift: {d.summary}</li>
          ))}
        </ul>
      )}
      {t.tasks.length === 0 && t.verdict !== "pending" && t.verdict !== "retired" && (
        <p className="text-xs text-slate-400">
          No work is linked yet. Link the task that implements it
          {t.components.length > 0
            ? ", or plan work that touches the components it governs"
            : ", and add the components it governs so related work is traced too"}
          .
        </p>
      )}
    </div>
  );
}
