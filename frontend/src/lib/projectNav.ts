import type { IconName } from "../components/icons";

/**
 * The project cockpit's two-level navigation, kept pure (no React) so the grouping, feature-gating,
 * and `?tab=` deep-link resolution are unit-testable — `ProjectView` just renders what these return.
 *
 * The 17 leaf views map onto the backend's own feature domains (`app/services/features.py`:
 * planning / tracking / architecture / governance / integrations), plus an at-a-glance **Overview**
 * entry. Leaf keys are unchanged from the old flat tab bar, so every existing `?tab=<leaf>` deep
 * link (the preview drawer, the Drift Sentinel, shared URLs) keeps working and just auto-selects the
 * parent group.
 */

export type ProjectTab =
  | "gantt"
  | "board"
  | "specs"
  | "deps"
  | "capacity"
  | "decisions"
  | "docs"
  | "architecture"
  | "drift"
  | "roadmap"
  | "drafts"
  | "jiralinks"
  | "burndown"
  | "delivery"
  | "risk"
  | "retros"
  | "activity";

export type ProjectGroupKey =
  | "overview"
  | "schedule"
  | "execution"
  | "architecture"
  | "governance"
  | "integrations";

export interface ProjectGroupDef {
  key: ProjectGroupKey;
  label: string;
  icon: IconName;
  /** Leaf views under this group, in display order. Empty for Overview (it is its own view). */
  tabs: ProjectTab[];
}

/** Top-level groups in display order. Overview first — it is the default entry surface. */
export const PROJECT_GROUPS: ProjectGroupDef[] = [
  { key: "overview", label: "Overview", icon: "overview", tabs: [] },
  { key: "schedule", label: "Schedule", icon: "gantt", tabs: ["gantt", "deps", "roadmap"] },
  {
    key: "execution",
    label: "Execution",
    icon: "board",
    tabs: ["board", "capacity", "delivery", "burndown", "activity"],
  },
  {
    key: "architecture",
    label: "Architecture",
    icon: "architecture",
    tabs: ["decisions", "architecture", "drift"],
  },
  { key: "governance", label: "Governance", icon: "governance", tabs: ["risk", "specs", "docs", "retros"] },
  { key: "integrations", label: "Integrations", icon: "jiralinks", tabs: ["drafts", "jiralinks"] },
];

/** The feature gate each leaf sits behind (absent = core, always on). Mirrors the backend catalog. */
export const TAB_FEATURES: Partial<Record<ProjectTab, string>> = {
  board: "tracking.board",
  specs: "governance.specs",
  capacity: "tracking.capacity",
  decisions: "architecture",
  docs: "governance.docs",
  architecture: "architecture",
  drift: "architecture.drift",
  drafts: "planning.draft_plans",
  jiralinks: "integrations",
  burndown: "tracking.burndown",
  delivery: "tracking.delivery",
  risk: "governance.risk",
  retros: "governance.retros",
};

export const TAB_LABELS: Record<ProjectTab, string> = {
  gantt: "Gantt",
  board: "Board",
  specs: "Specs",
  deps: "Dependencies",
  capacity: "Capacity",
  decisions: "Decisions",
  docs: "Docs",
  architecture: "Architecture",
  drift: "Drift",
  roadmap: "Roadmap",
  drafts: "Plan → Jira",
  jiralinks: "Jira Links",
  burndown: "Burndown",
  delivery: "Delivery",
  risk: "Risk",
  retros: "Retros",
  activity: "Activity",
};

export const TAB_ICONS: Record<ProjectTab, IconName> = {
  gantt: "gantt",
  board: "board",
  specs: "specs",
  deps: "deps",
  capacity: "capacity",
  decisions: "decisions",
  docs: "docs",
  architecture: "architecture",
  drift: "drift",
  roadmap: "roadmap",
  drafts: "drafts",
  jiralinks: "jiralinks",
  burndown: "burndown",
  delivery: "delivery",
  risk: "risk",
  retros: "retros",
  activity: "activity",
};

/** Leaf view → the group it lives under (derived from PROJECT_GROUPS). */
export const TAB_GROUP: Record<ProjectTab, ProjectGroupKey> = (() => {
  const map: Partial<Record<ProjectTab, ProjectGroupKey>> = {};
  for (const group of PROJECT_GROUPS) {
    for (const tab of group.tabs) map[tab] = group.key;
  }
  return map as Record<ProjectTab, ProjectGroupKey>;
})();

export type IsFeatureOn = (feature: string) => boolean;

/** Whether a leaf view is enabled (its feature gate is on, or it is core). */
export function tabEnabled(tab: ProjectTab, isOn: IsFeatureOn): boolean {
  const gate = TAB_FEATURES[tab];
  return gate === undefined || isOn(gate);
}

export interface VisibleGroup {
  group: ProjectGroupDef;
  /** The group's enabled leaf views, in display order. */
  tabs: ProjectTab[];
}

/**
 * The nav to render: Overview always, plus each group that still has at least one enabled leaf.
 * A whole group disappears when every one of its features is gated off — so the group headers
 * stay honest without hard-coding group-level gates (a group with a core child never vanishes).
 */
export function visibleProjectNav(isOn: IsFeatureOn): VisibleGroup[] {
  const out: VisibleGroup[] = [];
  for (const group of PROJECT_GROUPS) {
    if (group.key === "overview") {
      out.push({ group, tabs: [] });
      continue;
    }
    const tabs = group.tabs.filter((t) => tabEnabled(t, isOn));
    if (tabs.length > 0) out.push({ group, tabs });
  }
  return out;
}

export interface ResolvedTab {
  group: ProjectGroupKey;
  /** The active leaf, or null when the Overview is active. */
  tab: ProjectTab | null;
}

/**
 * Resolve a requested `?tab=` value (+ the effective feature map) into the active group + leaf.
 * A known, enabled leaf selects that leaf and its parent group; anything else — "overview", absent,
 * unknown, or a gated-off leaf — falls back to the Overview (never a jarring snap to the Gantt).
 */
export function resolveProjectTab(requested: string | null, isOn: IsFeatureOn): ResolvedTab {
  if (requested && requested in TAB_GROUP) {
    const tab = requested as ProjectTab;
    if (tabEnabled(tab, isOn)) return { group: TAB_GROUP[tab], tab };
  }
  return { group: "overview", tab: null };
}

/** The default (first enabled) leaf for a group — where a click on the group header lands. */
export function defaultTabForGroup(key: ProjectGroupKey, isOn: IsFeatureOn): ProjectTab | null {
  const group = PROJECT_GROUPS.find((g) => g.key === key);
  if (!group) return null;
  return group.tabs.find((t) => tabEnabled(t, isOn)) ?? null;
}
