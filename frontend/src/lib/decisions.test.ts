import { describe, expect, it } from "vitest";

import type { DecisionQueueItem } from "../api/types";
import { groupQueue, legalNextStatuses } from "./decisions";

describe("legalNextStatuses", () => {
  it("includes the current status and its legal transitions", () => {
    expect(legalNextStatuses("proposed")).toEqual([
      "proposed",
      "under_discussion",
      "deferred",
      "accepted",
      "rejected",
    ]);
  });

  it("offers no forward move from a terminal status", () => {
    expect(legalNextStatuses("deprecated")).toEqual(["deprecated"]);
  });

  it("does not allow reopening an accepted decision as proposed", () => {
    expect(legalNextStatuses("accepted")).not.toContain("proposed");
  });
});

describe("groupQueue", () => {
  const item = (id: number, bucket: string): DecisionQueueItem => ({
    id,
    project_id: 1,
    number: id,
    title: `ADR ${id}`,
    status: "proposed",
    bucket,
    reason: "",
    overdue: false,
    decide_by: null,
    age_hours: 1,
  });

  it("groups by bucket in triage-priority order and drops empties", () => {
    const groups = groupQueue([
      item(1, "discussing"),
      item(2, "needs_triage"),
      item(3, "stuck"),
    ]);
    expect(groups.map((g) => g.meta.key)).toEqual(["needs_triage", "stuck", "discussing"]);
    expect(groups.every((g) => g.items.length === 1)).toBe(true);
  });
});
