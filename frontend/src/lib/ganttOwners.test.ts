import { describe, expect, it } from "vitest";

import type { GanttTask } from "../api/types";
import { initials, visibleTaskIds } from "../components/GanttChart";

function task(partial: Partial<GanttTask> & { id: number }): GanttTask {
  return {
    text: `t${partial.id}`,
    start_date: null,
    end_date: null,
    baseline_start: null,
    baseline_end: null,
    deadline: null,
    duration: 1,
    progress: 0,
    parent: 0,
    type: "task",
    is_critical: false,
    total_float: 0,
    assignee_engineer_id: null,
    assignee_name: null,
    ...partial,
  };
}

describe("initials", () => {
  it("takes the first letters of up to two name parts", () => {
    expect(initials("Dana Lee")).toBe("DL");
    expect(initials("Ada")).toBe("A");
    expect(initials("Grace Brewster Murray Hopper")).toBe("GB");
  });
});

describe("visibleTaskIds (owner filter)", () => {
  const phase = task({ id: 1, type: "summary" });
  const mine = task({ id: 2, parent: 1, assignee_engineer_id: 7, assignee_name: "Dana Lee" });
  const theirs = task({ id: 3, parent: 1, assignee_engineer_id: 8, assignee_name: "Sam Roy" });
  const loose = task({ id: 4 }); // unassigned, top-level
  const all = [phase, mine, theirs, loose];

  it("keeps everything without a filter", () => {
    expect(visibleTaskIds(all, "")).toEqual(new Set([1, 2, 3, 4]));
  });

  it("keeps a person's tasks plus their WBS ancestors", () => {
    expect(visibleTaskIds(all, "7")).toEqual(new Set([1, 2]));
  });

  it("filters to unassigned leaf work (summaries don't count as unassigned)", () => {
    expect(visibleTaskIds(all, "none")).toEqual(new Set([4]));
  });

  it("drops phases with no matching descendants", () => {
    expect(visibleTaskIds(all, "99")).toEqual(new Set());
  });
});
