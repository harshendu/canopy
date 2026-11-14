import { describe, expect, it } from "vitest";

import type { Project, Sprint, SprintCapacity, SprintReport, Velocity } from "../api/types";
import {
  burndownSeries,
  capacityView,
  carryOverTargets,
  daysBetween,
  defaultPlanningSprint,
  defaultReportSprint,
  defaultSprintSelection,
  formatDay,
  formatEstimate,
  formatSprintDates,
  liveSprints,
  parseSprintSelection,
  percent,
  planLists,
  projectTeamId,
  shownSprint,
  sprintParam,
  teamProjects,
  timeLeftLabel,
  usesSprints,
  velocitySeries,
} from "./sprints";

function sprint(id: number, overrides: Partial<Sprint> = {}): Sprint {
  return {
    id,
    team_id: 1,
    pod_id: null,
    name: `Sprint ${id}`,
    goal: null,
    start_date: null,
    end_date: null,
    state: "planned",
    owner: "canopy",
    estimate_unit: null,
    committed: null,
    completed: null,
    started_at: null,
    completed_at: null,
    task_count: 0,
    done_count: 0,
    scope: 0,
    done: 0,
    unit: "points",
    ...overrides,
  };
}

const SPRINTS: Sprint[] = [
  sprint(1, { state: "completed", start_date: "2026-10-01", end_date: "2026-10-14" }),
  sprint(2, { state: "completed", start_date: "2026-10-15", end_date: "2026-10-28" }),
  sprint(3, { state: "active", start_date: "2026-10-29", end_date: "2026-11-11" }),
  sprint(5, { state: "planned", start_date: "2026-11-26", end_date: "2026-12-09" }),
  sprint(4, { state: "planned", start_date: "2026-11-12", end_date: "2026-11-25" }),
];

describe("delivery method + formatting", () => {
  it("turns sprint surfaces on for sprint and both only", () => {
    expect(usesSprints("sprint")).toBe(true);
    expect(usesSprints("both")).toBe(true);
    expect(usesSprints("kanban")).toBe(false);
    expect(usesSprints(undefined)).toBe(false);
  });

  it("formats estimates, ratios and dates", () => {
    expect(formatEstimate(13, "points")).toBe("13 pts");
    expect(formatEstimate(1, "points")).toBe("1 pt");
    expect(formatEstimate(4.25, "days")).toBe("4.3 d");
    expect(formatEstimate(1, "count")).toBe("1 task");
    expect(percent(0.856)).toBe("86%");
    expect(percent(null)).toBe("—");
    expect(formatDay("2026-11-03")).toBe("Nov 3");
    expect(formatSprintDates(SPRINTS[2])).toBe("Oct 29 – Nov 11");
    expect(formatSprintDates(sprint(9))).toBe("No dates yet");
    expect(daysBetween("2026-10-30", "2026-11-02")).toBe(3);
  });

  it("says how long an active sprint has left", () => {
    const active = SPRINTS[2];
    expect(timeLeftLabel(active, "2026-11-08")).toBe("3 days left");
    expect(timeLeftLabel(active, "2026-11-10")).toBe("1 day left");
    expect(timeLeftLabel(active, "2026-11-11")).toBe("ends today");
    expect(timeLeftLabel(active, "2026-11-13")).toBe("ended 2 days ago");
    expect(timeLeftLabel(SPRINTS[3], "2026-11-08")).toBeNull();
  });
});

describe("sprint lists", () => {
  it("lists live sprints active first, then planned by start", () => {
    expect(liveSprints(SPRINTS).map((s) => s.id)).toEqual([3, 4, 5]);
  });

  it("offers other open canopy sprints of the team as carry-over targets", () => {
    const mirrored = sprint(6, { owner: "jira", state: "planned", start_date: "2026-11-12" });
    const otherTeam = sprint(7, { team_id: 2, state: "planned" });
    const targets = carryOverTargets([...SPRINTS, mirrored, otherTeam], SPRINTS[2]);
    expect(targets.map((s) => s.id)).toEqual([4, 5]);
  });

  it("opens planning on the active sprint, and reports on the active or latest completed", () => {
    expect(defaultPlanningSprint(SPRINTS)?.id).toBe(3);
    expect(defaultPlanningSprint(SPRINTS.filter((s) => s.state !== "active"))?.id).toBe(4);
    expect(defaultPlanningSprint(SPRINTS.filter((s) => s.state === "completed"))?.id).toBe(2);
    expect(defaultPlanningSprint([])).toBeNull();
    expect(defaultReportSprint(SPRINTS)?.id).toBe(3);
    expect(defaultReportSprint(SPRINTS.filter((s) => s.state !== "active"))?.id).toBe(2);
  });
});

describe("the board's sprint selector", () => {
  it("defaults to the active sprint when there is one, else all work", () => {
    expect(defaultSprintSelection(3)).toBe("active");
    expect(defaultSprintSelection(null)).toBe("all");
  });

  it("round-trips selections through the query value", () => {
    for (const s of ["active", "backlog", "all", 42] as const) {
      expect(parseSprintSelection(sprintParam(s))).toBe(s);
    }
    expect(parseSprintSelection("nonsense")).toBe("all");
    expect(parseSprintSelection("-3")).toBe("all");
  });

  it("names the one sprint a selection shows", () => {
    expect(shownSprint(4, SPRINTS, null)?.id).toBe(4);
    expect(shownSprint("active", SPRINTS, 3)?.id).toBe(3);
    expect(shownSprint("active", SPRINTS, null)?.id).toBe(3);
    expect(shownSprint("backlog", SPRINTS, null)).toBeNull();
    expect(shownSprint("all", SPRINTS, 3)).toBeNull();
  });
});

describe("capacityView", () => {
  const base: SprintCapacity = {
    person_days: 40,
    engineers: [],
    velocity_mean: 24,
    committed: 30,
    unit: "points",
    over_capacity: true,
  };

  it("compares points against mean velocity and carries the server's verdict", () => {
    const v = capacityView(base);
    expect(v).toMatchObject({ limit: 24, basis: "velocity", fillPct: 100, over: true });
    expect(v.summary).toBe("30 pts planned against a mean velocity of 24 pts");
  });

  it("compares days against person-days", () => {
    const v = capacityView({ ...base, unit: "days", committed: 20, over_capacity: false });
    expect(v).toMatchObject({ limit: 40, basis: "person-days", fillPct: 50, over: false });
    expect(v.summary).toBe("20 d planned of 40 person-days");
  });

  it("says so when there is nothing to compare with", () => {
    const v = capacityView({ ...base, velocity_mean: null, over_capacity: null });
    expect(v).toMatchObject({ limit: null, basis: null, fillPct: 0, over: false });
    expect(v.summary).toMatch(/no velocity history/);
    expect(capacityView({ ...base, unit: "days", person_days: 0 }).summary).toMatch(/person-days/);
  });
});

describe("planLists", () => {
  const backlog = [{ id: 1 }, { id: 2 }, { id: 3 }];
  const inSprint = [{ id: 10 }, { id: 11 }];

  it("shows the server's lists when nothing is moving", () => {
    expect(planLists(backlog, inSprint, {})).toEqual({ backlog, sprint: inSprint });
  });

  it("moves pending cards to their new side at once", () => {
    const { backlog: b, sprint: s } = planLists(backlog, inSprint, { 2: "sprint", 11: "backlog" });
    expect(b.map((t) => t.id)).toEqual([1, 3, 11]);
    expect(s.map((t) => t.id)).toEqual([10, 2]);
  });

  it("counts a card listed on both sides as in the sprint", () => {
    const { backlog: b, sprint: s } = planLists([{ id: 1 }, { id: 10 }], inSprint, {});
    expect(b.map((t) => t.id)).toEqual([1]);
    expect(s.map((t) => t.id)).toEqual([10, 11]);
  });
});

describe("chart series", () => {
  const report: SprintReport = {
    sprint: sprint(3, { state: "active", start_date: "2026-11-01", end_date: "2026-11-05" }),
    unit: "points",
    burndown: [
      { day: "2026-11-01", remaining: 20, ideal: 20, scope_added: 0 },
      { day: "2026-11-02", remaining: 18, ideal: 15, scope_added: 3 },
    ],
    committed: 20,
    completed: 5,
    scope_added: 3,
    scope_removed: 0,
    carried_over: 0,
    reliability: 0.25,
  };

  it("runs the burndown to the sprint end, the ideal line continuing past today", () => {
    const rows = burndownSeries(report);
    expect(rows.map((r) => r.day)).toEqual([
      "2026-11-01",
      "2026-11-02",
      "2026-11-03",
      "2026-11-04",
      "2026-11-05",
    ]);
    expect(rows[1]).toMatchObject({ remaining: 18, ideal: 15, scopeAdded: 3, label: "Nov 2" });
    expect(rows[2]).toMatchObject({ remaining: null, ideal: 10, scopeAdded: null });
    expect(rows[4]).toMatchObject({ remaining: null, ideal: 0 });
  });

  it("keeps the server's rows when the sprint has no dates", () => {
    const undated = { ...report, sprint: sprint(3) };
    expect(burndownSeries(undated)).toHaveLength(2);
  });

  it("shapes velocity oldest first", () => {
    const velocity: Velocity = {
      team_id: 1,
      unit: "points",
      points: [
        { sprint_id: 1, name: "S1", end_date: "2026-10-14", committed: 20, completed: 18, reliability: 0.9 },
        { sprint_id: 2, name: "S2", end_date: "2026-10-28", committed: 22, completed: 22, reliability: 1 },
      ],
      mean: 20,
      low: 18,
      high: 22,
      mean_reliability: 0.95,
      sufficient: false,
      reason: "needs 3",
      forecast: {
        sufficient: false,
        remaining: 40,
        history_sprints: 2,
        p50_sprints: null,
        p85_sprints: null,
        p50_date: null,
        p85_date: null,
        reason: "needs 3",
      },
    };
    expect(velocitySeries(velocity)).toEqual([
      { name: "S1", committed: 20, completed: 18, reliability: 0.9 },
      { name: "S2", committed: 22, completed: 22, reliability: 1 },
    ]);
  });
});

describe("teams", () => {
  const teams = [
    { id: 1, pods: [{ id: 10, team_id: 1, name: "A" }] },
    { id: 2, pods: [{ id: 20, team_id: 2, name: "B" }] },
  ];
  const initiatives = [
    { id: 100, team_id: 2 },
    { id: 101, team_id: null },
  ];
  const project = (id: number, pod_id: number | null, initiative_id: number | null, archived = false) =>
    ({ id, pod_id, initiative_id, archived }) as Pick<Project, "id" | "pod_id" | "initiative_id" | "archived">;

  it("resolves a project's team from its pod, else its initiative", () => {
    expect(projectTeamId(project(1, 10, 100), teams, initiatives)).toBe(1);
    expect(projectTeamId(project(2, null, 100), teams, initiatives)).toBe(2);
    expect(projectTeamId(project(3, null, 101), teams, initiatives)).toBeNull();
    expect(projectTeamId(project(4, null, null), teams, initiatives)).toBeNull();
  });

  it("lists a team's live projects the way the server does", () => {
    const projects = [
      project(1, 10, null),
      project(2, null, 100),
      project(3, 20, 100), // another team's pod wins over the initiative
      project(4, 10, null, true),
    ];
    expect(teamProjects(1, projects, teams, initiatives).map((p) => p.id)).toEqual([1]);
    expect(teamProjects(2, projects, teams, initiatives).map((p) => p.id)).toEqual([2, 3]);
  });
});
