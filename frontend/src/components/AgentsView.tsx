import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { AgentIntake, AgentsView as AgentsViewData, IntakeResponse } from "../api/types";
import {
  INTAKE_OPTIONS,
  claimLooksStale,
  claimSummary,
  gateLabel,
  heartbeatPhrase,
  reasonText,
  refusalText,
  waitedPhrase,
} from "../lib/execution";

/**
 * A project's agent work at a glance (docs/AGENT_EXECUTION.md §16): the intake switch (the
 * project's opt-in and kill switch), which columns agents work, what is ready by role and why
 * the rest isn't, the sessions working now, what waits on people, and what canopy parked.
 */
export default function AgentsView({
  projectId,
  onOpenTask,
}: {
  projectId: number;
  onOpenTask?: (taskId: number) => void;
}) {
  const qc = useQueryClient();
  const view = useQuery({
    queryKey: ["agents", projectId],
    queryFn: () => api.get<AgentsViewData>(`/projects/${projectId}/agents`),
  });
  const [stopped, setStopped] = useState<number | null>(null);
  const intake = useMutation({
    mutationFn: (state: AgentIntake) =>
      api.post<IntakeResponse>(`/projects/${projectId}/agent-intake`, { state }),
    onSuccess: (resp) => {
      setStopped(resp.agent_intake === "off" ? resp.stopped : null);
      void qc.invalidateQueries({ queryKey: ["agents", projectId] });
      void qc.invalidateQueries({ queryKey: ["board", projectId] });
      void qc.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });
  const release = useMutation({
    mutationFn: (claimId: number) =>
      api.post(`/work/claims/${claimId}/release`, {
        reason: "released by a planner",
        note: "A planner gave this task back to the queue from the Agents view.",
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agents", projectId] }),
  });

  if (view.isLoading) return <p className="text-sm text-slate-400">Loading agent work…</p>;
  if (view.isError || !view.data) {
    return <p className="text-sm text-red-700">{refusalText(view.error)}</p>;
  }
  const data = view.data;
  const agentStages = data.stages.filter((s) => s.worked_by);
  const roles = Object.keys(data.ready);
  const notReady = Object.entries(data.reasons).filter(([, n]) => n > 0);

  const setIntake = (state: AgentIntake) => {
    if (state === data.agent_intake) return;
    if (
      state === "off" &&
      data.working.length > 0 &&
      !window.confirm(
        `Switch agent intake off? ${data.working.length} running session${
          data.working.length === 1 ? " is" : "s are"
        } told to stop.`,
      )
    )
      return;
    intake.mutate(state);
  };

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold">Agent intake</h2>
            <p className="mt-0.5 max-w-xl text-sm text-slate-500">
              Delegated tasks are offered to agent sessions only while intake is on.{" "}
              {data.delegated === 0
                ? "Nothing is delegated yet — open a task and choose “Delegate to agents”."
                : `${data.delegated} task${data.delegated === 1 ? " is" : "s are"} delegated.`}
            </p>
          </div>
          <div role="radiogroup" aria-label="Agent intake" className="flex overflow-hidden rounded-md ring-1 ring-slate-200">
            {INTAKE_OPTIONS.map((o) => (
              <button
                key={o.value}
                role="radio"
                aria-checked={data.agent_intake === o.value}
                title={o.help}
                disabled={!data.can_manage || intake.isPending}
                onClick={() => setIntake(o.value)}
                className={`px-3 py-1.5 text-sm ${
                  data.agent_intake === o.value
                    ? o.value === "off"
                      ? "bg-slate-700 text-white"
                      : o.value === "paused"
                        ? "bg-amber-500 text-white"
                        : "bg-canopy-500 text-white"
                    : "bg-white text-slate-600 hover:bg-slate-50 disabled:hover:bg-white"
                } disabled:cursor-not-allowed`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          {INTAKE_OPTIONS.find((o) => o.value === data.agent_intake)?.help}
          {!data.can_manage && " Only the project’s planners can change it."}
        </p>
        {stopped !== null && stopped > 0 && (
          <p className="mt-1 text-xs text-slate-600">
            {stopped} running session{stopped === 1 ? " was" : "s were"} told to stop.
          </p>
        )}
        {intake.isError && (
          <p role="alert" className="mt-1 text-xs text-red-700">
            {refusalText(intake.error)}
          </p>
        )}
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="font-semibold">Who works which column</h2>
          {agentStages.length === 0 ? (
            <p className="mt-1 text-sm text-slate-500">
              No column is worked by agents: the workflow has no in-progress column.
            </p>
          ) : (
            <ul className="mt-2 space-y-1 text-sm">
              {agentStages.map((s) => (
                <li key={s.status} className="flex items-center gap-2">
                  <span className="font-medium">{s.status}</span>
                  <span className="rounded bg-violet-50 px-1.5 text-xs text-violet-700">
                    {s.worked_by === "human" ? "a person decides" : s.worked_by}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {!data.configured && (
            <p className="mt-2 text-xs text-slate-400">
              The built-in default: agents implement in the first in-progress column, pulling from
              the column before it, and hand off to the next one.
            </p>
          )}
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="font-semibold">Ready for agents</h2>
          {roles.every((r) => data.ready[r].length === 0) ? (
            <p className="mt-1 text-sm text-slate-500">
              {data.agent_intake === "on" ? "Nothing is ready right now." : "Intake isn’t on."}
            </p>
          ) : (
            roles.map((role) => (
              <div key={role} className="mt-2">
                <h3 className="text-xs font-medium uppercase tracking-wide text-slate-400">{role}</h3>
                <ul className="mt-1 space-y-0.5 text-sm">
                  {data.ready[role].map((item) => (
                    <li key={item.task_id}>
                      <button
                        type="button"
                        onClick={() => onOpenTask?.(item.task_id)}
                        className="text-left hover:text-canopy-700"
                      >
                        {item.key && <span className="mr-1 font-mono text-xs text-slate-400">{item.key}</span>}
                        {item.name}
                      </button>
                      <span className="ml-1 text-xs text-slate-400">
                        {item.pull ? `pulls into ${item.stage}` : `in ${item.stage}`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
          {notReady.length > 0 && (
            <div className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-500">
              <p className="font-medium text-slate-600">Delegated but not ready</p>
              <ul className="mt-0.5 space-y-0.5">
                {notReady.map(([reason, count]) => (
                  <li key={reason}>
                    {count} · {reasonText(reason)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="font-semibold">Working now</h2>
        {data.working.length === 0 ? (
          <p className="mt-1 text-sm text-slate-500">No agent session holds a task in this project.</p>
        ) : (
          <ul className="mt-2 divide-y divide-slate-100 text-sm">
            {data.working.map((w) => {
              const stale = claimLooksStale(w.heartbeat_age_s, w.claim.lease_minutes);
              return (
                <li key={w.claim.id} className="flex flex-wrap items-center gap-2 py-1.5">
                  <button
                    type="button"
                    onClick={() => onOpenTask?.(w.claim.task_id)}
                    className="text-left font-medium hover:text-canopy-700"
                  >
                    {w.task_key && <span className="mr-1 font-mono text-xs text-slate-400">{w.task_key}</span>}
                    {w.task_name}
                  </button>
                  <span className="text-xs text-slate-500">
                    {w.claim.agent_label ?? "agent"} · {claimSummary(w.claim)}
                  </span>
                  <span className={`text-xs ${stale ? "font-medium text-amber-700" : "text-slate-400"}`}>
                    checked in {heartbeatPhrase(w.heartbeat_age_s)}
                    {stale ? " — may have stopped" : ""}
                  </span>
                  {w.claim.progress_note && (
                    <span className="w-full text-xs italic text-slate-500">“{w.claim.progress_note}”</span>
                  )}
                  {data.can_manage && (
                    <button
                      type="button"
                      onClick={() => {
                        if (window.confirm("Give this task back to the queue? The session is told to stop."))
                          release.mutate(w.claim.id);
                      }}
                      className="ml-auto text-xs text-slate-400 hover:text-red-600"
                    >
                      Release
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {release.isError && (
          <p role="alert" className="mt-1 text-xs text-red-700">
            {refusalText(release.error)}
          </p>
        )}
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="font-semibold">Waiting on people</h2>
          {data.waiting.length === 0 ? (
            <p className="mt-1 text-sm text-slate-500">No agent work waits on a decision.</p>
          ) : (
            <ul className="mt-2 space-y-1 text-sm">
              {data.waiting.map((g) => (
                <li key={g.id}>
                  <Link to={`/reviews/gates/${g.id}`} className="hover:text-canopy-700">
                    <span className="mr-1 rounded bg-amber-100 px-1 text-xs text-amber-800">{gateLabel(g)}</span>
                    {g.task_key ? `${g.task_key} · ` : ""}
                    {g.title}
                  </Link>
                  <span className="ml-1 text-xs text-slate-400">{waitedPhrase(g.age_hours)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="font-semibold">Parked</h2>
          {data.parked.length === 0 ? (
            <p className="mt-1 text-sm text-slate-500">
              Nothing parked. A task parks when sessions keep failing to finish it.
            </p>
          ) : (
            <ul className="mt-2 space-y-1 text-sm">
              {data.parked.map((p) => (
                <li key={p.task_id}>
                  <Link to={`/reviews/gates/${p.gate_id}`} className="hover:text-canopy-700">
                    <span className="mr-1 rounded bg-red-100 px-1 text-xs text-red-700">parked</span>
                    {p.key ? `${p.key} · ` : ""}
                    {p.name}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <section className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-600">
        <h2 className="font-semibold text-slate-700">Running agent sessions</h2>
        <p className="mt-1">
          canopy offers the work; sessions come from wherever you run Claude. With the canopy
          plugin installed and an agent token from{" "}
          <Link to="/agent-setup" className="underline">
            Agent Setup
          </Link>
          , ask a session in the repository: <em>“Work on my next canopy task.”</em> For an
          unattended worker, run the same prompt headless (<code>claude -p</code>) on a schedule,
          one task per run.
        </p>
      </section>
    </div>
  );
}
