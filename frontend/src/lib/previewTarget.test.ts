import { describe, expect, it } from "vitest";

import { targetKey, targetKindLabel, targetPath, type PreviewTarget } from "./previewTarget";

describe("targetPath", () => {
  it("builds project routes, optionally deep-linking a tab", () => {
    expect(targetPath({ kind: "project", id: 7 })).toBe("/projects/7");
    expect(targetPath({ kind: "project", id: 7, tab: "decisions" })).toBe(
      "/projects/7?tab=decisions",
    );
  });

  it("builds initiative and scenario routes", () => {
    expect(targetPath({ kind: "initiative", id: 3 })).toBe("/initiatives/3");
    expect(targetPath({ kind: "scenario", id: 9, initiativeId: 3 })).toBe(
      "/initiatives/3/scenarios/9",
    );
  });
});

describe("targetKindLabel", () => {
  it("labels each kind", () => {
    const cases: [PreviewTarget, string][] = [
      [{ kind: "project", id: 1 }, "Project"],
      [{ kind: "initiative", id: 1 }, "Initiative"],
      [{ kind: "scenario", id: 1, initiativeId: 2 }, "Scenario"],
    ];
    for (const [t, label] of cases) expect(targetKindLabel(t)).toBe(label);
  });
});

describe("targetKey", () => {
  it("distinguishes a project's tab deep-links", () => {
    expect(targetKey({ kind: "project", id: 7 })).toBe("project:7");
    expect(targetKey({ kind: "project", id: 7, tab: "decisions" })).toBe("project:7:decisions");
    expect(targetKey({ kind: "initiative", id: 7 })).toBe("initiative:7");
  });
});
