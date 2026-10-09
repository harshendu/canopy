import { describe, expect, it } from "vitest";

import type { Initiative, InitiativeLead } from "../api/types";
import { groupByOwnership, leadTeamLabel, leadsFor } from "./initiativeAccess";

const init = (id: number): Initiative => ({
  id,
  key: `I${id}`,
  name: `Initiative ${id}`,
  outcome_statement: null,
  start_date: null,
  target_date: null,
  owner_engineer_id: null,
  archived: false,
  tags: [],
  health: null,
  status_note: null,
  status_updated_at: null,
});

const leads: InitiativeLead[] = [
  { initiative_id: 1, engineer_id: 10, engineer_name: "Priya", lead_role: "technical", user_id: 5 },
  { initiative_id: 1, engineer_id: 11, engineer_name: "Daniel", lead_role: "product", user_id: 6 },
  { initiative_id: 2, engineer_id: 12, engineer_name: "Nora", lead_role: "technical", user_id: 7 },
];

describe("groupByOwnership", () => {
  it("splits led from read-only initiatives, keeping order", () => {
    const g = groupByOwnership([init(1), init(2), init(3)], [2]);
    expect(g.led.map((i) => i.id)).toEqual([2]);
    expect(g.others.map((i) => i.id)).toEqual([1, 3]);
  });
  it("treats an unknown access map as nothing led", () => {
    const g = groupByOwnership([init(1)], undefined);
    expect(g.led).toEqual([]);
    expect(g.others).toHaveLength(1);
  });
});

describe("lead team labels", () => {
  it("filters seats per initiative and formats the team", () => {
    expect(leadTeamLabel(leadsFor(leads, 1))).toBe("Priya (Tech) · Daniel (Product)");
    expect(leadTeamLabel(leadsFor(leads, 3))).toBe("");
  });
});
