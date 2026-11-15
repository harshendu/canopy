import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { DelegationResponse, Task, TaskArtifact, TaskExecution } from "../api/types";
import {
  artifactLabel,
  claimSummary,
  eventText,
  gateLabel,
  heartbeatPhrase,
  reasonText,
  refusalText,
  trackerMoveText,
  waitedPhrase,
} from "../lib/execution";
import { timeAgo } from "../lib/proposals";

/**
 * A task's agent work (docs/AGENT_EXECUTION.md §16): delegate it to the work queue or take it
 * back, see why it is or isn't moving, the session working it, what waits on a person, the
 * latest plan and hand-off, the timeline — and leave guidance for the next attempt. Every
 * write here is a person's (the API refuses agent tokens for delegation and take-over).
 */
export default function ExecutionSection({
  task,
  projectId,
  mayContribute,
}: {
  task: Task;
  projectId: number;
  mayContribute: boolean;
}) {
  const qc = useQueryClient();
  const [hints, setHints] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [showAll, setShowAll] = useState(false);
  const execution = useQuery({
    queryKey: ["task-execution", task.id],
    queryFn: () => api.get<TaskExecution>(`/tasks/${task.id}/execution`),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["task-execution", task.id] });
    void qc.invalidateQueries({ queryKey: ["task", task.id] });
    void qc.invalidateQueries({ queryKey: ["board", projectId] });
    void qc.invalidateQueries({ queryKey: ["agents", projectId] });
  };
  const delegate = useMutation({
    mutationFn: (delegation: "agent" | null) =>
      api.post<DelegationResponse>(`/tasks/${task.id}/delegation`, { delegation }),
    onSuccess: (resp) => {
      setHints(resp.hints);
      refresh();
    },
  });
  const takeOver = useMutation({
    mutationFn: () => api.post<Task>(`/tasks/${task.id}/take-over`),
    onSuccess: () => {
      setHints([]);
      refresh();
    },
  });
  const addNote = useMutation({
    mutationFn: () => api.post<TaskArtifact>(`/tasks/${task.id}/artifacts`, { kind: "note", body: note }),
    onSuccess: () => {
      setNote("");
      refresh();
    },
  });

  if (task.type === "summary") return null;
  const data = execution.data;
  const delegated = (data?.delegation ?? task.delegation) === "agent";
  const mirrored = task.status_owner !== "canopy";
  const error = delegate.error ?? takeOver.error ?? addNote.error;
  const plan = latest(data?.artifacts ?? [], "plan");
  const handoff = latest(data?.artifacts ?? [], "handoff");
  const openGates = (data?.gates ?? []).filter((g) => g.status === "open");
  const events = data?.events ?? [];
  const shown = showAll ? events : events.slice(-6);

  return (
    <section aria-labelledby="execution-heading" className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 id="execution-heading" className="text-sm font-semibold text-slate-700">
          Agent work
        </h3>
        {mayContribute && (
          <div className="flex gap-2">
            {delegated ? (
              <button
                type="button"
                onClick={() => {
                  if (
                    window.confirm(
                      "Take this task back from agents? Any running session is told to stop and open questions close.",
                    )
                  )
                    takeOver.mutate();
                }}
                disabled={takeOver.isPending}
                className="rounded border border-slate-300 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
              >
                Take it back
              </button>
            ) : (
              <button
                type="button"
                onClick={() => delegate.mutate("agent")}
                disabled={delegate.isPending}
                className="rounded bg-violet-600 px-2 py-1 text-xs font-medium text-white hover:bg-violet-700 disabled:opacity-50"
              >
                Delegate to agents
              </button>
            )}
          </div>
        )}
      </div>

      {error && (
        <p role="alert" className="rounded bg-red-50 px-2 py-1 text-xs text-red-700">
          {refusalText(error)}
        </p>
      )}

      {!delegated ? (
        <p className="text-xs text-slate-500">
          Not delegated. Delegating offers the task to agent sessions while the project's agent intake is on; its
          assignee stays accountable.
          {mirrored &&
            " Its status stays its tracker's: canopy clears each move and the session (or the tracker's automation) makes it."}
        </p>
      ) : (
        <Readiness data={data} />
      )}

      {hints.length > 0 && (
        <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-900">
          <p className="font-medium">Delegated — a few things would help an agent:</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {hints.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
        </div>
      )}

      {data?.tracker_transition && (
        <div className="rounded border border-sky-200 bg-sky-50 px-2 py-1.5 text-xs text-sky-900">
          <p className="font-medium">{trackerMoveText(data.tracker_transition)}</p>
          <p className="text-sky-800">
            canopy cleared it — it never changes a tracker's status itself. Nothing is offered to agents until the
            tracker shows the move.
          </p>
        </div>
      )}

      {data?.active_claim && (
        <div className="rounded border border-violet-200 bg-violet-50 px-2 py-1.5 text-xs text-violet-900">
          <p className="font-medium">
            {data.active_claim.agent_label ?? "An agent session"} is working on it
          </p>
          <p className="text-violet-800">
            {claimSummary(data.active_claim)} · checked in{" "}
            {heartbeatPhrase(secondsSince(data.active_claim.heartbeat_at))}
          </p>
          {data.active_claim.progress_note && (
            <p className="mt-0.5 italic">“{data.active_claim.progress_note}”</p>
          )}
          {data.active_claim.pr_url && (
            <a href={data.active_claim.pr_url} target="_blank" rel="noreferrer" className="underline">
              pull request ↗
            </a>
          )}
        </div>
      )}

      {openGates.map((g) => (
        <Link
          key={g.id}
          to={`/reviews/gates/${g.id}`}
          className="block rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-900 hover:border-amber-400"
        >
          <span className="font-medium">{gateLabel(g)}</span> · waiting {waitedPhrase(g.age_hours)} —{" "}
          {g.title}
          <span className="ml-1 text-amber-700">{g.may_decide ? "Decide →" : "View →"}</span>
        </Link>
      ))}

      {plan && <ArtifactCard artifact={plan} />}
      {handoff && <ArtifactCard artifact={handoff} />}

      {events.length > 0 && (
        <div>
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-medium uppercase tracking-wide text-slate-400">Timeline</h4>
            {events.length > 6 && (
              <button
                type="button"
                onClick={() => setShowAll((v) => !v)}
                className="text-xs text-slate-500 hover:text-slate-700"
              >
                {showAll ? "Show recent" : `Show all ${events.length}`}
              </button>
            )}
          </div>
          <ol className="mt-1 space-y-1 border-l border-slate-200 pl-3 text-xs">
            {shown.map((e) => (
              <li key={e.id} className="text-slate-600">
                <span className="text-slate-400">{timeAgo(e.at)}</span> · {eventText(e)}
                {e.actor_kind === "agent" && (
                  <span className="ml-1 rounded bg-violet-50 px-1 text-[10px] text-violet-700">agent</span>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}

      {delegated && mayContribute && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (note.trim()) addNote.mutate();
          }}
          className="space-y-1"
        >
          <label htmlFor="agent-note" className="text-xs font-medium text-slate-600">
            Guidance for the next session
          </label>
          <textarea
            id="agent-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder="e.g. Use the sandbox account; the flaky test is in the timer"
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <button
            type="submit"
            disabled={!note.trim() || addNote.isPending}
            className="rounded border border-slate-300 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
          >
            Add note
          </button>
        </form>
      )}
    </section>
  );
}

function Readiness({ data }: { data: TaskExecution | undefined }) {
  if (!data) return <p className="text-xs text-slate-400">Loading…</p>;
  const roles = Object.entries(data.readiness?.by_role ?? {});
  const intake = data.readiness?.intake ?? "off";
  return (
    <div className="space-y-1 text-xs text-slate-600">
      <p>
        Delegated to agents
        {data.stage ? (
          <>
            {" "}
            · in <span className="font-medium">{data.stage}</span>
            {data.worked_by && data.worked_by !== "human" ? ` (worked by ${data.worked_by})` : ""}
          </>
        ) : null}
      </p>
      {intake !== "on" && (
        <p className="text-amber-700">
          {reasonText(intake === "paused" ? "intake_paused" : "intake_off")} — a planner changes it
          in the project’s Agents view.
        </p>
      )}
      {intake === "on" &&
        roles.map(([role, r]) => (
          <p key={role}>
            <span className="font-medium">{role}:</span>{" "}
            {r.ready ? (
              <span className="text-emerald-700">ready to claim{r.stage ? ` in ${r.stage}` : ""}</span>
            ) : (
              <span className={r.reason === "not_in_stage" ? "text-slate-400" : "text-slate-600"}>
                {reasonText(r.reason)}
                {r.detail ? ` (${r.detail})` : ""}
              </span>
            )}
          </p>
        ))}
    </div>
  );
}

function ArtifactCard({ artifact }: { artifact: TaskArtifact }) {
  const [open, setOpen] = useState(false);
  const steps = Array.isArray(artifact.data.steps)
    ? (artifact.data.steps as { content?: string; status?: string }[])
    : [];
  const summary =
    artifact.kind === "handoff" && typeof artifact.data.summary === "string"
      ? artifact.data.summary
      : null;
  return (
    <div className="rounded border border-slate-200 px-2 py-1.5 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between text-left"
      >
        <span className="font-medium text-slate-700">
          Latest {artifactLabel(artifact.kind)} · revision {artifact.revision}
          {artifact.author_kind === "agent" ? " · by an agent" : ""}
        </span>
        <span className="text-slate-400">{timeAgo(artifact.created_at)}</span>
      </button>
      {summary && <p className="mt-1 text-slate-600">{summary}</p>}
      {open && (
        <div className="mt-1 space-y-1 text-slate-600">
          <p className="whitespace-pre-wrap">{artifact.body}</p>
          {steps.length > 0 && (
            <ul className="space-y-0.5">
              {steps.map((s, i) => (
                <li key={i}>
                  <span aria-hidden>{s.status === "completed" ? "☑" : "☐"}</span> {s.content}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function latest(artifacts: TaskArtifact[], kind: TaskArtifact["kind"]): TaskArtifact | undefined {
  return artifacts.filter((a) => a.kind === kind).sort((a, b) => b.revision - a.revision)[0];
}

function secondsSince(iso: string): number {
  const at = new Date(iso.endsWith("Z") ? iso : `${iso}Z`).getTime();
  return Math.max(0, Math.round((Date.now() - at) / 1000));
}
