import { describe, expect, it } from "vitest";

import type { DeliveryRule } from "../api/types";
import {
  addableScopes,
  checkDef,
  checksSummary,
  decisionText,
  draftFrom,
  draftProblem,
  emptyDraft,
  evidenceChecks,
  gateSummary,
  hoursText,
  inheritedFrom,
  parseList,
  percent,
  policyPath,
  ruleBody,
  ruleEffectText,
  ruleReachText,
  slugKey,
  workedByText,
} from "./policy";

const RULE: DeliveryRule = {
  id: 4,
  scope_level: "workspace",
  scope_id: 0,
  key: "tests",
  title: "Tests added",
  body: "At the right level",
  kind: "attestation",
  roles: ["implementer"],
  selector: { tags: ["payments"], components: [7], paths: ["api/**"] },
  enforcement: "block",
  locked: true,
  disabled: false,
  source_adr_id: 3,
  source_url: null,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
};

describe("policy wording", () => {
  it("knows every server check and whether canopy saw it or someone stated it", () => {
    expect(checkDef("pr_checks")?.fact).toBe("observed");
    expect(checkDef("verdict")?.fact).toBe("attested");
    expect(checkDef("nope")).toBeUndefined();
  });

  it("says who works a column", () => {
    expect(workedByText({ worked_by: null, hands_off: null })).toBe("No one works it (a queue)");
    expect(workedByText({ worked_by: "human", hands_off: null })).toMatch(/decision column/);
    expect(workedByText({ worked_by: "reviewer", hands_off: "review" })).toBe(
      "Agents work it as reviewer, handing off a review",
    );
  });

  it("summarises entry checks by enforcement", () => {
    expect(
      checksSummary({
        worked_by: "reviewer",
        enter: {
          checks: [
            { check: "artifact", params: { kind: "handoff" }, enforcement: "block" },
            { check: "pr_size", params: { max_changed_lines: 400 }, enforcement: "warn" },
            { check: "verdict", params: { kind: "review", in: ["pass", "concerns"] }, enforcement: "block" },
            { check: "pr_approved", enforcement: "off" },
          ],
        },
      }),
    ).toEqual([
      "Blocks without: An artifact was recorded this round (handoff); A review / QA verdict allows it (review, pass or concerns)",
      "Warns without: The PR is small (400)",
    ]);
    expect(checksSummary(null)).toEqual([]);
  });

  it("explains when a person looks", () => {
    expect(
      gateSummary({
        worked_by: "implementer",
        checkpoints: { plan: { required: true, approval_when: ["one_way_door", "probation:5"] } },
      }),
    ).toEqual([
      "A plan is required; a person approves it when it touches a one-way-door decision or declares a risky change, or fewer than 5 agent tasks are done in the project",
    ]);
    expect(
      decisionText({ approvers: "project_planners", when: "always", satisfied_by: ["canopy", "pr_approval", "pr_merge"] }),
    ).toBe("The project's planners sign off every task · not the requester · a PR approval or merge counts");
  });

  it("finds where a scope's policy is edited", () => {
    expect(policyPath("project", { projectId: 3 })).toBe("/projects/3/workflow/policy");
    expect(policyPath("team", { teamId: 2 })).toBe("/teams/2/workflow/policy");
    expect(policyPath("template", {})).toBe("/workflows/template/policy");
    expect(policyPath("default", { projectId: 3 })).toBeNull();
  });

  it("formats shares and durations", () => {
    expect(percent(0.456)).toBe("46%");
    expect(percent(null)).toBe("—");
    expect(hoursText(3.25)).toBe("3.3 h");
    expect(hoursText(72)).toBe("3 d");
  });
});

describe("rules", () => {
  it("knows which scopes are inherited", () => {
    expect(inheritedFrom("workspace", "project")).toBe(true);
    expect(inheritedFrom("team", "project")).toBe(true);
    expect(inheritedFrom("project", "project")).toBe(false);
    expect(inheritedFrom("project", "team")).toBe(false);
  });

  it("makes keys and lists the server accepts", () => {
    expect(slugKey("Tests added (unit) ")).toBe("tests-added-unit");
    expect(slugKey("--USER_FLOWS.md updated")).toBe("user_flows.md-updated");
    expect(parseList(" Implementer, reviewer,,implementer ", true)).toEqual(["implementer", "reviewer"]);
    expect(parseList("web/**, API/*")).toEqual(["web/**", "API/*"]);
  });

  it("says who a rule reaches and what it does", () => {
    expect(ruleReachText(RULE)).toBe("for implementer · tagged payments · 1 component · paths api/**");
    expect(ruleReachText({ roles: [], selector: {} })).toBe("for every role");
    expect(ruleEffectText("guidance", "block")).toBe("Guidance in the brief");
    expect(ruleEffectText("attestation", "block")).toMatch(/refused/);
    expect(ruleEffectText("attestation", "warn")).toMatch(/flagged/);
  });

  it("offers only the scopes a person may edit", () => {
    const scopes = [
      { scope_level: "workspace" as const, scope_id: 0, name: "Workspace", can_edit: false },
      { scope_level: "project" as const, scope_id: 2, name: "Payments", can_edit: true },
    ];
    expect(addableScopes(scopes).map((s) => s.name)).toEqual(["Payments"]);
    expect(addableScopes(undefined)).toEqual([]);
    expect(emptyDraft(scopes[1]).scope).toBe("project:2");
  });

  it("round-trips a rule through a draft, and overrides lower down unlocked", () => {
    const edit = draftFrom(RULE);
    expect(ruleBody(edit, RULE.selector.components)).toEqual({
      scope_level: "workspace",
      scope_id: 0,
      key: "tests",
      title: "Tests added",
      body: "At the right level",
      kind: "attestation",
      roles: ["implementer"],
      selector: { tags: ["payments"], components: [7], paths: ["api/**"] },
      enforcement: "block",
      locked: true,
      source_adr_id: 3,
      source_url: null,
    });
    const override = draftFrom(RULE, { scope_level: "project", scope_id: 2, name: "P", can_edit: true });
    expect(override.scope).toBe("project:2");
    expect(override.locked).toBe(false);
    expect(ruleBody({ ...override, locked: true }).locked).toBe(false); // nothing below a project
  });

  it("explains what a draft is missing", () => {
    const draft = emptyDraft({ scope_level: "team", scope_id: 1, name: "T", can_edit: true });
    expect(draftProblem(draft)).toMatch(/key/);
    expect(draftProblem({ ...draft, key: "Bad Key", title: "x" })).toMatch(/key/);
    expect(draftProblem({ ...draft, key: "ok" })).toMatch(/title/);
    expect(draftProblem({ ...draft, key: "ok", title: "Ok", body: "x".repeat(801) })).toMatch(/800/);
    expect(draftProblem({ ...draft, key: "ok", title: "Ok" })).toBeNull();
  });
});

describe("gate evidence", () => {
  it("splits what canopy saw from what a session stated", () => {
    const split = evidenceChecks({
      target: "Done",
      results: [
        { check: "pr_checks", label: "CI passes", enforcement: "block", fact: "observed", passed: true, message: "passing" },
        { check: "verdict", enforcement: "warn", fact: "attested", passed: false, message: "concerns" },
        { check: "criteria_met", passed: true }, // older rows: fact from the catalog
        "junk",
      ],
    });
    expect(split?.observed.map((c) => [c.check, c.label])).toEqual([["pr_checks", "The PR's checks pass"]]);
    expect(split?.attested.map((c) => [c.check, c.label])).toEqual([
      ["verdict", "A review / QA verdict allows it"],
      ["criteria_met", "Acceptance criteria are met or waived"],
    ]);
    expect(evidenceChecks({ pull_request: {} })).toBeNull();
    expect(evidenceChecks(undefined)).toBeNull();
  });
});
