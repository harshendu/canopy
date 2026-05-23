import { describe, expect, it } from "vitest";

import { canContribute, canWriteProjects, isPlanner, isViewer } from "./permissions";

describe("permissions", () => {
  it("planners are admin/architect/eng-manager (and legacy member)", () => {
    expect(isPlanner("admin")).toBe(true);
    expect(isPlanner("architect")).toBe(true);
    expect(isPlanner("engineering_manager")).toBe(true);
    expect(isPlanner("member")).toBe(true);
    expect(isPlanner("engineer")).toBe(false);
    expect(isPlanner("viewer")).toBe(false);
    expect(isPlanner(undefined)).toBe(false);
  });

  it("only admin/architect write projects", () => {
    expect(canWriteProjects("architect")).toBe(true);
    expect(canWriteProjects("engineering_manager")).toBe(false);
    expect(canWriteProjects("engineer")).toBe(false);
  });

  it("everyone but viewer can contribute (propose/comment/own tasks)", () => {
    expect(canContribute("engineer")).toBe(true);
    expect(canContribute("viewer")).toBe(false);
    expect(isViewer("viewer")).toBe(true);
  });
});
