import { describe, expect, it } from "vitest";

import type { TrackerCatalog, TrackerInfo } from "../api/types";
import {
  CONNECTOR_FIELDS,
  MIRROR_PROJECT_LABEL,
  buildConnectorConfig,
  connectorFields,
  missingRequired,
  providerOptions,
  splitMirrorProject,
} from "./connectorFields";

const CAPS = {
  direct_read: true,
  hierarchy: true,
  status_categories: true,
  status_history: true,
  iterations: true,
  webhooks: true,
  create_items: true,
  update_items: true,
  estimates: true,
  oauth: true,
};

const optional = (title: string) => ({ anyOf: [{ type: "string" }, { type: "null" }], default: null, title });

// Trackers the UI knows nothing about: their forms come from their JSON Schemas (as the server
// emits them for Linear and the generic tracker).
const LINEAR: TrackerInfo = {
  provider: "linear",
  label: "Linear",
  enabled: true,
  capabilities: CAPS,
  config_schema: {
    properties: { workspace_url_key: optional("Workspace Url Key"), team_key: optional("Team Key") },
  },
  scope_schema: {
    properties: { team_key: optional("Team Key"), project_id: optional("Project Id"), label: optional("Label") },
  },
  webhook_path: "/webhooks/linear",
  webhook_secret_setting: "LINEAR_WEBHOOK_SECRET",
};
const GENERIC: TrackerInfo = {
  ...LINEAR,
  provider: "generic",
  label: "Generic tracker",
  capabilities: { ...CAPS, direct_read: false, create_items: false },
  config_schema: {
    properties: { tracker_name: optional("Tracker Name"), item_url_template: optional("Item Url Template") },
  },
  scope_schema: { properties: { project_key: optional("Project Key") } },
};
// A synthetic one with typed and required config.
const TYPED: TrackerInfo = {
  ...LINEAR,
  provider: "typed",
  label: "Typed",
  config_schema: {
    properties: {
      site_url: optional("Site Url"),
      admin_email: optional("Admin Email"),
      page_size: { type: "integer", title: "Page Size" },
    },
    required: ["page_size"],
  },
  scope_schema: { properties: { team_key: optional("Team Key"), page_size: { type: "integer" } } },
};

const JIRA: TrackerInfo = { ...LINEAR, provider: "jira", label: "Jira Cloud", config_schema: {}, scope_schema: {} };

describe("connectorFields", () => {
  it("every built-in provider has a project picker field", () => {
    for (const p of ["jira", "github", "gdrive"] as const) {
      expect(CONNECTOR_FIELDS[p].some((f) => f.kind === "project")).toBe(true);
    }
  });

  it("labels a tracker's project picker as a mirror binding", () => {
    const picker = connectorFields("jira", JIRA, { mirroring: false }).find((f) => f.kind === "project");
    expect(picker?.label).toBe(MIRROR_PROJECT_LABEL);
    expect(picker?.help).toContain("mirrored from Jira Cloud");
    // Jira keeps its typed fields.
    expect(connectorFields("jira", null, { mirroring: true }).map((f) => f.key)).toEqual([
      "base_url",
      "email",
      "jira_project_key",
      "project_id",
    ]);
    expect(connectorFields("github", JIRA, { mirroring: true })).toBe(CONNECTOR_FIELDS.github);
  });

  it("renders any other tracker from its schemas", () => {
    const fields = connectorFields("linear", LINEAR, { mirroring: false });
    expect(fields.map((f) => [f.key, f.kind, f.label])).toEqual([
      ["workspace_url_key", "text", "Workspace URL key"],
      ["team_key", "text", "Team key"],
      ["project_id", "project", MIRROR_PROJECT_LABEL],
    ]);
    const typed = connectorFields("typed", TYPED, { mirroring: false });
    expect(typed.map((f) => [f.key, f.kind, f.required])).toEqual([
      ["site_url", "url", false],
      ["admin_email", "email", false],
      ["page_size", "integer", true],
      ["project_id", "project", undefined],
    ]);
    expect(connectorFields("linear", null, { mirroring: false })).toEqual([]);
  });

  it("adds the scope keys the server binds from once a project is picked", () => {
    // Linear's team key is already config; its own `project_id`/`label` aren't read from config.
    expect(connectorFields("linear", LINEAR, { mirroring: true }).map((f) => f.key)).toEqual([
      "workspace_url_key",
      "team_key",
      "project_id",
    ]);
    const generic = connectorFields("generic", GENERIC, { mirroring: true });
    expect(generic.map((f) => f.key)).toEqual(["tracker_name", "item_url_template", "project_id", "project_key"]);
    expect(generic[3].help).toBe("Where in Generic tracker the project mirrors from.");
    expect(connectorFields("typed", TYPED, { mirroring: true }).map((f) => f.key)).toContain("team_key");
  });

  it("lists enabled trackers — directly read first, by label — then GitHub and Drive", () => {
    const catalog: TrackerCatalog = {
      trackers: [GENERIC, LINEAR, JIRA, { ...TYPED, enabled: false }],
      default_tracking_mode: "native",
    };
    expect(providerOptions(catalog).map((o) => o.value)).toEqual(["jira", "linear", "generic", "github", "gdrive"]);
    expect(providerOptions(undefined).map((o) => o.label)).toEqual(["Jira", "GitHub", "Google Drive"]);
  });

  it("offers the Claude artifact sync to admins only, with its own fields", () => {
    expect(providerOptions(undefined).map((o) => o.value)).not.toContain("claude");
    expect(providerOptions(undefined, { admin: true }).map((o) => o.value)).toEqual([
      "jira",
      "github",
      "gdrive",
      "claude",
    ]);
    expect(connectorFields("claude", null, { mirroring: false }).map((f) => f.key)).toEqual([
      "api_version",
    ]);
  });
});

describe("buildConnectorConfig", () => {
  it("coerces project_id to a number and keeps typed strings", () => {
    const cfg = buildConnectorConfig(
      CONNECTOR_FIELDS.jira,
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
      CONNECTOR_FIELDS.github,
      { owner: "acme", repo: "  ", project_id: "" },
      '{"repo":"from-advanced"}',
    );
    expect(cfg).toEqual({ owner: "acme", repo: "from-advanced" });
  });

  it("typed values override advanced keys", () => {
    const cfg = buildConnectorConfig(
      CONNECTOR_FIELDS.github,
      { owner: "typed-owner", repo: "", project_id: "" },
      '{"owner":"advanced-owner","extra":true}',
    );
    expect(cfg).toEqual({ owner: "typed-owner", extra: true });
  });

  it("drops a non-numeric project id rather than sending a bad value", () => {
    const cfg = buildConnectorConfig(CONNECTOR_FIELDS.gdrive, { project_id: "not-a-number" }, "");
    expect(cfg).toEqual({});
  });

  it("parses schema-typed integers and refuses bad ones", () => {
    const fields = connectorFields("typed", TYPED, { mirroring: true });
    expect(buildConnectorConfig(fields, { page_size: " 50 ", team_key: "ENG", project_id: "3" }, "")).toEqual({
      page_size: 50,
      team_key: "ENG",
      project_id: 3,
    });
    expect(() => buildConnectorConfig(fields, { page_size: "lots" }, "")).toThrow(/Page size must be a whole number/);
    expect(missingRequired(fields, { page_size: " " })).toEqual(["Page size"]);
    expect(missingRequired(fields, { page_size: "5" })).toEqual([]);
  });

  it("throws on invalid or non-object advanced JSON", () => {
    expect(() => buildConnectorConfig(CONNECTOR_FIELDS.jira, {}, "{not json")).toThrow(/valid JSON/);
    expect(() => buildConnectorConfig(CONNECTOR_FIELDS.jira, {}, "[1,2]")).toThrow(/JSON object/);
  });
});

describe("splitMirrorProject", () => {
  it("lifts a tracker's mirror project out of the config", () => {
    expect(splitMirrorProject({ base_url: "https://x", project_id: 7 }, true)).toEqual({
      config: { base_url: "https://x" },
      projectId: 7,
    });
    // From the Advanced JSON too, and a bad value binds nothing.
    expect(splitMirrorProject({ project_id: "9" }, true)).toEqual({ config: {}, projectId: 9 });
    expect(splitMirrorProject({ project_id: "soon" }, true)).toEqual({ config: {}, projectId: null });
    expect(splitMirrorProject({ team_key: "ENG" }, true)).toEqual({ config: { team_key: "ENG" }, projectId: null });
  });

  it("leaves GitHub and Drive configs alone (their project_id is their own)", () => {
    expect(splitMirrorProject({ owner: "acme", project_id: 3 }, false)).toEqual({
      config: { owner: "acme", project_id: 3 },
      projectId: null,
    });
  });
});
