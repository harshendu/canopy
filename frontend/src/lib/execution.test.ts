import { describe, expect, it } from "vitest";

import {
  claimLooksStale,
  claimSummary,
  decisionNeedsNote,
  decisionsFor,
  decisionTone,
  eventText,
  gateLabel,
  heartbeatPhrase,
  isParked,
  reasonText,
  refusalText,
  waitedPhrase,
} from "./execution";

describe("gates", () => {
  it("calls a system escalation 'Parked' and names the other kinds", () => {
    expect(isParked({ kind: "escalation", origin: "system" })).toBe(true);
    expect(gateLabel({ kind: "escalation", origin: "system" })).toBe("Parked");
    expect(gateLabel({ kind: "escalation", origin: "agent" })).toBe("Escalation");
    expect(gateLabel({ kind: "plan_approval", origin: "checkpoint" })).toBe("Plan approval");
  });

  it("offers the allowed decisions, without inline plan editing", () => {
    expect(
      decisionsFor({ allowed_decisions: ["approve", "edit_and_approve", "request_changes"] }),
    ).toEqual(["approve", "request_changes"]);
  });

  it("asks for a note where the decision needs one", () => {
    expect(decisionNeedsNote("request_changes")).toBe(true);
    expect(decisionNeedsNote("retry")).toBe(true);
    expect(decisionNeedsNote("approve")).toBe(false);
    expect(decisionTone("reject")).toBe("danger");
    expect(decisionTone("answer")).toBe("primary");
    expect(decisionTone("take_over")).toBe("neutral");
  });
});

describe("claims", () => {
  it("summarises a claim in one line", () => {
    const base = { role: "implementer", attempt: 2, end_reason: null };
    expect(claimSummary({ ...base, state: "active", outcome: null })).toBe(
      "implementer · attempt 2 · working",
    );
    expect(claimSummary({ ...base, state: "completed", outcome: "advanced" })).toBe(
      "implementer · attempt 2 · handed off",
    );
    expect(
      claimSummary({
        ...base,
        state: "superseded",
        outcome: "superseded",
        end_reason: "moved_by_person",
      }),
    ).toBe("implementer · attempt 2 · stopped: a person moved the card");
  });

  it("phrases heartbeat ages and spots a session that went quiet", () => {
    expect(heartbeatPhrase(20)).toBe("just now");
    expect(heartbeatPhrase(4 * 60 + 5)).toBe("4 min ago");
    expect(heartbeatPhrase(2 * 3600 + 10)).toBe("2 h ago");
    expect(claimLooksStale(10 * 60)).toBe(false);
    expect(claimLooksStale(16 * 60)).toBe(true);
    expect(claimLooksStale(16 * 60, 60)).toBe(false);
  });

  it("phrases how long a gate has waited", () => {
    expect(waitedPhrase(0.2)).toBe("12 min");
    expect(waitedPhrase(5.4)).toBe("5 h");
    expect(waitedPhrase(72)).toBe("3 d");
  });
});

describe("readiness and the timeline", () => {
  it("turns reason codes into plain language", () => {
    expect(reasonText("gate_open")).toBe("Waiting for a person to decide");
    expect(reasonText("some_new_reason")).toBe("some new reason");
    expect(reasonText(null)).toBe("");
  });

  it("describes timeline events", () => {
    expect(eventText({ kind: "delegated", data: { delegation: "agent" } })).toBe(
      "Delegated to agents",
    );
    expect(eventText({ kind: "delegated", data: { delegation: null, taken_over: true } })).toBe(
      "A person took the task over",
    );
    expect(
      eventText({
        kind: "claimed",
        data: { role: "implementer", stage: "In Progress", attempt: 1, pulled: true },
      }),
    ).toBe("Claimed as implementer in In Progress (attempt 1) — pulled into the column");
    expect(
      eventText({ kind: "claim_ended", data: { outcome: "superseded", reason: "intake_off" } }),
    ).toBe("Claim ended: stopped (agent intake was switched off)");
    expect(eventText({ kind: "checks_evaluated", data: { target: "In Review", failures: [] } })).toBe(
      "Checks for In Review passed",
    );
    expect(
      eventText({ kind: "gate_decided", data: { decision: "approve", via: "pr_review" } }),
    ).toBe("Decided: Approve (via pr review)");
    expect(eventText({ kind: "something_new", data: {} })).toBe("something new");
  });
});

describe("refusalText", () => {
  it("pulls the message out of FastAPI error bodies", () => {
    expect(refusalText(new Error('{"detail":"Task not found"}'))).toBe("Task not found");
    expect(
      refusalText(new Error('{"detail":{"code":"not_an_approver","message":"You can\'t decide"}}')),
    ).toBe("You can't decide");
    expect(refusalText(new Error("Bad Gateway"))).toBe("Bad Gateway");
  });
});
