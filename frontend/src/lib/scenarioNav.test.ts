import { describe, expect, it } from "vitest";

import {
  SCENARIO_GROUPS,
  SCENARIO_NEEDS_PROJECT,
  SCENARIO_VIEW_GROUP,
  SCENARIO_VIEW_ICONS,
  SCENARIO_VIEW_LABELS,
  defaultScenarioView,
  resolveScenarioView,
  type ScenarioView,
} from "./scenarioNav";

describe("SCENARIO_GROUPS / SCENARIO_VIEW_GROUP", () => {
  it("covers all 10 views with a label, icon, and consistent group mapping", () => {
    const views = Object.keys(SCENARIO_VIEW_GROUP) as ScenarioView[];
    expect(views).toHaveLength(10);
    for (const v of views) {
      expect(SCENARIO_VIEW_LABELS[v]).toBeTruthy();
      expect(SCENARIO_VIEW_ICONS[v]).toBeTruthy();
    }
    // every leaf view listed under a group maps back to that group
    for (const g of SCENARIO_GROUPS) {
      for (const v of g.tabs) expect(SCENARIO_VIEW_GROUP[v]).toBe(g.key);
    }
    // single-view groups (empty tabs) route via their own key
    for (const g of SCENARIO_GROUPS) {
      if (g.tabs.length === 0) expect(SCENARIO_VIEW_GROUP[g.key as ScenarioView]).toBe(g.key);
    }
  });

  it("leads with Compare as the entry group", () => {
    expect(SCENARIO_GROUPS[0].key).toBe("compare");
  });

  it("only per-project projections need a project", () => {
    for (const v of SCENARIO_NEEDS_PROJECT) expect(SCENARIO_VIEW_GROUP[v]).toBeTruthy();
    expect(SCENARIO_NEEDS_PROJECT).not.toContain("compare");
    expect(SCENARIO_NEEDS_PROJECT).not.toContain("capacity"); // capacity is scenario-wide
  });
});

describe("resolveScenarioView", () => {
  it("defaults to Compare when no tab is requested", () => {
    expect(resolveScenarioView(null)).toEqual({ group: "compare", view: "compare" });
    expect(resolveScenarioView("bogus")).toEqual({ group: "compare", view: "compare" });
  });

  it("resolves a view and its parent group", () => {
    expect(resolveScenarioView("gantt")).toEqual({ group: "schedule", view: "gantt" });
    expect(resolveScenarioView("criticalpath")).toEqual({ group: "schedule", view: "criticalpath" });
    expect(resolveScenarioView("board")).toEqual({ group: "execution", view: "board" });
    expect(resolveScenarioView("forecast")).toEqual({ group: "outlook", view: "forecast" });
    expect(resolveScenarioView("edit")).toEqual({ group: "edit", view: "edit" });
    expect(resolveScenarioView("compare")).toEqual({ group: "compare", view: "compare" });
  });
});

describe("defaultScenarioView", () => {
  it("lands a group header on its first sub-view (or itself when single-view)", () => {
    expect(defaultScenarioView("schedule")).toBe("gantt");
    expect(defaultScenarioView("execution")).toBe("board");
    expect(defaultScenarioView("outlook")).toBe("forecast");
    expect(defaultScenarioView("compare")).toBe("compare");
    expect(defaultScenarioView("edit")).toBe("edit");
  });
});
