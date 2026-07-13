import type { IconName } from "../components/icons";

/**
 * The scenario workspace's two-level navigation, kept pure (no React) so grouping and `?tab=`
 * resolution are unit-testable. Mirrors the project cockpit (`projectNav.ts`) for consistency: a
 * what-if scenario's 10 views collapse into a **Compare** entry (the diff vs. live — the scenario's
 * "overview"), an **Edit** action, and the projected-plan views grouped by the same Schedule /
 * Execution domains, plus an **Outlook** group for the forward-looking forecast + alerts.
 */

export type ScenarioView =
  | "compare"
  | "gantt"
  | "deps"
  | "criticalpath"
  | "capacity"
  | "board"
  | "burndown"
  | "forecast"
  | "alerts"
  | "edit";

export type ScenarioGroupKey = "compare" | "schedule" | "execution" | "outlook" | "edit";

export interface ScenarioGroupDef {
  key: ScenarioGroupKey;
  label: string;
  icon: IconName;
  /** Sub-views under this group. Empty = the group is itself a single view (its key doubles as the
   *  routing key — e.g. Compare, Edit), so it has no secondary sub-nav. */
  tabs: ScenarioView[];
}

/** Top-level groups in display order. Compare first — it is the default entry (the impact diff). */
export const SCENARIO_GROUPS: ScenarioGroupDef[] = [
  { key: "compare", label: "Compare", icon: "compare", tabs: [] },
  { key: "schedule", label: "Schedule", icon: "gantt", tabs: ["gantt", "deps", "criticalpath"] },
  { key: "execution", label: "Execution", icon: "board", tabs: ["board", "capacity", "burndown"] },
  { key: "outlook", label: "Outlook", icon: "forecast", tabs: ["forecast", "alerts"] },
  { key: "edit", label: "Edit", icon: "edit", tabs: [] },
];

export const SCENARIO_VIEW_LABELS: Record<ScenarioView, string> = {
  compare: "Compare to live",
  gantt: "Gantt",
  deps: "Dependencies",
  criticalpath: "Critical path",
  capacity: "Capacity",
  board: "Board",
  burndown: "Burndown",
  forecast: "Forecast",
  alerts: "Alerts",
  edit: "Edit",
};

export const SCENARIO_VIEW_ICONS: Record<ScenarioView, IconName> = {
  compare: "compare",
  gantt: "gantt",
  deps: "deps",
  criticalpath: "criticalpath",
  capacity: "capacity",
  board: "board",
  burndown: "burndown",
  forecast: "forecast",
  alerts: "alerts",
  edit: "edit",
};

/** view → the group it lives under. Single-view groups (compare, edit) map to themselves. */
export const SCENARIO_VIEW_GROUP: Record<ScenarioView, ScenarioGroupKey> = {
  compare: "compare",
  gantt: "schedule",
  deps: "schedule",
  criticalpath: "schedule",
  board: "execution",
  capacity: "execution",
  burndown: "execution",
  forecast: "outlook",
  alerts: "outlook",
  edit: "edit",
};

/** Views that render a per-project projection and so need a selected project in the header picker. */
export const SCENARIO_NEEDS_PROJECT: ScenarioView[] = [
  "gantt",
  "deps",
  "board",
  "burndown",
  "alerts",
];

export interface ResolvedScenarioView {
  group: ScenarioGroupKey;
  view: ScenarioView;
}

/** Resolve a `?tab=` value into {group, view}; absent / unknown → Compare (the default entry). */
export function resolveScenarioView(requested: string | null): ResolvedScenarioView {
  if (requested && requested in SCENARIO_VIEW_GROUP) {
    const view = requested as ScenarioView;
    return { group: SCENARIO_VIEW_GROUP[view], view };
  }
  return { group: "compare", view: "compare" };
}

/** The view a click on a group header lands on (its first sub-view, or itself if single-view). */
export function defaultScenarioView(key: ScenarioGroupKey): ScenarioView {
  const group = SCENARIO_GROUPS.find((g) => g.key === key);
  if (group && group.tabs.length > 0) return group.tabs[0];
  return key === "edit" ? "edit" : "compare";
}
