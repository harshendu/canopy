import { describe, expect, it } from "vitest";

import { CONNECTOR_FIELDS, buildConnectorConfig } from "./connectorFields";

describe("connectorFields", () => {
  it("every provider has a project picker field", () => {
    for (const p of ["jira", "github", "gdrive"] as const) {
      expect(CONNECTOR_FIELDS[p].some((f) => f.kind === "project")).toBe(true);
    }
  });

  it("coerces project_id to a number and keeps typed strings", () => {
    const cfg = buildConnectorConfig(
      "jira",
      {
        base_url: "https://you.atlassian.net",
        email: "you@co.com",
        jira_project_key: "PLAT",
        project_id: "7",
      },
      "{}",
    );
    expect(cfg).toEqual({
      base_url: "https://you.atlassian.net",
      email: "you@co.com",
      jira_project_key: "PLAT",
      project_id: 7,
    });
  });

  it("omits empty typed values (won't clobber an advanced key with '')", () => {
    const cfg = buildConnectorConfig(
      "github",
      { owner: "acme", repo: "  ", project_id: "" },
      '{"repo":"from-advanced"}',
    );
    expect(cfg).toEqual({ owner: "acme", repo: "from-advanced" });
  });

  it("typed values override advanced keys", () => {
    const cfg = buildConnectorConfig(
      "github",
      { owner: "typed-owner", repo: "", project_id: "" },
      '{"owner":"advanced-owner","extra":true}',
    );
    expect(cfg).toEqual({ owner: "typed-owner", extra: true });
  });

  it("drops a non-numeric project id rather than sending a bad value", () => {
    const cfg = buildConnectorConfig("gdrive", { project_id: "not-a-number" }, "");
    expect(cfg).toEqual({});
  });

  it("throws on invalid or non-object advanced JSON", () => {
    expect(() => buildConnectorConfig("jira", {}, "{not json")).toThrow(/valid JSON/);
    expect(() => buildConnectorConfig("jira", {}, "[1,2]")).toThrow(/JSON object/);
  });
});
