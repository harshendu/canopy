import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Gate, GateDecideRequest, GateDecision, GateDetail, TaskArtifact } from "../api/types";
import {
  DECISION_EFFECT,
  DECISION_LABEL,
  artifactLabel,
  decisionNeedsNote,
  decisionsFor,
  decisionTone,
  eventText,
  gateLabel,
  isParked,
  refusalText,
  waitedPhrase,
} from "../lib/execution";
import { timeAgo } from "../lib/proposals";
import { PageHeader } from "../components/PageHeader";

/**
 * One gate, decided by a person (docs/AGENT_EXECUTION.md §9.4): what is asked and why, the work
 * it judges (the plan or hand-off revision, with the one before it), the evidence canopy saw,
 * and the trail — then the decision. The decision names the revision you looked at, so a
 * change made while you read is caught (`stale_subject`) rather than approved unseen.
 * Everything an agent wrote is shown as text, never as instructions to you.
 */
export default function GateReview() {
  const { gateId } = useParams();
  const id = Number(gateId);
  const detail = useQuery({
    queryKey: ["gate", id],
    queryFn: () => api.get<GateDetail>(`/gates/${id}`),
    enabled: Number.isFinite(id),
  });

  if (detail.isLoading) return <p className="text-sm text-slate-400">Loading…</p>;
  if (detail.isError || !detail.data) {
    return (
      <div className="space-y-4">
        <PageHeader
          breadcrumbs={[{ label: "Reviews", to: "/reviews?tab=decisions" }, { label: "Decision" }]}
          title="Decision"
        />
        <p className="text-sm text-red-700">{refusalText(detail.error)}</p>
      </div>
    );
  }
  const { gate, task, subject, previous, handoff, reviews, trail } = detail.data;
  const pr = (gate.evidence?.pull_request ?? null) as Record<string, unknown> | null;

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[
          { label: "Reviews", to: "/reviews?tab=decisions" },
          { label: `${gateLabel(gate)}${gate.task_key ? ` · ${gate.task_key}` : ""}` },
        ]}
        title={gate.title}
        subtitle={
          <>
            {gateLabel(gate)} on{" "}
            <Link to={`/projects/${gate.project_id}?tab=board`} className="underline">
              {task.key ? `${task.key} ` : ""}
              {task.name}
            </Link>
            {gate.stage ? ` · held in ${gate.stage}` : ""} ·{" "}
            {gate.status === "open"
              ? `waiting ${waitedPhrase(gate.age_hours)}`
              : `${gate.status.replaceAll("_", " ")} ${timeAgo(gate.decided_at)}`}
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-5">
          {gate.prompt && (
            <section className="rounded-lg border border-slate-200 bg-white p-4">
              <h2 className="text-sm font-semibold text-slate-700">
                {gate.kind === "question" ? "The question" : isParked(gate) ? "What happened" : "What is asked"}
              </h2>
              <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">{gate.prompt}</p>
              {gate.requester_name && gate.origin === "agent" && (
                <p className="mt-2 text-xs text-slate-400">
                  From an agent session acting for {gate.requester_name}.
                </p>
              )}
            </section>
          )}
          {gate.reasons.length > 0 && (
            <section className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              <h2 className="font-semibold">Why a person is asked</h2>
              <ul className="mt-1 list-disc pl-5">
                {gate.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </section>
          )}
          {subject && <ArtifactPanel title="Under review" artifact={subject} previous={previous} />}
          {handoff && handoff.id !== subject?.id && (
            <ArtifactPanel title="The hand-off" artifact={handoff} previous={null} />
          )}
          {reviews.map((r) => (
            <ArtifactPanel key={r.id} title={`The ${artifactLabel(r.kind)}`} artifact={r} previous={null} />
          ))}
          {pr && (
            <section className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
              <h2 className="font-semibold text-slate-700">Pull request</h2>
              <p className="mt-1 text-slate-600">
                {typeof pr.url === "string" ? (
                  <a href={pr.url} target="_blank" rel="noreferrer" className="underline">
                    {String(pr.repo)}#{String(pr.number)} ↗
                  </a>
                ) : (
                  `${String(pr.repo)}#${String(pr.number)}`
                )}{" "}
                · {pr.merged ? "merged" : String(pr.state)}
                {pr.checks_state ? ` · checks ${String(pr.checks_state)}` : ""}
                {pr.review_decision ? ` · ${String(pr.review_decision).replaceAll("_", " ")}` : ""}
                {typeof pr.changed_lines === "number" ? ` · ${pr.changed_lines} lines changed` : ""}
              </p>
            </section>
          )}
          <section>
            <h2 className="text-sm font-semibold text-slate-700">Trail</h2>
            <ol className="mt-2 space-y-1 border-l border-slate-200 pl-3 text-xs text-slate-600">
              {trail.map((e) => (
                <li key={e.id}>
                  <span className="text-slate-400">{timeAgo(e.at)}</span> · {eventText(e)}
                  {e.actor_kind === "agent" && (
                    <span className="ml-1 rounded bg-violet-50 px-1 text-[10px] text-violet-700">agent</span>
                  )}
                </li>
              ))}
            </ol>
          </section>
        </div>

        <aside className="space-y-4">
          {gate.status === "open" ? (
            gate.may_decide ? (
              <DecideForm gate={gate} subject={subject} />
            ) : (
              <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600">
                <p className="font-medium text-slate-700">You can’t decide this one.</p>
                <p className="mt-1">
                  {gate.exclude_requester
                    ? "The person whose agent did the work can’t approve it — someone else decides. "
                    : ""}
                  It’s for {approversText(gate)}.
                </p>
              </div>
            )
          ) : (
            <Decided gate={gate} />
          )}
        </aside>
      </div>
    </div>
  );
}

function approversText(gate: Gate): string {
  const who: Record<string, string> = {
    project_planners: "the project’s planners",
    assignee_or_planners: "the task’s assignee or the project’s planners",
    assignee: "the task’s assignee",
    project_owner: "the project’s owner",
    initiative_leads: "the initiative’s owners",
    team_directors: "the team’s directors",
    engineers: "the people it was handed to",
  };
  const base = who[gate.approvers] ?? gate.approvers;
  return gate.escalation_level > 0 ? `${base} (escalated: more people may decide now)` : base;
}

function DecideForm({ gate, subject }: { gate: Gate; subject: TaskArtifact | null }) {
  const qc = useQueryClient();
  const choices = decisionsFor(gate);
  const [decision, setDecision] = useState<GateDecision | null>(
    gate.kind === "question" ? "answer" : null,
  );
  const [option, setOption] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: (body: GateDecideRequest) => api.post<Gate>(`/gates/${gate.id}/decide`, body),
    onSuccess: () => {
      void qc.invalidateQueries();
    },
  });
  const needsNote = decision !== null && decisionNeedsNote(decision);
  const isAnswer = decision === "answer";
  const ready =
    decision !== null &&
    (!needsNote || note.trim().length > 0) &&
    (!isAnswer || option !== null || (gate.allow_text && note.trim().length > 0));

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready || decision === null) return;
        decide.mutate({
          decision,
          note: note.trim() || null,
          option: isAnswer ? option : null,
          subject_revision: subject?.revision ?? null,
        });
      }}
      className="space-y-3 rounded-lg border border-slate-200 bg-white p-4"
    >
      <h2 className="text-sm font-semibold text-slate-700">Your decision</h2>
      <div className="flex flex-col gap-1.5">
        {choices.map((d) => {
          const tone = decisionTone(d);
          const active = decision === d;
          return (
            <label
              key={d}
              className={`cursor-pointer rounded border px-2.5 py-1.5 text-sm ${
                active
                  ? tone === "danger"
                    ? "border-red-400 bg-red-50"
                    : "border-canopy-500 bg-canopy-50"
                  : "border-slate-200 hover:bg-slate-50"
              }`}
            >
              <input
                type="radio"
                name="decision"
                value={d}
                checked={active}
                onChange={() => setDecision(d)}
                className="sr-only"
              />
              <span className="font-medium">{DECISION_LABEL[d]}</span>
              <span className="block text-xs text-slate-500">{DECISION_EFFECT[d]}</span>
            </label>
          );
        })}
      </div>
      {isAnswer && gate.options.length > 0 && (
        <fieldset>
          <legend className="text-xs font-medium text-slate-600">Pick an answer</legend>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {gate.options.map((o) => (
              <button
                key={o.value}
                type="button"
                aria-pressed={option === o.value}
                onClick={() => setOption(option === o.value ? null : o.value)}
                className={`rounded-full px-2.5 py-1 text-xs ${
                  option === o.value
                    ? "bg-canopy-500 text-white"
                    : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
                }`}
              >
                {o.label || o.value}
              </button>
            ))}
          </div>
        </fieldset>
      )}
      {(decision !== null && decision !== "take_over") || isAnswer ? (
        <div>
          <label htmlFor="gate-note" className="text-xs font-medium text-slate-600">
            {isAnswer
              ? gate.allow_text
                ? "Your answer (or a note with the option)"
                : "A note (optional)"
              : needsNote
                ? "What should change (required)"
                : "A note (optional)"}
          </label>
          <textarea
            id="gate-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={4}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <p className="mt-0.5 text-[11px] text-slate-400">The next session reads this in its brief.</p>
        </div>
      ) : null}
      {decide.isError && (
        <p role="alert" className="rounded bg-red-50 px-2 py-1 text-xs text-red-700">
          {refusalText(decide.error)}
        </p>
      )}
      <button
        type="submit"
        disabled={!ready || decide.isPending}
        className="w-full rounded bg-canopy-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-canopy-700 disabled:opacity-50"
      >
        {decide.isPending ? "Recording…" : decision ? DECISION_LABEL[decision] : "Choose a decision"}
      </button>
    </form>
  );
}

function Decided({ gate }: { gate: Gate }) {
  return (
    <div className="space-y-1 rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600">
      <p className="font-medium text-slate-700">
        {gate.decision ? DECISION_LABEL[gate.decision] : gate.status}
        {gate.decided_by_label ? ` — ${gate.decided_by_label}` : ""}
      </p>
      <p className="text-xs text-slate-400">
        {timeAgo(gate.decided_at)}
        {gate.decided_via && gate.decided_via !== "canopy"
          ? ` · via ${gate.decided_via.replaceAll("_", " ")}`
          : ""}
      </p>
      {typeof gate.response_data?.option === "string" && (
        <p>
          Answer: <span className="font-medium">{gate.response_data.option}</span>
        </p>
      )}
      {gate.response_note && <p className="whitespace-pre-wrap">“{gate.response_note}”</p>}
      {gate.waiting_for_evidence && (
        <p className="text-amber-700">
          Approved — the task moves on once the next column’s checks are met (e.g. the PR merges).
        </p>
      )}
    </div>
  );
}

function ArtifactPanel({
  title,
  artifact,
  previous,
}: {
  title: string;
  artifact: TaskArtifact;
  previous: TaskArtifact | null;
}) {
  const [showPrevious, setShowPrevious] = useState(false);
  const d = artifact.data;
  const list = (key: string): string[] =>
    Array.isArray(d[key]) ? (d[key] as unknown[]).map((v) => String(v)) : [];
  const steps = Array.isArray(d.steps) ? (d.steps as { content?: string }[]) : [];
  const findings = Array.isArray(d.findings)
    ? (d.findings as { severity?: string; note?: string; path?: string }[])
    : [];
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold text-slate-700">
          {title}: {artifactLabel(artifact.kind)} revision {artifact.revision}
          {artifact.verdict ? ` · ${artifact.verdict}` : ""}
        </h2>
        <span className="text-xs text-slate-400">
          {artifact.author_kind === "agent" ? "by an agent · " : ""}
          {timeAgo(artifact.created_at)}
        </span>
      </div>
      {typeof d.summary === "string" && <p className="mt-2 font-medium text-slate-700">{d.summary}</p>}
      <p className="mt-2 whitespace-pre-wrap text-slate-700">{artifact.body}</p>
      {steps.length > 0 && (
        <ol className="mt-2 list-decimal pl-5 text-slate-600">
          {steps.map((s, i) => (
            <li key={i}>{s.content}</li>
          ))}
        </ol>
      )}
      <dl className="mt-2 grid grid-cols-[8rem_1fr] gap-x-2 gap-y-1 text-xs">
        {list("change_classes").length > 0 && (
          <>
            <dt className="text-slate-400">Change classes</dt>
            <dd>{list("change_classes").join(", ").replaceAll("_", " ")}</dd>
          </>
        )}
        {list("affected_paths").length > 0 && (
          <>
            <dt className="text-slate-400">Touches</dt>
            <dd className="font-mono">{list("affected_paths").join(", ")}</dd>
          </>
        )}
        {typeof d.confidence === "string" && (
          <>
            <dt className="text-slate-400">Confidence</dt>
            <dd>{d.confidence}</dd>
          </>
        )}
        {list("risks").length > 0 && (
          <>
            <dt className="text-slate-400">Risks</dt>
            <dd>{list("risks").join("; ")}</dd>
          </>
        )}
        {typeof d.test_plan === "string" && d.test_plan && (
          <>
            <dt className="text-slate-400">Test plan</dt>
            <dd>{d.test_plan}</dd>
          </>
        )}
        {list("known_gaps").length > 0 && (
          <>
            <dt className="text-slate-400">Known gaps</dt>
            <dd>{list("known_gaps").join("; ")}</dd>
          </>
        )}
      </dl>
      {findings.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs">
          {findings.map((f, i) => (
            <li key={i} className="rounded bg-slate-50 px-2 py-1">
              <span className="font-medium uppercase text-slate-500">{f.severity}</span> {f.path ? `${f.path}: ` : ""}
              {f.note}
            </li>
          ))}
        </ul>
      )}
      {previous && (
        <div className="mt-3 border-t border-slate-100 pt-2">
          <button
            type="button"
            onClick={() => setShowPrevious((v) => !v)}
            aria-expanded={showPrevious}
            className="text-xs text-slate-500 hover:text-slate-700"
          >
            {showPrevious ? "Hide" : "Show"} revision {previous.revision}
          </button>
          {showPrevious && (
            <p className="mt-1 whitespace-pre-wrap text-xs text-slate-500">{previous.body}</p>
          )}
        </div>
      )}
    </section>
  );
}
