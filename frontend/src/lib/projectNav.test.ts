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
  it("places every one of the 18 leaf views under exactly one group", () => {
    const tabs = PROJECT_GROUPS.flatMap((g) => g.tabs);
    expect(tabs).toHaveLength(18);
    expect(new Set(tabs).size).toBe(18); // no duplicates
    for (const tab of tabs) expect(TAB_GROUP[tab]).toBeTruthy();
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

  it("resolves a known leaf and auto-selects its parent group (deep-link contract)", () => {
    expect(resolveProjectTab("gantt", ALL_ON)).toEqual({ group: "schedule", tab: "gantt" });
    expect(resolveProjectTab("drift", ALL_ON)).toEqual({ group: "architecture", tab: "drift" });
    expect(resolveProjectTab("risk", ALL_ON)).toEqual({ group: "governance", tab: "risk" });
    // legacy preview-drawer deep links must still resolve
    expect(resolveProjectTab("decisions", ALL_ON).tab).toBe("decisions");
    expect(resolveProjectTab("board", ALL_ON).tab).toBe("board");
    expect(resolveProjectTab("docs", ALL_ON).tab).toBe("docs");
  });

  it("falls back to Overview for unknown or gated-off tabs (never snaps to Gantt)", () => {
    expect(resolveProjectTab("bogus", ALL_ON)).toEqual({ group: "overview", tab: null });
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
    const keys = visibleProjectNav(ALL_OFF).map((v) => v.group.key);
    // Overview (always), Schedule (gantt/deps/roadmap are core) and Execution (activity is core) survive
    expect(keys).toContain("overview");
    expect(keys).toContain("schedule");
    expect(keys).toContain("execution");
    // fully-gated domains collapse
    expect(keys).not.toContain("architecture");
    expect(keys).not.toContain("governance");
    expect(keys).not.toContain("integrations");
  });

  it("keeps only the enabled leaves inside a partially-gated group", () => {
    const isOn = (f: string) => f !== "tracking.board" && f !== "tracking.delivery";
    const execution = visibleProjectNav(isOn).find((v) => v.group.key === "execution");
    expect(execution?.tabs).toEqual(["capacity", "burndown", "activity"]);
  });
});

describe("defaultTabForGroup", () => {
  it("returns the first enabled leaf a group header should land on", () => {
    expect(defaultTabForGroup("schedule", ALL_ON)).toBe("gantt");
    expect(defaultTabForGroup("execution", ALL_ON)).toBe("board");
    expect(defaultTabForGroup("governance", ALL_ON)).toBe("risk");
    expect(defaultTabForGroup("overview", ALL_ON)).toBeNull();
  });

  it("skips gated-off leaves when choosing the landing view", () => {
    const isOn = (f: string) => f !== "tracking.board";
    expect(defaultTabForGroup("execution", isOn)).toBe("capacity");
  });
});
