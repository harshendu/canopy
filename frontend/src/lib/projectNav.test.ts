import { describe, expect, it } from "vitest";

import {
  PROJECT_GROUPS,
  TAB_GROUP,
  TAB_LABELS,
  defaultTabForGroup,
  resolveProjectTab,
  visibleProjectNav,
  type ProjectTab,
} from "./projectNav";

const ALL_ON = () => true;
const ALL_OFF = () => false;

describe("PROJECT_GROUPS / TAB_GROUP", () => {
  it("places every one of the 22 leaf views under exactly one group", () => {
    const tabs = PROJECT_GROUPS.flatMap((g) => g.tabs);
    expect(tabs).toHaveLength(22);
    expect(new Set(tabs).size).toBe(22); // no duplicates
    for (const tab of tabs) expect(TAB_GROUP[tab]).toBeTruthy();
  });

  it("names the tracker surfaces neutrally", () => {
    expect(TAB_LABELS.tracking).toBe("Tracking");
    expect(TAB_LABELS.trackerlinks).toBe("Tracker links");
    expect(TAB_LABELS.drafts).toBe("Draft plans");
    expect(PROJECT_GROUPS.find((g) => g.key === "integrations")?.tabs).toEqual([
      "tracking",
      "drafts",
      "trackerlinks",
      "notifications",
    ]);
  });

  it("labels every mapped leaf", () => {
    for (const tab of Object.keys(TAB_GROUP) as ProjectTab[]) {
      expect(TAB_LABELS[tab]).toBeTruthy();
    }
  });

  it("leads with Overview as the entry group", () => {
    expect(PROJECT_GROUPS[0].key).toBe("overview");
    expect(PROJECT_GROUPS[0].tabs).toHaveLength(0);
  });
});

describe("resolveProjectTab", () => {
  it("defaults to Overview when no tab is requested", () => {
    expect(resolveProjectTab(null, ALL_ON)).toEqual({ group: "overview", tab: null });
  });

  it("opens the Agents view under Execution, behind the work-queue gate", () => {
    expect(resolveProjectTab("agents", ALL_ON)).toEqual({ group: "execution", tab: "agents" });
    expect(resolveProjectTab("agents", (f) => f !== "ai.work_queue")).toEqual({
      group: "overview",
      tab: null,
    });
  });

  it("opens Notifications under Integrations, behind the outbound gate", () => {
    expect(resolveProjectTab("notifications", ALL_ON)).toEqual({ group: "integrations", tab: "notifications" });
    expect(resolveProjectTab("notifications", (f) => f !== "integrations.outbound").tab).toBeNull();
  });

  it("opens Rules under Governance, behind the stage-policy gate", () => {
    expect(resolveProjectTab("rules", ALL_ON)).toEqual({ group: "governance", tab: "rules" });
    expect(resolveProjectTab("rules", (f) => f !== "ai.stage_policy")).toEqual({
      group: "overview",
      tab: null,
    });
  });

  it("resolves a known leaf and auto-selects its parent group (deep-link contract)", () => {
    expect(resolveProjectTab("gantt", ALL_ON)).toEqual({ group: "schedule", tab: "gantt" });
    expect(resolveProjectTab("drift", ALL_ON)).toEqual({ group: "architecture", tab: "drift" });
    expect(resolveProjectTab("risk", ALL_ON)).toEqual({ group: "governance", tab: "risk" });
    // legacy preview-drawer deep links must still resolve
    expect(resolveProjectTab("decisions", ALL_ON).tab).toBe("decisions");
    expect(resolveProjectTab("board", ALL_ON).tab).toBe("board");
    expect(resolveProjectTab("docs", ALL_ON).tab).toBe("docs");
  });

  it("opens Tracker links, and a retired leaf key lands on the overview", () => {
    expect(resolveProjectTab("trackerlinks", ALL_ON)).toEqual({ group: "integrations", tab: "trackerlinks" });
    expect(resolveProjectTab("trackerlinks", ALL_OFF)).toEqual({ group: "overview", tab: null });
    // `jiralinks` was the Jira-only name (an alias for one release).
    expect(resolveProjectTab("jiralinks", ALL_ON)).toEqual({ group: "overview", tab: null });
  });

  it("opens Tracking even with every gate off (reading it is core)", () => {
    expect(resolveProjectTab("tracking", ALL_OFF)).toEqual({ group: "integrations", tab: "tracking" });
  });

  it("falls back to Overview for unknown or gated-off tabs (never snaps to Gantt)", () => {
    expect(resolveProjectTab("bogus", ALL_ON)).toEqual({ group: "overview", tab: null });
    // Inherited object keys are not leaves.
    expect(resolveProjectTab("toString", ALL_ON)).toEqual({ group: "overview", tab: null });
    // risk requires governance.risk; with everything off it is not reachable
    expect(resolveProjectTab("risk", ALL_OFF)).toEqual({ group: "overview", tab: null });
    // core leaves stay reachable even with every gate off
    expect(resolveProjectTab("gantt", ALL_OFF)).toEqual({ group: "schedule", tab: "gantt" });
  });
});

describe("visibleProjectNav", () => {
  it("shows all six groups when every feature is on", () => {
    const keys = visibleProjectNav(ALL_ON).map((v) => v.group.key);
    expect(keys).toEqual([
      "overview",
      "schedule",
      "execution",
      "architecture",
      "governance",
      "integrations",
    ]);
  });

  it("hides a group only when all of its leaves are gated off; core-bearing groups stay", () => {
    const nav = visibleProjectNav(ALL_OFF);
    const keys = nav.map((v) => v.group.key);
    // Overview (always), Schedule (gantt/deps/roadmap are core), Execution (activity is core) and
    // Integrations (tracking is core) survive
    expect(keys).toContain("overview");
    expect(keys).toContain("schedule");
    expect(keys).toContain("execution");
    expect(nav.find((v) => v.group.key === "integrations")?.tabs).toEqual(["tracking"]);
    // fully-gated domains collapse
    expect(keys).not.toContain("architecture");
    expect(keys).not.toContain("governance");
  });

  it("keeps only the enabled leaves inside a partially-gated group", () => {
    const isOn = (f: string) =>
      f !== "tracking.board" && f !== "tracking.delivery" && f !== "ai.work_queue";
    const execution = visibleProjectNav(isOn).find((v) => v.group.key === "execution");
    expect(execution?.tabs).toEqual(["capacity", "burndown", "activity"]);
  });
});

describe("defaultTabForGroup", () => {
  it("returns the first enabled leaf a group header should land on", () => {
    expect(defaultTabForGroup("schedule", ALL_ON)).toBe("gantt");
    expect(defaultTabForGroup("execution", ALL_ON)).toBe("board");
    expect(defaultTabForGroup("governance", ALL_ON)).toBe("risk");
    expect(defaultTabForGroup("integrations", ALL_ON)).toBe("tracking");
    expect(defaultTabForGroup("overview", ALL_ON)).toBeNull();
  });

  it("skips gated-off leaves when choosing the landing view", () => {
    const isOn = (f: string) => f !== "tracking.board" && f !== "ai.work_queue";
    expect(defaultTabForGroup("execution", isOn)).toBe("capacity");
    expect(defaultTabForGroup("execution", (f) => f !== "tracking.board")).toBe("agents");
  });
});
