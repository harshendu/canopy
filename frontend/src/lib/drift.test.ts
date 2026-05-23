import { describe, expect, it } from "vitest";

import { driftKindLabel, RECONCILE_ACTIONS } from "./drift";

describe("driftKindLabel", () => {
  it("labels known kinds and falls back", () => {
    expect(driftKindLabel("unexpected_dependency")).toBe("Unexpected dependency");
    expect(driftKindLabel("implicit_decision")).toBe("Implicit decision (no ADR)");
    expect(driftKindLabel("mystery")).toBe("mystery");
  });
});

describe("RECONCILE_ACTIONS", () => {
  it("offers the three triage outcomes", () => {
    expect(RECONCILE_ACTIONS.map((a) => a.action)).toEqual([
      "accepted",
      "rejected",
      "false_positive",
    ]);
  });
});
