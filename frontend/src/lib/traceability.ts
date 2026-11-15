// Decision-to-code traceability (PROPOSED_FLOWS §T) — the wording and grouping the ledger and
// the ADR panel share. The verdict itself is computed by the backend
// (app/services/traceability.py); this only presents it.
import type { DecisionTrace, TraceLedgerRow, TracedTask, TraceVerdict } from "../api/types";

export interface VerdictMeta {
  label: string;
  tone: string; // badge classes
  hint: string;
}

export const VERDICTS: Record<TraceVerdict, VerdictMeta> = {
  violated: {
    label: "Violated",
    tone: "bg-red-100 text-red-700",
    hint: "a fitness rule it carries is broken in the code",
  },
  unimplemented: {
    label: "Unimplemented",
    tone: "bg-red-50 text-red-600",
    hint: "the drift scan finds no code that implements it",
  },
  at_risk: {
    label: "At risk",
    tone: "bg-amber-100 text-amber-700",
    hint: "open drift on what it governs, or failed reviews against it",
  },
  in_progress: {
    label: "In progress",
    tone: "bg-blue-100 text-blue-700",
    hint: "its implementing work is still open",
  },
  no_linked_work: {
    label: "No linked work",
    tone: "bg-slate-100 text-slate-600",
    hint: "no task implements it or touches what it governs yet",
  },
  pending: {
    label: "Not binding yet",
    tone: "bg-slate-100 text-slate-500",
    hint: "the decision is not accepted",
  },
  honored: {
    label: "Honored",
    tone: "bg-emerald-100 text-emerald-700",
    hint: "its work is done, its rules hold, no drift is open",
  },
  retired: {
    label: "Retired",
    tone: "bg-slate-200 text-slate-500",
    hint: "superseded, deprecated or rejected",
  },
};

/** Worst first — the order the backend sorts the ledger in. */
export const VERDICT_ORDER: TraceVerdict[] = [
  "violated",
  "unimplemented",
  "at_risk",
  "in_progress",
  "no_linked_work",
  "pending",
  "honored",
  "retired",
];

export function verdictMeta(verdict: string): VerdictMeta {
  return (
    VERDICTS[verdict as TraceVerdict] ?? {
      label: verdict.replace(/_/g, " "),
      tone: "bg-slate-100 text-slate-600",
      hint: "",
    }
  );
}

/** "3 need attention" — the decisions whose verdict calls for a person. */
export function attentionCount(rows: TraceLedgerRow[]): number {
  return rows.filter((r) => ["violated", "unimplemented", "at_risk"].includes(r.verdict)).length;
}

/** Ledger counts as short phrases, leaving out what is zero. */
export function ledgerFacts(row: TraceLedgerRow): string[] {
  const out: string[] = [];
  if (row.tasks > 0) out.push(`${row.done}/${row.tasks} tasks done`);
  if (row.prs > 0) out.push(`${row.merged}/${row.prs} PRs merged`);
  if (row.fitness > 0) {
    out.push(
      row.violated > 0
        ? `${row.violated}/${row.fitness} rules broken`
        : `${row.fitness} fitness rule${row.fitness === 1 ? "" : "s"}, none broken`,
    );
  }
  if (row.reviews_checked > 0) {
    out.push(`${row.reviews_checked} review${row.reviews_checked === 1 ? "" : "s"} checked it`);
  }
  if (row.open_drift > 0) out.push(`${row.open_drift} open drift`);
  return out;
}

/** The trace's tasks split the way a reader asks: what says it implements the decision, and
 * what only touches what it governs. A task that does both is listed as implementing. */
export function splitTasks(trace: DecisionTrace): {
  implementing: TracedTask[];
  governed: TracedTask[];
} {
  return {
    implementing: trace.tasks.filter((t) => t.implements),
    governed: trace.tasks.filter((t) => !t.implements && t.governed),
  };
}

export function taskLabel(t: TracedTask): string {
  return t.key ?? `#${t.task_id}`;
}

/** "merged" · "open" · "closed" — a PR's state as a reviewer reads it. */
export function prState(pr: { state: string; merged: boolean }): string {
  if (pr.merged) return "merged";
  return pr.state === "open" ? "open" : "closed";
}

/** The fitness rule as a sentence: "payments must not depend on legacy-db". */
export function fitnessSentence(f: { kind: string; source: string; target: string }): string {
  return `${f.source} must ${f.kind === "forbid" ? "not " : ""}depend on ${f.target}`;
}

/** The URL if it is plain http(s), else null — PR links come from webhooks and are rendered
 * as links only when they cannot run script. */
export function httpUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}
