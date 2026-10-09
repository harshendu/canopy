import { describe, expect, it } from "vitest";

import type { Initiative, InitiativeLead, Project, Team } from "../api/types";
import {
  groupByOwnership,
  groupByTeam,
  leadTeamLabel,
  leadsFor,
  podsForInitiative,
  teamSeatsLabel,
} from "./initiativeAccess";

const init = (id: number, team_id: number | null = null): Initiative => ({
  id,
  key: `I${id}`,
  name: `Initiative ${id}`,
  outcome_statement: null,
  start_date: null,
  target_date: null,
  owner_engineer_id: null,
  team_id,
  archived: false,
  tags: [],
  health: null,
  status_note: null,
  status_updated_at: null,
});

const project = (id: number, initiative_id: number, pod_id: number | null): Project =>
  ({ id, key: `P${id}`, name: `P${id}`, initiative_id, pod_id }) as Project;

const teams: Team[] = [
  {
    id: 1,
    key: "TA",
    name: "Talent Acquisition",
    description: null,
    pods: [
      { id: 10, team_id: 1, name: "Interviewer" },
      { id: 11, team_id: 1, name: "Recruiter Experience" },
    ],
    members: [
      { team_id: 1, engineer_id: 1, engineer_name: "Samir", role: "director", user_id: 1 },
      { team_id: 1, engineer_id: 2, engineer_name: "Jonah", role: "manager", user_id: 2 },
    ],
  },
];

const leads: InitiativeLead[] = [
  { initiative_id: 1, engineer_id: 10, engineer_name: "Priya", lead_role: "technical", user_id: 5 },
  { initiative_id: 1, engineer_id: 11, engineer_name: "Jonah", lead_role: "manager", user_id: 6 },
  { initiative_id: 2, engineer_id: 12, engineer_name: "Nora", lead_role: "technical", user_id: 7 },
];

describe("groupByOwnership", () => {
  it("splits owned from read-only initiatives, keeping order", () => {
    const g = groupByOwnership([init(1), init(2), init(3)], [2]);
    expect(g.led.map((i) => i.id)).toEqual([2]);
    expect(g.others.map((i) => i.id)).toEqual([1, 3]);
  });
  it("treats an unknown access map as nothing owned", () => {
    const g = groupByOwnership([init(1)], undefined);
    expect(g.led).toEqual([]);
    expect(g.others).toHaveLength(1);
  });
});

describe("groupByTeam", () => {
  it("groups under teams and puts teamless initiatives last", () => {
    const g = groupByTeam([init(1, 1), init(2), init(3, 1)], teams);
    expect(g.map((x) => x.team?.name ?? null)).toEqual(["Talent Acquisition", null]);
    expect(g[0].initiatives.map((i) => i.id)).toEqual([1, 3]);
  });
});

describe("pods and labels", () => {
  it("derives the pods an initiative spans from its projects", () => {
    const projects = [project(1, 1, 10), project(2, 1, 11), project(3, 2, 10), project(4, 1, null)];
    expect(podsForInitiative(1, projects, teams)).toEqual(["Interviewer", "Recruiter Experience"]);
  });
  it("formats owners and team seats", () => {
    expect(leadTeamLabel(leadsFor(leads, 1))).toBe("Priya (Tech) · Jonah (Manager)");
    expect(leadTeamLabel(leadsFor(leads, 3))).toBe("");
    expect(teamSeatsLabel(teams[0].members)).toBe("Director: Samir · Manager: Jonah");
  });
});
