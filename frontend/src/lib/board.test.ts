import { describe, expect, it } from "vitest";

import type { BoardResponse, BoardViewer } from "../api/types";
import {
  NO_FILTER,
  NO_STATUS,
  applyOptimisticMove,
  boardOwners,
  boardPath,
  boardQueryKey,
  boardTags,
  canDrag,
  canMove,
  cardLabel,
  cellId,
  containerOf,
  expectedStatusOf,
  filterCards,
  foldedStatus,
  groupIntoSwimlanes,
  isFiltering,
  isOpenCard,
  laneCount,
  limitWip,
  matchesFilter,
  moveTargets,
  normalizeBoard,
  overLimit,
  parseCellId,
  placementAt,
  placementOf,
  sameOrder,
  toMoveRequest,
  trackerName,
  trackingFailure,
  viewerForRole,
  wipBeyondBoard,
  workflowPath,
  workflowQueryKey,
  wouldBlockOnWip,
  type Board,
  type Card,
  type Lane,
} from "./board";

function card(id: number, overrides: Partial<Card> = {}): Card {
  return {
    id,
    name: `Task ${id}`,
    status: "To Do",
    assignee_engineer_id: null,
    is_done: false,
    age_days: 2,
    aging: false,
    project_id: 1,
    key: `CHK-${id}`,
    status_category: "todo",
    status_owner: "canopy",
    movable: true,
    external_url: null,
    rank: id * 1024,
    parent_id: null,
    blocked: false,
    is_critical: false,
    deadline: null,
    tags: [],
    sprint_id: null,
    story_points: null,
    duration: null,
    ...overrides,
  };
}

function lane(status: string, category: Lane["category"], tasks: Card[], extra: Partial<Lane> = {}): Lane {
  const stamped = tasks.map((t) => ({ ...t, status, status_category: category }));
  const wip = stamped.filter(isOpenCard).length;
  return {
    status,
    is_done: category === "done",
    wip,
    tasks: stamped,
    category,
    position: 0,
    wip_limit: null,
    scope_wip: null,
    over_limit: false,
    in_workflow: true,
    ...extra,
  };
}

function board(lanes: Lane[], extra: Partial<Board> = {}): Board {
  return {
    project_id: 1,
    lanes: lanes.map((l, i) => ({ ...l, position: i })),
    cycle_time_p85_days: 5,
    aging_count: lanes.reduce((n, l) => n + l.tasks.filter((t) => t.aging).length, 0),
    mode: "native",
    wip_enforcement: "warn",
    viewer: PLANNER,
    team_id: null,
    sprint_id: null,
    delivery_method: "kanban",
    ...extra,
  };
}

const PLANNER: BoardViewer = { can_plan: true, engineer_id: 7, native_enabled: true };
const ENGINEER: BoardViewer = { can_plan: false, engineer_id: 7, native_enabled: true };

function sample(): Board {
  return board([
    lane("To Do", "todo", [card(1), card(2), card(3, { aging: true })]),
    lane("In Progress", "in_progress", [card(4), card(5)], { wip_limit: 2 }),
    lane("Done", "done", [card(6, { is_done: true })]),
  ]);
}

const ids = (l: Lane) => l.tasks.map((t) => t.id);

describe("normalizeBoard", () => {
  it("fills what a projection (the scenario board) leaves out with the server's defaults", () => {
    const raw: BoardResponse = {
      project_id: 9,
      cycle_time_p85_days: null,
      aging_count: 0,
      lanes: [
        {
          status: "Doing",
          is_done: false,
          wip: 3,
          tasks: [
            { id: 1, name: "a", status: "Doing", assignee_engineer_id: null, is_done: false, age_days: 1, aging: false },
          ],
        },
      ],
    };
    const b = normalizeBoard(raw);
    expect(b.mode).toBe("native");
    expect(b.wip_enforcement).toBe("warn");
    expect(b.viewer).toBeNull();
    expect(b).toMatchObject({ team_id: null, sprint_id: null, delivery_method: "kanban" });
    expect(b.lanes[0]).toMatchObject({ category: null, position: 0, wip_limit: null, over_limit: false, in_workflow: true });
    expect(b.lanes[0].tasks[0]).toMatchObject({
      project_id: 9,
      key: null,
      status_owner: "canopy",
      movable: true,
      tags: [],
      blocked: false,
      rank: 0,
      duration: null,
    });
  });

  it("keeps what the live board sends, and derives `movable` from the owner when absent", () => {
    const raw: BoardResponse = {
      project_id: 1,
      cycle_time_p85_days: 4,
      aging_count: 1,
      mode: "mirrored",
      wip_enforcement: "block",
      viewer: ENGINEER,
      lanes: [
        {
          status: "In Review",
          is_done: false,
          wip: 3,
          wip_limit: 2,
          category: "in_progress",
          in_workflow: false,
          tasks: [
            { id: 1, name: "a", status: "In Review", assignee_engineer_id: 7, is_done: false, age_days: 9, aging: true, status_owner: "jira", key: "SHOP-1", duration: 3 },
          ],
        },
      ],
    };
    const b = normalizeBoard(raw);
    expect(b.mode).toBe("mirrored");
    expect(b.viewer).toEqual(ENGINEER);
    expect(b.lanes[0]).toMatchObject({ over_limit: true, in_workflow: false, category: "in_progress" });
    expect(b.lanes[0].tasks[0]).toMatchObject({ movable: false, key: "SHOP-1", status_owner: "jira", duration: 3 });
  });
});

describe("canMove", () => {
  const mine = card(1, { assignee_engineer_id: 7 });
  const theirs = card(2, { assignee_engineer_id: 8 });
  const unassigned = card(3);
  const mirrored = card(4, { movable: false, status_owner: "jira", assignee_engineer_id: 7 });
  const move = { changesStatus: true };
  const reorder = { changesStatus: false };

  it("lets a planner move any canopy-owned card, and only reorder a mirrored one", () => {
    for (const c of [mine, theirs, unassigned]) {
      expect(canMove(c, PLANNER, move)).toBe(true);
      expect(canMove(c, PLANNER, reorder)).toBe(true);
    }
    expect(canMove(mirrored, PLANNER, move)).toBe(false);
    expect(canMove(mirrored, PLANNER, reorder)).toBe(true);
  });

  it("lets an engineer move their own cards and pull unassigned work into a column", () => {
    expect(canMove(mine, ENGINEER, move)).toBe(true);
    expect(canMove(mine, ENGINEER, reorder)).toBe(true);
    expect(canMove(theirs, ENGINEER, move)).toBe(false);
    expect(canMove(theirs, ENGINEER, reorder)).toBe(false);
    expect(canMove(unassigned, ENGINEER, move)).toBe(true);
    // Reordering someone else's backlog is planning, and would silently assign it to them.
    expect(canMove(unassigned, ENGINEER, reorder)).toBe(false);
    expect(canMove(mirrored, ENGINEER, reorder)).toBe(true);
    expect(canMove(mirrored, ENGINEER, move)).toBe(false);
  });

  it("refuses everyone while canopy-owned status is off, and a viewer with no engineer", () => {
    const off = { ...PLANNER, native_enabled: false };
    expect(canMove(mine, off, move)).toBe(false);
    expect(canMove(mine, off, reorder)).toBe(false);
    expect(canMove(mine, { can_plan: false, engineer_id: null, native_enabled: true }, move)).toBe(false);
    expect(canMove(mine, null, move)).toBe(false);
  });

  it("shows a drag handle when any move is open", () => {
    expect(canDrag(mirrored, PLANNER)).toBe(true);
    expect(canDrag(unassigned, ENGINEER)).toBe(true);
    expect(canDrag(theirs, ENGINEER)).toBe(false);
    expect(canDrag(mine, undefined)).toBe(false);
  });
});

describe("viewerForRole", () => {
  it("drops every move for a read-only viewer", () => {
    expect(viewerForRole(PLANNER, { planner: false, contributor: false })).toEqual({
      can_plan: false,
      engineer_id: null,
      native_enabled: true,
    });
  });

  it("keeps the engineer rules for a planner who may not plan this project", () => {
    const outsider = { ...ENGINEER };
    expect(viewerForRole(outsider, { planner: true, contributor: true })).toEqual(ENGINEER);
    expect(viewerForRole(PLANNER, { planner: true, contributor: true })).toEqual(PLANNER);
  });

  it("keeps an engineer's own path, and the server's view while the role is unknown", () => {
    expect(viewerForRole(ENGINEER, { planner: false, contributor: true })).toEqual(ENGINEER);
    expect(viewerForRole(ENGINEER, null)).toEqual(ENGINEER);
    expect(viewerForRole(null, null)).toBeNull();
  });
});

describe("applyOptimisticMove", () => {
  it("moves a card into another column after its new neighbour, stamping the column", () => {
    const before = sample();
    const after = applyOptimisticMove(before, { taskId: 3, to_status: "In Progress", after_task_id: 4 });
    expect(ids(after.lanes[0])).toEqual([1, 2]);
    expect(ids(after.lanes[1])).toEqual([4, 3, 5]);
    const moved = after.lanes[1].tasks[1];
    expect(moved).toMatchObject({
      status: "In Progress",
      status_category: "in_progress",
      is_done: false,
      age_days: 0,
      aging: false,
    });
    // WIP follows the cards; the limit of 2 is now exceeded.
    expect(after.lanes[0].wip).toBe(2);
    expect(after.lanes[1]).toMatchObject({ wip: 3, over_limit: true });
    expect(after.aging_count).toBe(before.aging_count - 1);
  });

  it("places by `before_task_id`, at the top, or at the bottom by default", () => {
    const b = sample();
    expect(ids(applyOptimisticMove(b, { taskId: 1, to_status: "In Progress", before_task_id: 5 }).lanes[1])).toEqual([4, 1, 5]);
    expect(ids(applyOptimisticMove(b, { taskId: 1, to_status: "In Progress", position: "top" }).lanes[1])).toEqual([1, 4, 5]);
    expect(ids(applyOptimisticMove(b, { taskId: 1, to_status: "In Progress" }).lanes[1])).toEqual([4, 5, 1]);
  });

  it("reorders within a column when no status is named", () => {
    const b = sample();
    expect(ids(applyOptimisticMove(b, { taskId: 1, after_task_id: 3 }).lanes[0])).toEqual([2, 3, 1]);
    expect(ids(applyOptimisticMove(b, { taskId: 3, before_task_id: 1 }).lanes[0])).toEqual([3, 1, 2]);
    expect(ids(applyOptimisticMove(b, { taskId: 2, position: "top" }).lanes[0])).toEqual([2, 1, 3]);
  });

  it("closes work moved into done: it leaves WIP and counts as done", () => {
    const after = applyOptimisticMove(sample(), { taskId: 4, to_status: "done" });
    expect(after.lanes[2].tasks.at(-1)).toMatchObject({ id: 4, status: "Done", is_done: true });
    expect(after.lanes[1].wip).toBe(1);
    expect(after.lanes[2].wip).toBe(0);
  });

  it("assigns pulled work to the engineer who pulled it, never reassigning owned work", () => {
    const b = board([lane("To Do", "todo", [card(1), card(2, { assignee_engineer_id: 3 })]), lane("Doing", "in_progress", [])]);
    const pulled = applyOptimisticMove(b, { taskId: 1, to_status: "Doing", assignTo: 7 });
    expect(pulled.lanes[1].tasks[0].assignee_engineer_id).toBe(7);
    const owned = applyOptimisticMove(b, { taskId: 2, to_status: "Doing", assignTo: 7 });
    expect(owned.lanes[1].tasks[0].assignee_engineer_id).toBe(3);
  });

  it("leaves the board alone for an unknown card or column, or its own column without neighbours", () => {
    const b = sample();
    expect(applyOptimisticMove(b, { taskId: 99, to_status: "Done" })).toBe(b);
    expect(applyOptimisticMove(b, { taskId: 1, to_status: "Nowhere" })).toBe(b);
    expect(applyOptimisticMove(b, { taskId: 1, to_status: "To Do" })).toBe(b);
  });

  it("keeps a column's scope-wide WIP in step with what moved on this board", () => {
    const b = board([
      lane("To Do", "todo", [card(1), card(2)], { scope_wip: 6 }),
      lane("In Progress", "in_progress", [card(3)], { wip_limit: 3, scope_wip: 3 }),
    ]);
    const after = applyOptimisticMove(b, { taskId: 1, to_status: "In Progress" });
    expect(after.lanes[0]).toMatchObject({ wip: 1, scope_wip: 5 });
    // Judged across the scope: 4 open against a limit of 3, though this board shows two.
    expect(after.lanes[1]).toMatchObject({ wip: 2, scope_wip: 4, over_limit: true });
  });

  it("does not mutate the board it was given", () => {
    const b = sample();
    const snapshot = JSON.stringify(b);
    applyOptimisticMove(b, { taskId: 3, to_status: "Done", position: "top" });
    expect(JSON.stringify(b)).toBe(snapshot);
  });
});

describe("placementAt / placementOf", () => {
  it("names the visible neighbours around a drop", () => {
    expect(placementAt([10, 11, 12], 0)).toEqual({ before_task_id: 10 });
    expect(placementAt([10, 11, 12], 2)).toEqual({ after_task_id: 11, before_task_id: 12 });
    expect(placementAt([10, 11, 12], 3)).toEqual({ after_task_id: 12 });
  });

  it("takes an empty column at its end, and clamps an out-of-range index", () => {
    expect(placementAt([], 0)).toEqual({ position: "bottom" });
    expect(placementAt([10], 9)).toEqual({ after_task_id: 10 });
    expect(placementAt([10], -3)).toEqual({ before_task_id: 10 });
  });

  it("reads the neighbours of a card from the order a drop left", () => {
    expect(placementOf([10, 5, 11], 5)).toEqual({ after_task_id: 10, before_task_id: 11 });
    expect(placementOf([5, 10], 5)).toEqual({ before_task_id: 10 });
    expect(placementOf([5], 5)).toEqual({ position: "bottom" });
    expect(placementOf([10, 11], 5)).toEqual({ after_task_id: 11 });
  });
});

describe("filters", () => {
  const lanes = [
    lane("To Do", "todo", [
      card(1, { assignee_engineer_id: 7, tags: ["api"] }),
      card(2, { blocked: true }),
      card(3, { aging: true, tags: ["api", "web"] }),
    ]),
  ];

  it("matches owner, tag, blocked and aging", () => {
    const pick = (f: Partial<typeof NO_FILTER>) => ids(filterCards(lanes, { ...NO_FILTER, ...f })[0]);
    expect(pick({})).toEqual([1, 2, 3]);
    expect(pick({ owner: 7 })).toEqual([1]);
    expect(pick({ owner: "none" })).toEqual([2, 3]);
    expect(pick({ tag: "api" })).toEqual([1, 3]);
    expect(pick({ blocked: true })).toEqual([2]);
    expect(pick({ aging: true, tag: "web" })).toEqual([3]);
    expect(matchesFilter(lanes[0].tasks[0], { ...NO_FILTER, owner: 8 })).toBe(false);
  });

  it("keeps the column's real WIP while narrowing what shows", () => {
    expect(filterCards(lanes, { ...NO_FILTER, owner: 7 })[0].wip).toBe(3);
    expect(isFiltering(NO_FILTER)).toBe(false);
    expect(isFiltering({ ...NO_FILTER, blocked: true })).toBe(true);
  });

  it("lists the tags and owners present", () => {
    expect(boardTags(lanes)).toEqual(["api", "web"]);
    expect(boardOwners(lanes)).toEqual([7]);
  });

  it("narrows a team board to a project, or to a pod through each card's project", () => {
    const team = [
      lane("To Do", "todo", [card(1, { project_id: 5 }), card(2, { project_id: 6 }), card(3, { project_id: 7 })]),
    ];
    const podOf = new Map<number, number | null>([[5, 50], [6, 50], [7, null]]);
    expect(ids(filterCards(team, { ...NO_FILTER, project: 6 }, podOf)[0])).toEqual([2]);
    expect(ids(filterCards(team, { ...NO_FILTER, pod: 50 }, podOf)[0])).toEqual([1, 2]);
    expect(ids(filterCards(team, { ...NO_FILTER, pod: 50 })[0])).toEqual([]);
    expect(isFiltering({ ...NO_FILTER, pod: 50 })).toBe(true);
  });
});

describe("groupIntoSwimlanes", () => {
  const lanes = [
    lane("To Do", "todo", [
      card(1, { assignee_engineer_id: 2, parent_id: 50 }),
      card(2, { parent_id: 40 }),
      card(3, { assignee_engineer_id: 1, parent_id: 99 }),
    ]),
    lane("Done", "done", [card(4, { assignee_engineer_id: 2, parent_id: 40 })]),
  ];

  it("is one row when ungrouped or empty", () => {
    expect(groupIntoSwimlanes(lanes, "none")).toHaveLength(1);
    const empty = groupIntoSwimlanes([lane("To Do", "todo", [])], "owner");
    expect(empty).toHaveLength(1);
    expect(empty[0].lanes).toHaveLength(1);
  });

  it("groups by owner alphabetically, Unassigned last, every row keeping every column", () => {
    const rows = groupIntoSwimlanes(lanes, "owner", new Map([[1, "Zoe"], [2, "Ann"]]));
    expect(rows.map((r) => r.label)).toEqual(["Ann", "Zoe", "Unassigned"]);
    expect(rows[0].lanes.map(ids)).toEqual([[1], [4]]);
    expect(rows[2]).toMatchObject({ key: "owner:none", groupId: null, count: 1 });
    expect(rows.every((r) => r.lanes.length === 2)).toBe(true);
  });

  it("groups by phase in WBS order, unknown phases after known ones, No phase last", () => {
    const withLoose = [...lanes, lane("Doing", "in_progress", [card(5)])];
    const rows = groupIntoSwimlanes(withLoose, "parent", new Map([[50, "Build"], [40, "Design"]]));
    expect(rows.map((r) => r.label)).toEqual(["Build", "Design", "#99", "No phase"]);
    expect(rows[1].count).toBe(2);
  });

  it("groups a team board by project, alphabetically", () => {
    const team = [lane("To Do", "todo", [card(1, { project_id: 2 }), card(2, { project_id: 1 })])];
    const rows = groupIntoSwimlanes(team, "project", new Map([[1, "Search"], [2, "Payments"]]));
    expect(rows.map((r) => [r.key, r.label])).toEqual([
      ["project:2", "Payments"],
      ["project:1", "Search"],
    ]);
  });
});

describe("WIP and labels", () => {
  it("flags a column over its limit", () => {
    expect(overLimit({ wip: 3, wip_limit: 2 })).toBe(true);
    expect(overLimit({ wip: 2, wip_limit: 2 })).toBe(false);
    expect(overLimit({ wip: 9, wip_limit: null })).toBe(false);
  });

  it("counts cards in closed columns and WIP against the limit elsewhere", () => {
    const b = sample();
    expect(laneCount(b.lanes[0])).toBe("3");
    expect(laneCount(b.lanes[1])).toBe("2/2");
    expect(laneCount(b.lanes[2])).toBe("1");
  });

  it("judges the limit on the scope-wide WIP when the server sends it", () => {
    const shared = { wip: 2, scope_wip: 5, wip_limit: 4 };
    expect(overLimit(shared)).toBe(true);
    expect(overLimit({ ...shared, scope_wip: null })).toBe(false);
    expect(limitWip(shared)).toBe(5);
    expect(wipBeyondBoard(shared)).toBe(true);
    expect(wipBeyondBoard({ wip: 2, scope_wip: 2 })).toBe(false);
    const column = lane("Doing", "in_progress", [card(1)], { wip_limit: 4, scope_wip: 5 });
    expect(laneCount(column)).toBe("5/4");
    expect(laneCount({ ...column, wip_limit: null })).toBe("1");
  });

  it("predicts a refusal for a full column only under block enforcement", () => {
    const full = board(
      [
        lane("To Do", "todo", [card(1)]),
        lane("Doing", "in_progress", [card(2)], { wip_limit: 2, scope_wip: 2 }),
        lane("Done", "done", [], { wip_limit: 1 }),
      ],
      { wip_enforcement: "block" },
    );
    expect(wouldBlockOnWip(full, { taskId: 1, to_status: "doing" })).toBe(true);
    expect(wouldBlockOnWip({ ...full, wip_enforcement: "warn" }, { taskId: 1, to_status: "Doing" })).toBe(false);
    // Reordering inside the column, closed columns and room to spare never block.
    expect(wouldBlockOnWip(full, { taskId: 2, to_status: "Doing", before_task_id: 2 })).toBe(false);
    expect(wouldBlockOnWip(full, { taskId: 1, to_status: "Done" })).toBe(false);
    const roomy = { ...full, lanes: full.lanes.map((l) => ({ ...l, scope_wip: l.scope_wip && 1 })) };
    expect(wouldBlockOnWip(roomy, { taskId: 1, to_status: "Doing" })).toBe(false);
    expect(wouldBlockOnWip(full, { taskId: 1, after_task_id: 1 })).toBe(false);
  });

  it("names trackers and cards", () => {
    expect(trackerName("jira")).toBe("Jira");
    expect(trackerName("linear")).toBe("Linear");
    expect(cardLabel({ key: "CHK-1", name: "Retry" })).toBe("CHK-1 Retry");
    expect(cardLabel({ key: null, name: "Retry" })).toBe("Retry");
  });

  it("offers only the other workflow columns as move targets", () => {
    const b = board([
      lane(NO_STATUS, null, [card(1)], { in_workflow: false }),
      lane("To Do", "todo", [card(2)]),
      lane("Blocked upstream", "in_progress", [], { in_workflow: false }),
      lane("Done", "done", []),
    ]);
    expect(moveTargets(b.lanes, { status: "to do" })).toEqual(["Done"]);
    expect(moveTargets(b.lanes, { status: NO_STATUS })).toEqual(["To Do", "Done"]);
  });

  it("expects an empty status for a card shown without one", () => {
    expect(expectedStatusOf({ status: NO_STATUS })).toBe("");
    expect(expectedStatusOf({ status: "To Do" })).toBe("To Do");
  });

  it("names a card's own status when the team board shows it in another column", () => {
    expect(foldedStatus({ status: "Code Review" }, { status: "In Progress" })).toBe("Code Review");
    expect(foldedStatus({ status: "in progress" }, { status: "In Progress" })).toBeNull();
    expect(foldedStatus({ status: NO_STATUS }, { status: NO_STATUS })).toBeNull();
  });
});

describe("source, cells and requests", () => {
  it("keys a project board where the task drawer invalidates it", () => {
    expect(boardQueryKey({ kind: "project", id: 4 })).toEqual(["board", 4]);
    expect(boardPath({ kind: "project", id: 4 })).toBe("/projects/4/board");
  });

  it("extends the key and path with a sprint filter, and serves team boards", () => {
    expect(boardQueryKey({ kind: "project", id: 4 }, "active")).toEqual(["board", 4, "active"]);
    expect(boardQueryKey({ kind: "team", id: 2 })).toEqual(["team-board", 2]);
    expect(boardPath({ kind: "team", id: 2 }, "12")).toBe("/teams/2/board?sprint=12");
    expect(workflowPath({ kind: "team", id: 2 })).toBe("/teams/2/workflow");
    expect(workflowQueryKey({ kind: "team", id: 2 })).toEqual(["workflow", "team", 2]);
  });

  it("round-trips any status name through a cell id", () => {
    for (const status of ["To Do", "a:b", "50% done", "Ünïcode / ✓", NO_STATUS]) {
      expect(parseCellId(cellId("owner:7", status))).toEqual({ swimlane: "owner:7", status });
    }
    expect(parseCellId(12)).toBeNull();
    expect(parseCellId("lane:x")).toBeNull();
    expect(parseCellId("cell:%E0%A4%A:x")).toBeNull();
  });

  it("finds the cell holding a card, and a cell by its own id", () => {
    const layout = { [cellId("all", "To Do")]: [1, 2], [cellId("all", "Done")]: [] };
    expect(containerOf(2, layout)).toBe(cellId("all", "To Do"));
    expect(containerOf(cellId("all", "Done"), layout)).toBe(cellId("all", "Done"));
    expect(containerOf(9, layout)).toBeNull();
    expect(containerOf(cellId("all", "Gone"), layout)).toBeNull();
    expect(sameOrder([1, 2], [1, 2])).toBe(true);
    expect(sameOrder([2, 1], [1, 2])).toBe(false);
    expect(sameOrder([1], undefined)).toBe(false);
  });

  it("sends only the request fields", () => {
    expect(
      JSON.parse(JSON.stringify(toMoveRequest({ taskId: 1, projectId: 2, assignTo: 3, to_status: "Done", after_task_id: 4 }))),
    ).toEqual({ to_status: "Done", after_task_id: 4 });
  });
});

describe("trackingFailure", () => {
  const apiError = (body: unknown) => new Error(typeof body === "string" ? body : JSON.stringify(body));

  it("reads a structured refusal", () => {
    const f = trackingFailure(
      apiError({
        detail: {
          code: "status_externally_owned",
          message: "This task's status is owned by jira; change it there",
          provider: "jira",
          url: "https://jira.example.com/browse/SHOP-1",
        },
      }),
    );
    expect(f).toMatchObject({ code: "status_externally_owned", provider: "jira", url: "https://jira.example.com/browse/SHOP-1" });
    expect(f.message).toContain("owned by jira");
  });

  it("reads the removed columns of a column_in_use refusal", () => {
    const f = trackingFailure(apiError({ detail: { code: "column_in_use", message: "m", columns: ["QA", 3] } }));
    expect(f.columns).toEqual(["QA"]);
    expect(f.projectIds).toEqual([]);
  });

  it("reads the projects a connection still feeds", () => {
    const f = trackingFailure(
      apiError({ detail: { code: "connection_in_use", message: "Projects are still mirrored", project_ids: [4, "x", 9] } }),
    );
    expect(f).toMatchObject({ code: "connection_in_use", message: "Projects are still mirrored", projectIds: [4, 9] });
  });

  it("reads plain, validation and non-JSON bodies", () => {
    expect(trackingFailure(apiError({ detail: "Task not found" })).message).toBe("Task not found");
    expect(trackingFailure(apiError({ detail: [{ msg: "field required" }, { msg: "bad" }] })).message).toBe("field required; bad");
    expect(trackingFailure(apiError("Bad Gateway"))).toMatchObject({ code: null, message: "Bad Gateway" });
    expect(trackingFailure(apiError({ detail: { code: "stale" } })).message).toBe("stale");
  });
});
