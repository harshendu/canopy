import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { AgentFlow, GateKind } from "../api/types";
import { GATE_KIND_LABEL } from "../lib/execution";
import { hoursText, percent } from "../lib/policy";

function kindLabel(kind: string): string {
  return GATE_KIND_LABEL[kind as GateKind] ?? kind.replaceAll("_", " ");
}

/** The agent-flow measures (docs/AGENT_EXECUTION.md §19) as stat cards — team-level only,
 *  never per person; thin data says so instead of showing a meaningless rate. */
export default function AgentFlowCards({ projectId }: { projectId: number }) {
  const flow = useQuery({
    queryKey: ["agent-flow", projectId],
    queryFn: () => api.get<AgentFlow>(`/projects/${projectId}/agent-flow?weeks=8`),
  });
  if (!flow.data) return null;
  const f = flow.data;
  const waits = Object.entries(f.human_wait.by_kind);
  const cards: { label: string; value: string; hint: string }[] = [
    {
      label: "Waiting on people",
      value: String(f.human_wait.open),
      hint: `open decisions · ${f.human_wait.open_past_reminder} past their reminder${
        f.queue.parked ? ` · ${f.queue.parked} for parked task(s)` : ""
      }`,
    },
    {
      label: "Time to decide",
      value: waits.length ? hoursText(waits[0][1].median_hours) : "—",
      hint: waits.length
        ? waits.map(([k, v]) => `${kindLabel(k)}: ${hoursText(v.median_hours)}`).join(" · ")
        : "No decisions in the window",
    },
    {
      label: "First-pass acceptance",
      value: percent(f.first_pass.reviews),
      hint: `reviews and QA · plans and sign-offs ${percent(f.first_pass.approvals)}`,
    },
    {
      label: "Rework",
      value: percent(f.rework.tasks_returned_share),
      hint: "of worked tasks went back at least once",
    },
    {
      label: "Flow efficiency",
      value: percent(f.flow_efficiency),
      hint: "time under a claim ÷ first claim to done",
    },
    {
      label: "Unassisted",
      value: percent(f.unassisted_share),
      hint: `of ${f.agent_tasks_done} agent task(s) done needed no person but sign-off`,
    },
  ];
  return (
    <section aria-label="Agent flow" className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-semibold">Agent flow · last {f.weeks} weeks</h2>
        <span className="text-xs text-slate-400">
          {f.claims.finished} session(s) finished · {f.gate_load.per_week} gate(s)/week
          {f.cost_per_task_usd != null ? ` · $${f.cost_per_task_usd}/task` : ""}
        </span>
      </div>
      {!f.sufficient && f.reason && <p className="text-xs text-amber-700">{f.reason}</p>}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        {cards.map((c) => (
          <div key={c.label} className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="text-xs text-slate-500">{c.label}</div>
            <div className="mt-0.5 text-xl font-semibold tabular-nums">{c.value}</div>
            <div className="mt-0.5 text-[11px] leading-snug text-slate-400">{c.hint}</div>
          </div>
        ))}
      </div>
      {f.gates_as_experiments.length > 0 && (
        <p className="text-xs text-slate-500">
          Gates as experiments:{" "}
          {f.gates_as_experiments
            .map((g) => `${kindLabel(g.kind)} approved ${percent(g.approval_rate)} in ${hoursText(g.median_hours)}`)
            .join(" · ")}
          . A gate approved nearly every time, quickly, isn’t protecting anything — narrow it.
        </p>
      )}
    </section>
  );
}
