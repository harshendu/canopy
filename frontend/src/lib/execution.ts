import type {
  AgentIntake,
  ArtifactKind,
  ClaimOutcome,
  Gate,
  GateDecision,
  GateKind,
  WorkClaim,
  WorkEvent,
} from "../api/types";

/**
 * Agent work in plain language (docs/AGENT_EXECUTION.md §16): gate kinds and decisions, claim
 * outcomes, why a delegated task isn't moving, and the execution timeline's events. Pure, so
 * the wording is unit-tested and shared by the board, the task panel, the inbox and the Agents
 * view.
 */

export const GATE_KIND_LABEL: Record<GateKind, string> = {
  plan_approval: "Plan approval",
  handoff_approval: "Hand-off approval",
  signoff: "Sign-off",
  question: "Question",
  escalation: "Escalation",
};

/** A gate canopy itself opened because sessions kept failing (attempts used up, a review loop
 *  not converging) — shown as "Parked", not as an agent's escalation. */
export function isParked(gate: Pick<Gate, "kind" | "origin">): boolean {
  return gate.kind === "escalation" && gate.origin === "system";
}

export function gateLabel(gate: Pick<Gate, "kind" | "origin">): string {
  return isParked(gate) ? "Parked" : (GATE_KIND_LABEL[gate.kind] ?? gate.kind);
}

export const DECISION_LABEL: Record<GateDecision, string> = {
  approve: "Approve",
  edit_and_approve: "Edit and approve",
  approve_with_conditions: "Approve with conditions",
  request_changes: "Request changes",
  reject: "Reject",
  answer: "Answer",
  retry: "Retry with guidance",
  take_over: "Take it over",
  cancelled: "Withdrawn",
};

/** What each response does, said before the person clicks it. */
export const DECISION_EFFECT: Record<GateDecision, string> = {
  approve: "The task moves on.",
  edit_and_approve: "Your version of the plan is recorded and approved.",
  approve_with_conditions: "The task moves on; your conditions go into the next brief.",
  request_changes: "Back to the work column with your note in the next brief.",
  reject: "The task is cancelled.",
  answer: "The task is offered again with your answer in its brief.",
  retry: "Attempts reset; the next session gets your guidance.",
  take_over: "The task leaves the queue and stays with its assignee.",
  cancelled: "",
};

const NOTE_REQUIRED = new Set<GateDecision>(["request_changes", "reject", "retry"]);

export function decisionNeedsNote(decision: GateDecision): boolean {
  return NOTE_REQUIRED.has(decision);
}

export type DecisionTone = "primary" | "danger" | "neutral";

export function decisionTone(decision: GateDecision): DecisionTone {
  if (decision === "approve" || decision === "answer" || decision === "retry") return "primary";
  if (decision === "reject") return "danger";
  return "neutral";
}

/** The responses the decide form offers, in order. Editing a plan inline isn't offered here
 *  (a planner records their own plan revision as a note instead). */
export function decisionsFor(gate: Pick<Gate, "allowed_decisions">): GateDecision[] {
  return gate.allowed_decisions.filter((d) => d !== "edit_and_approve" && d !== "cancelled");
}

export const OUTCOME_LABEL: Record<ClaimOutcome, string> = {
  advanced: "handed off",
  returned: "sent back for rework",
  gated: "waiting on a person",
  released: "gave it back",
  failed: "needs a person",
  expired: "lease expired",
  superseded: "stopped",
};

const END_REASON_TEXT: Record<string, string> = {
  moved_by_person: "a person moved the card",
  taken_over: "a person took it over",
  undelegated: "it was taken back from agents",
  intake_off: "agent intake was switched off",
  merged_ahead: "its PR was merged",
  cancelled: "it was cancelled",
  expired: "the session stopped checking in",
};

/** "implementer · attempt 2 · handed off" — one line for a claim. */
export function claimSummary(
  claim: Pick<WorkClaim, "role" | "attempt" | "state" | "outcome" | "end_reason">,
): string {
  const parts = [claim.role, `attempt ${claim.attempt}`];
  if (claim.state === "active") parts.push("working");
  else if (claim.outcome) {
    const reason = claim.end_reason ? END_REASON_TEXT[claim.end_reason] : undefined;
    parts.push(
      claim.outcome === "superseded" && reason
        ? `stopped: ${reason}`
        : (OUTCOME_LABEL[claim.outcome] ?? claim.outcome),
    );
  }
  return parts.join(" · ");
}

/** "just now" | "4 min ago" | "2 h ago" for a heartbeat age in seconds. */
export function heartbeatPhrase(seconds: number): string {
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  return `${Math.floor(minutes / 60)} h ago`;
}

/** A session is probably gone when it hasn't checked in for half its lease. */
export function claimLooksStale(heartbeatAgeS: number, leaseMinutes = 30): boolean {
  return heartbeatAgeS > (leaseMinutes * 60) / 2;
}

/** "45 min" | "6 h" | "3 d" — how long a gate has waited. */
export function waitedPhrase(hours: number): string {
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 48) return `${Math.round(hours)} h`;
  return `${Math.round(hours / 24)} d`;
}

export const READINESS_REASON_TEXT: Record<string, string> = {
  intake_off: "Agent intake is off for this project",
  intake_paused: "Agent intake is paused",
  not_delegated: "Not delegated to agents",
  closed: "Already done or cancelled",
  not_in_stage: "Not in a column an agent works",
  claimed: "A session is working on it",
  gate_open: "Waiting for a person to decide",
  blocked: "Blocked",
  waiting_on_dependencies: "Waiting on its dependencies",
  checks_failed: "The column's entry checks aren't met",
  wip_limit: "The column is at its WIP limit",
  parked: "Parked — its attempts are used up",
  not_in_sprint: "Not in the active sprint",
  not_permitted: "Assigned to someone else",
  role_not_allowed: "No token may work that role",
  no_accountable_owner: "Nobody is accountable — assign it first",
  same_actor: "Needs a different session than the one before",
};

export function reasonText(code: string | null | undefined): string {
  if (!code) return "";
  return READINESS_REASON_TEXT[code] ?? code.replaceAll("_", " ");
}

export const INTAKE_OPTIONS: { value: AgentIntake; label: string; help: string }[] = [
  {
    value: "on",
    label: "On",
    help: "Delegated tasks are offered to agent sessions.",
  },
  {
    value: "paused",
    label: "Paused",
    help: "Nothing new is offered; sessions already working finish.",
  },
  {
    value: "off",
    label: "Off",
    help: "The kill switch: nothing is offered and running sessions are told to stop.",
  },
];

const ARTIFACT_LABEL: Record<ArtifactKind, string> = {
  plan: "plan",
  handoff: "hand-off",
  review: "review",
  qa_report: "QA report",
  note: "note",
};

export function artifactLabel(kind: ArtifactKind): string {
  return ARTIFACT_LABEL[kind] ?? kind;
}

function str(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

/** One line for an execution-timeline event. */
export function eventText(event: Pick<WorkEvent, "kind" | "data">): string {
  const d = event.data ?? {};
  switch (event.kind) {
    case "delegated":
      if (d.taken_over) return "A person took the task over";
      return d.delegation ? "Delegated to agents" : "Taken back from agents";
    case "intake_changed":
      return `Agent intake switched ${str(d.from)} → ${str(d.to)}`;
    case "components_changed":
      return "Components updated";
    case "claimed":
      return `Claimed as ${str(d.role)} in ${str(d.stage)} (attempt ${str(d.attempt)})${
        d.pulled ? " — pulled into the column" : ""
      }`;
    case "claim_ended": {
      const outcome = str(d.outcome) as ClaimOutcome;
      const reason = d.reason ? END_REASON_TEXT[str(d.reason)] : undefined;
      return `Claim ended: ${OUTCOME_LABEL[outcome] ?? outcome}${reason ? ` (${reason})` : ""}`;
    }
    case "artifact_added":
      return `Added a ${artifactLabel(str(d.kind) as ArtifactKind)} (revision ${str(d.revision)})`;
    case "checks_evaluated": {
      if (d.replayed) return "Hand-off replayed";
      const failures = Array.isArray(d.failures) ? d.failures.length : 0;
      return failures
        ? `Checks for ${str(d.target)}: ${failures} not met`
        : `Checks for ${str(d.target)} passed`;
    }
    case "advanced":
      return `Moved ${str(d.from)} → ${str(d.to)}`;
    case "returned":
      return `Sent back to ${str(d.to)} for rework`;
    case "gate_opened":
      return `Asked a person: ${GATE_KIND_LABEL[str(d.kind) as GateKind] ?? str(d.kind)}`;
    case "gate_decided": {
      const decision = str(d.decision) as GateDecision;
      const via = str(d.via);
      return `Decided: ${DECISION_LABEL[decision] ?? decision}${
        via && via !== "canopy" ? ` (via ${via.replace("_", " ")})` : ""
      }`;
    }
    case "gate_escalated":
      return `Escalated — more people may decide now (level ${str(d.level)})`;
    case "gate_reassigned":
      return "Decision reassigned";
    case "override":
      return `Checks overridden by a planner: ${str(d.reason)}`;
    case "merged_ahead_of_stage":
      return "PR merged while the task was upstream — moved to done";
    case "moved_without_clearance":
      return "Moved in the tracker without canopy's clearance";
    case "policy_changed":
      return "Stage policy changed";
    default:
      return event.kind.replaceAll("_", " ");
  }
}

/** The human-readable part of a refused call: FastAPI sends `{"detail": "..."}` or
 *  `{"detail": {"code", "message", ...}}`; anything else is shown as it came. */
export function refusalText(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error ?? "");
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    const detail = parsed.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      return String((detail as { message: unknown }).message);
    }
  } catch {
    // not JSON — fall through
  }
  return raw;
}
