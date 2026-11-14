/**
 * Finalising a draft plan (USER_FLOWS §C10.2), kept pure: whether it makes canopy tasks or the
 * project's tracker items, the create/update split stated before the write, the button and
 * confirm wording, and what stops it. The project's tracking mode decides — never assume Jira.
 */
import type { Connection, DraftTask, ProjectTracking, TrackerCapabilities } from "../api/types";

/** native: canopy tasks; tracker: the bound tracker's items (content only, never status). */
export type FinalizeMode = "native" | "tracker";

export function finalizeModeOf(tracking: Pick<ProjectTracking, "mode">): FinalizeMode {
  return tracking.mode === "mirrored" ? "tracker" : "native";
}

/** Whether a draft task already became real work in this mode — a re-finalise updates it
 *  (the canopy task it created, or the tracker item it created) instead of duplicating. */
export function alreadyFinalized(
  task: Pick<DraftTask, "task_id" | "external_id" | "jira_issue_id">,
  mode: FinalizeMode,
): boolean {
  return mode === "native" ? task.task_id != null : Boolean(task.external_id || task.jira_issue_id);
}

export interface FinalizeSplit {
  creates: number;
  updates: number;
}

export function finalizeSplit(
  tasks: readonly Pick<DraftTask, "task_id" | "external_id" | "jira_issue_id">[],
  mode: FinalizeMode,
): FinalizeSplit {
  const updates = tasks.filter((t) => alreadyFinalized(t, mode)).length;
  return { creates: tasks.length - updates, updates };
}

/** "Create tasks" / "Update Jira tickets" — Update once every draft task exists already. */
export function finalizeLabel(mode: FinalizeMode, trackerLabel: string, split: FinalizeSplit): string {
  const verb = split.creates === 0 && split.updates > 0 ? "Update" : "Create";
  return mode === "native" ? `${verb} tasks` : `${verb} ${trackerLabel} tickets`;
}

function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/** The pre-flight confirm: the split, stated before the write. */
export function finalizeConfirm(
  planTitle: string,
  mode: FinalizeMode,
  trackerLabel: string,
  split: FinalizeSplit,
): string {
  if (mode === "native") {
    return [
      `Create the tasks of “${planTitle}”?`,
      "",
      `• create ${count(split.creates, "new task")}`,
      `• update ${count(split.updates, "existing task")}`,
      "",
      "They join this project's board and schedule, and the project replans.",
    ].join("\n");
  }
  return [
    `Push “${planTitle}” to ${trackerLabel}?`,
    "",
    `• create ${count(split.creates, "new ticket")}`,
    `• update ${count(split.updates, "existing ticket")}`,
    "",
    `This writes to ${trackerLabel} directly — content only, never status. The new items sync back as tasks.`,
  ].join("\n");
}

export interface FinalizeBlocker {
  message: string;
  /** Where it is fixed: the project's Tracking tab, the Connectors page, or not in the UI. */
  fix: "tracking" | "connectors" | null;
}

/** Why the plan can't be finalised right now (null = it can). Tracker mode needs a binding, a
 *  tracker that creates items and a connection that writes directly with a credential. */
export function finalizeBlocker(input: {
  mode: FinalizeMode;
  tracking: Pick<ProjectTracking, "binding" | "legacy_connection_id">;
  trackerLabel: string;
  capabilities: TrackerCapabilities | null;
  connection: Pick<Connection, "write_strategy" | "authorized" | "user_connected"> | null;
}): FinalizeBlocker | null {
  const { mode, tracking, trackerLabel: label, capabilities, connection } = input;
  if (mode === "native") return null;
  if (!tracking.binding && tracking.legacy_connection_id === null) {
    return { message: "This mirrored project has no tracker bound yet — bind one on its Tracking tab.", fix: "tracking" };
  }
  if (capabilities && !capabilities.create_items) {
    return {
      message: `${label} can't create items from canopy — create them with Claude and record them back.`,
      fix: null,
    };
  }
  if (connection?.write_strategy === "mcp") {
    return {
      message: `${label} writes are routed through Claude (MCP) by integration policy — create the tickets via Claude, then record them back.`,
      fix: null,
    };
  }
  if (connection?.write_strategy === "disabled") {
    return { message: `${label} writes are disabled by integration policy.`, fix: null };
  }
  if (connection && !connection.authorized && !connection.user_connected) {
    return { message: `The ${label} connection isn't authorized yet.`, fix: "connectors" };
  }
  return null;
}
