/**
 * The workflow editor's pure logic (USER_FLOWS §C9.1), unit-tested in `workflow.test.ts`: the
 * editable draft of a board's columns, which saved columns a draft removes (the server's rule),
 * validation that mirrors the server's 422s, and the `PUT …/workflow` body.
 */
import type {
  StatusCategory,
  WipEnforcement,
  WorkflowColumn,
  WorkflowColumnInput,
  WorkflowRead,
  WorkflowUpdate,
} from "../api/types";
import { CANOPY_OWNER, CATEGORY_LABELS, fold, isClosedCategory } from "./board";

/** The server's limit on a column (status) name. */
export const MAX_COLUMN_NAME = 64;

export const CATEGORY_ORDER: StatusCategory[] = ["todo", "in_progress", "done", "cancelled"];

export const ENFORCEMENT_LABELS: Record<WipEnforcement, string> = {
  off: "Off — limits are shown, never enforced",
  warn: "Warn — a move into a full column goes through, with a warning",
  block: "Block — a move into a full column is refused",
};

export interface ColumnDraft {
  /** Stable React key — survives renames and reorders. */
  uid: string;
  name: string;
  category: StatusCategory;
  /** The WIP-limit input's text ("" = no limit). */
  wipLimit: string;
  /** The saved column this row edits (null = a new column); a changed name renames it, and
   *  its canopy-owned cards follow. */
  originalName: string | null;
}

export interface WorkflowDraft {
  name: string;
  wipEnforcement: WipEnforcement;
  columns: ColumnDraft[];
}

export function draftFromWorkflow(workflow: WorkflowRead): WorkflowDraft {
  return {
    name: workflow.name,
    wipEnforcement: workflow.wip_enforcement,
    columns: [...workflow.columns]
      .sort((a, b) => a.position - b.position)
      .map((c, i) => ({
        uid: `saved-${i}`,
        name: c.name,
        category: c.category,
        wipLimit: c.wip_limit != null ? String(c.wip_limit) : "",
        originalName: c.name,
      })),
  };
}

export function newColumnDraft(uid: string): ColumnDraft {
  return { uid, name: "", category: "in_progress", wipLimit: "", originalName: null };
}

/** Swap a column with its neighbour (`delta` -1 = left/up, 1 = right/down). */
export function moveColumn(columns: readonly ColumnDraft[], index: number, delta: -1 | 1): ColumnDraft[] {
  const target = index + delta;
  if (index < 0 || index >= columns.length || target < 0 || target >= columns.length) {
    return [...columns];
  }
  const next = [...columns];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

/** The saved columns a draft drops. As on the server, a saved column survives when a draft
 *  column carries its name or renames it — so its cards need no new home. */
export function removedColumns(saved: readonly WorkflowColumn[], draft: WorkflowDraft): string[] {
  const kept = new Set<string>();
  for (const column of draft.columns) {
    kept.add(fold(column.name));
    if (column.originalName && fold(column.originalName) !== fold(column.name)) {
      kept.add(fold(column.originalName));
    }
  }
  return saved.filter((c) => !kept.has(fold(c.name))).map((c) => c.name);
}

/** canopy-owned cards per column (folded name) — what a removed column must rehome. Mirrored
 *  cards keep their tracker's status, so they never block a removal. */
export function occupiedColumns(
  lanes: readonly { status: string; tasks: readonly { status_owner: string }[] }[],
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const lane of lanes) {
    const n = lane.tasks.filter((t) => t.status_owner === CANOPY_OWNER).length;
    if (n > 0) counts[fold(lane.status)] = (counts[fold(lane.status)] ?? 0) + n;
  }
  return counts;
}

function wipLimitValue(text: string): number | null | "invalid" {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  return Number.isInteger(n) && n >= 1 ? n : "invalid";
}

/**
 * What stops the draft from saving, in plain words (empty = it can be saved). Mirrors the
 * server's checks: named, unique columns of at most 64 characters, at least one to-do and one
 * done column, whole-number WIP limits of at least 1, and a new home (`moveTo`, removed column
 * → draft column uid) for every removed column that still holds canopy-owned cards.
 */
export function validateDraft(
  draft: WorkflowDraft,
  removed: readonly string[],
  occupied: Readonly<Record<string, number>>,
  moveTo: Readonly<Record<string, string>>,
): string[] {
  const problems: string[] = [];
  if (draft.columns.length === 0) problems.push("Add at least one column.");
  const seen = new Set<string>();
  draft.columns.forEach((column, i) => {
    const name = column.name.trim();
    if (!name) {
      problems.push(`Column ${i + 1} needs a name.`);
    } else if (name.length > MAX_COLUMN_NAME) {
      problems.push(`“${name.slice(0, 24)}…” is longer than ${MAX_COLUMN_NAME} characters.`);
    } else if (seen.has(fold(name))) {
      problems.push(`“${name}” appears twice — column names must be unique.`);
    }
    if (name) seen.add(fold(name));
    if (!isClosedCategory(column.category) && wipLimitValue(column.wipLimit) === "invalid") {
      problems.push(`“${name || `Column ${i + 1}`}”: a WIP limit is a whole number of at least 1.`);
    }
  });
  for (const needed of ["todo", "done"] as const) {
    if (draft.columns.length > 0 && !draft.columns.some((c) => c.category === needed)) {
      problems.push(`Add at least one “${CATEGORY_LABELS[needed]}” column.`);
    }
  }
  for (const name of removed) {
    const cards = occupied[fold(name)] ?? 0;
    const target = moveTo[name];
    if (cards > 0 && !draft.columns.some((c) => c.uid === target)) {
      problems.push(`Choose where the ${cards} card${cards === 1 ? "" : "s"} in “${name}” go.`);
    }
  }
  return problems;
}

/** The `PUT …/workflow` body: columns in order (a changed name carries `previous_name`, a
 *  closed column drops its WIP limit) and the new home of each removed column's cards. */
export function buildWorkflowUpdate(
  draft: WorkflowDraft,
  removed: readonly string[],
  moveTo: Readonly<Record<string, string>>,
): WorkflowUpdate {
  const nameOf = new Map(draft.columns.map((c) => [c.uid, c.name.trim()]));
  const moveTasksTo: Record<string, string> = {};
  for (const name of removed) {
    const target = nameOf.get(moveTo[name] ?? "");
    if (target) moveTasksTo[name] = target;
  }
  return {
    name: draft.name.trim() || "Default",
    wip_enforcement: draft.wipEnforcement,
    columns: draft.columns.map((c) => {
      const name = c.name.trim();
      const limit = wipLimitValue(c.wipLimit);
      const column: WorkflowColumnInput = {
        name,
        category: c.category,
        wip_limit: isClosedCategory(c.category) || limit === "invalid" ? null : limit,
      };
      if (c.originalName && fold(c.originalName) !== fold(name)) column.previous_name = c.originalName;
      return column;
    }),
    move_tasks_to: moveTasksTo,
  };
}

/** Where a workflow's columns come from, in words for the editor's header. */
export function workflowSourceLabel(workflow: Pick<WorkflowRead, "scope" | "inherited">): string {
  switch (workflow.scope) {
    case "project":
      return "This project has its own columns, overriding its team’s.";
    case "team":
      return workflow.inherited
        ? "Inherited from the team’s columns, shared by its projects."
        : "The team’s columns, shared by its projects.";
    case "template":
      return workflow.inherited
        ? "Inherited from the workspace template."
        : "The workspace template that teams start from.";
    case "default":
      return "The built-in default columns — none have been saved yet.";
  }
}
