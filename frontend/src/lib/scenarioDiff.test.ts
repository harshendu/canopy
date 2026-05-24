import { describe, expect, it } from "vitest";

import type { ScenarioDiff } from "../api/types";
import { deltaTone, formatDayDelta, totalChanges } from "./scenarioDiff";

describe("formatDayDelta", () => {
  it("phrases later, earlier, none, and missing", () => {
    expect(formatDayDelta(null)).toBe("—");
    expect(formatDayDelta(0)).toBe("no change");
    expect(formatDayDelta(3)).toBe("3 days later");
    expect(formatDayDelta(1)).toBe("1 day later");
    expect(formatDayDelta(-2)).toBe("2 days earlier");
  });
});

describe("deltaTone", () => {
  it("is green when earlier, red when later", () => {
    expect(deltaTone(-1)).toContain("canopy");
    expect(deltaTone(5)).toContain("red");
    expect(deltaTone(0)).toContain("slate");
  });
});

describe("totalChanges", () => {
  it("sums every edited-entity counter", () => {
    const diff: ScenarioDiff = {
      tasks_added: 1,
      tasks_removed: 2,
      tasks_changed: 3,
      deps_added: 1,
      deps_removed: 0,
      milestones_changed: 1,
      allocations_changed: 2,
      availability_changed: 1,
      live_project_end: null,
      scenario_project_end: null,
      end_delta_days: null,
      live_cp_working_days: 0,
      scenario_cp_working_days: 0,
      cp_delta_days: 0,
      per_project: [],
    };
    expect(totalChanges(diff)).toBe(11);
  });
});
