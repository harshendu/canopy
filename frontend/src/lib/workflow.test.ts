import { describe, expect, it } from "vitest";

import type { WorkflowColumn, WorkflowRead } from "../api/types";
import {
  buildWorkflowUpdate,
  draftFromWorkflow,
  moveColumn,
  newColumnDraft,
  occupiedColumns,
  removedColumns,
  validateDraft,
  workflowEditable,
  workflowSourceLabel,
  type WorkflowDraft,
} from "./workflow";

const COLUMNS: WorkflowColumn[] = [
  { name: "In Progress", category: "in_progress", position: 2, wip_limit: 3 },
  { name: "Backlog", category: "todo", position: 0, wip_limit: null },
  { name: "To Do", category: "todo", position: 1, wip_limit: null },
  { name: "Done", category: "done", position: 3, wip_limit: null },
];

const WORKFLOW: WorkflowRead = {
  id: null,
  scope: "team",
  team_id: 2,
  project_id: null,
  name: "Default",
  wip_enforcement: "warn",
  inherited: true,
  columns: COLUMNS,
};

function edit(draft: WorkflowDraft, name: string, patch: Partial<WorkflowDraft["columns"][number]>): WorkflowDraft {
  return {
    ...draft,
    columns: draft.columns.map((c) => (c.originalName === name ? { ...c, ...patch } : c)),
  };
}

function drop(draft: WorkflowDraft, name: string): WorkflowDraft {
  return { ...draft, columns: draft.columns.filter((c) => c.originalName !== name) };
}

describe("draftFromWorkflow / moveColumn", () => {
  it("orders the columns by position and keeps where each came from", () => {
    const draft = draftFromWorkflow(WORKFLOW);
    expect(draft.columns.map((c) => c.name)).toEqual(["Backlog", "To Do", "In Progress", "Done"]);
    expect(draft.columns[2]).toMatchObject({ wipLimit: "3", originalName: "In Progress" });
    expect(draft.columns[0].wipLimit).toBe("");
    expect(new Set(draft.columns.map((c) => c.uid)).size).toBe(4);
  });

  it("swaps a column with its neighbour and ignores moves off either end", () => {
    const cols = draftFromWorkflow(WORKFLOW).columns;
    expect(moveColumn(cols, 1, 1).map((c) => c.name)).toEqual(["Backlog", "In Progress", "To Do", "Done"]);
    expect(moveColumn(cols, 0, -1).map((c) => c.name)).toEqual(cols.map((c) => c.name));
    expect(moveColumn(cols, 3, 1)).not.toBe(cols);
  });
});

describe("removedColumns", () => {
  const draft = draftFromWorkflow(WORKFLOW);

  it("lists a dropped column, but not a renamed one (its cards follow)", () => {
    expect(removedColumns(COLUMNS, drop(draft, "Backlog"))).toEqual(["Backlog"]);
    expect(removedColumns(COLUMNS, edit(draft, "To Do", { name: "Ready" }))).toEqual([]);
  });

  it("follows the server: a column whose name a draft column takes over is kept", () => {
    // Drop "To Do" and rename "Backlog" to "To Do": both sets of cards end up in "To Do".
    const merged = edit(drop(draft, "To Do"), "Backlog", { name: "to do" });
    expect(removedColumns(COLUMNS, merged)).toEqual([]);
    // Re-adding a dropped column by name keeps it, too.
    const readded = { ...drop(draft, "Done"), columns: [...drop(draft, "Done").columns, { ...newColumnDraft("n1"), name: "Done", category: "done" as const }] };
    expect(removedColumns(COLUMNS, readded)).toEqual([]);
  });
});

describe("occupiedColumns", () => {
  it("counts canopy-owned cards only — mirrored cards keep their tracker's status", () => {
    expect(
      occupiedColumns([
        {
          status: "To Do",
          tasks: [
            { status: "To Do", status_owner: "canopy" },
            { status: "To Do", status_owner: "jira" },
          ],
        },
        { status: "Done", tasks: [{ status: "Done", status_owner: "jira" }] },
      ]),
    ).toEqual({ "to do": 1 });
  });

  it("skips a card the team board only shows in a column (its status has another name)", () => {
    expect(
      occupiedColumns([
        {
          status: "In Progress",
          tasks: [
            { status: "Code Review", status_owner: "canopy" },
            { status: "in progress", status_owner: "canopy" },
          ],
        },
      ]),
    ).toEqual({ "in progress": 1 });
  });
});

describe("validateDraft", () => {
  const draft = draftFromWorkflow(WORKFLOW);

  it("accepts a valid draft", () => {
    expect(validateDraft(draft, [], {}, {})).toEqual([]);
  });

  it("needs named, unique, short-enough columns with whole-number limits", () => {
    const bad: WorkflowDraft = {
      ...draft,
      columns: [
        ...draft.columns,
        { ...newColumnDraft("a"), name: "  " },
        { ...newColumnDraft("b"), name: "done", category: "done" },
        { ...newColumnDraft("c"), name: "x".repeat(65) },
        { ...newColumnDraft("d"), name: "QA", wipLimit: "0" },
        { ...newColumnDraft("e"), name: "Shipped", category: "done", wipLimit: "abc" },
      ],
    };
    const problems = validateDraft(bad, [], {}, {});
    expect(problems).toHaveLength(4);
    expect(problems.join(" ")).toMatch(/Column 5 needs a name/);
    expect(problems.join(" ")).toMatch(/“done” appears twice/);
    expect(problems.join(" ")).toMatch(/longer than 64/);
    expect(problems.join(" ")).toMatch(/“QA”: a WIP limit/);
  });

  it("needs a to-do and a done column", () => {
    const noDone = drop(draft, "Done");
    expect(validateDraft(noDone, ["Done"], {}, {})).toEqual(["Add at least one “Done” column."]);
    expect(validateDraft({ ...draft, columns: [] }, [], {}, {})).toEqual(["Add at least one column."]);
  });

  it("needs a new home for the cards of a removed column", () => {
    const without = drop(draft, "Backlog");
    const removed = removedColumns(COLUMNS, without);
    expect(validateDraft(without, removed, { backlog: 2 }, {})).toEqual([
        "Choose where the 2 cards in “Backlog” go.",
    ]);
    const target = without.columns[0].uid;
    expect(validateDraft(without, removed, { backlog: 2 }, { Backlog: target })).toEqual([]);
    // An empty removed column needs nothing.
    expect(validateDraft(without, removed, {}, {})).toEqual([]);
  });
});

describe("buildWorkflowUpdate", () => {
  it("sends the columns in order, renames with previous_name, and drops limits on closed columns", () => {
    let draft = draftFromWorkflow(WORKFLOW);
    draft = edit(draft, "To Do", { name: " Ready " });
    draft = edit(draft, "Done", { wipLimit: "4" });
    draft = { ...draft, wipEnforcement: "block" };
    const body = buildWorkflowUpdate(draft, [], {});
    expect(body.wip_enforcement).toBe("block");
    expect(body.name).toBe("Default");
    expect(body.columns).toEqual([
      { name: "Backlog", category: "todo", wip_limit: null },
      { name: "Ready", category: "todo", wip_limit: null, previous_name: "To Do" },
      { name: "In Progress", category: "in_progress", wip_limit: 3 },
      { name: "Done", category: "done", wip_limit: null },
    ]);
    expect(body.move_tasks_to).toEqual({});
  });

  it("names a removed column's new home by the target's current name", () => {
    let draft = drop(draftFromWorkflow(WORKFLOW), "Backlog");
    const target = draft.columns.find((c) => c.originalName === "To Do")!.uid;
    draft = edit(draft, "To Do", { name: "Ready" });
    const body = buildWorkflowUpdate(draft, ["Backlog"], { Backlog: target });
    expect(body.move_tasks_to).toEqual({ Backlog: "Ready" });
  });
});

describe("workflowSourceLabel", () => {
  it("says where the columns come from", () => {
    expect(workflowSourceLabel({ scope: "project", inherited: false })).toMatch(/own columns/);
    expect(workflowSourceLabel({ scope: "team", inherited: true })).toMatch(/Inherited from the team/);
    expect(workflowSourceLabel({ scope: "template", inherited: true })).toMatch(/workspace template/);
    expect(workflowSourceLabel({ scope: "default", inherited: true })).toMatch(/built-in default/);
    expect(workflowSourceLabel({ scope: "tracker", inherited: false })).toMatch(/project’s tracker/);
  });

  it("leaves a tracker's columns read-only", () => {
    expect(workflowEditable({ scope: "tracker" })).toBe(false);
    expect(workflowEditable({ scope: "project" })).toBe(true);
    expect(workflowEditable({ scope: "team" })).toBe(true);
  });
});
