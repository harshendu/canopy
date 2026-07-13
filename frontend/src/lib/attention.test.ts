import { describe, expect, it } from "vitest";

import type { ProjectSummary } from "../api/types";
import { portfolioAttention } from "./attention";

function proj(over: Partial<ProjectSummary>): ProjectSummary {
  return {
    id: 1,
    key: "P",
    name: "Proj",
    total_tasks: 0,
    completed_tasks: 0,
    avg_percent_complete: 0,
    critical_tasks: 0,
    project_end: null,
    target_date: null,
    risk_score: 0,
    risk_level: "low",
    drift_score: 0,
    drift_level: "low",
    tags: [],
    health: null,
    status_note: null,
    open_risks: 0,
    ...over,
  };
}

describe("portfolioAttention", () => {
  it("is silent for a healthy project", () => {
    expect(portfolioAttention([proj({})])).toEqual([]);
  });

  it("flags behind-target when CPM end is past the target date", () => {
    const items = portfolioAttention([
      proj({ project_end: "2026-10-01", target_date: "2026-09-01" }),
    ]);
    expect(items).toHaveLength(1);
    expect(items[0].severity).toBe("error");
    expect(items[0].tab).toBe("gantt");
  });

  it("does not flag when the end is on/before target", () => {
    expect(
      portfolioAttention([proj({ project_end: "2026-08-01", target_date: "2026-09-01" })]),
    ).toEqual([]);
  });

  it("flags elevated risk/drift and off-track health, errors first", () => {
    const items = portfolioAttention([
      proj({ id: 2, risk_level: "high", drift_level: "critical", health: "off_track" }),
    ]);
    // off_track -> error; drift critical -> warning; risk high -> warning
    expect(items).toHaveLength(3);
    expect(items[0].severity).toBe("error");
    expect(items.some((i) => i.tab === "drift")).toBe(true);
  });

  it("treats critical risk as an error, high as a warning", () => {
    expect(portfolioAttention([proj({ risk_level: "critical" })])[0].severity).toBe("error");
    expect(portfolioAttention([proj({ risk_level: "high" })])[0].severity).toBe("warning");
  });

  it("does NOT flag a routinely-tracked open RAID risk — that's normal state, not an exception", () => {
    // Regression guard: the register is a ledger the architect maintains, not an alarm. Almost
    // every real project carries some open risk; treating that as an exception would defeat
    // "green is silent" by showing nearly every project, nearly always.
    expect(portfolioAttention([proj({ open_risks: 3 })])).toEqual([]);
  });
});
