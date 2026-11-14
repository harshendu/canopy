import { describe, expect, it } from "vitest";

import type {
  Connection,
  TrackerBinding,
  TrackerCapabilities,
  TrackerCatalog,
  TrackerInfo,
  TrackingSwitchAction,
} from "../api/types";
import {
  actionDetail,
  bindingDraft,
  bindingUpdate,
  capabilityNotes,
  configScope,
  fieldLabel,
  formPayload,
  formValues,
  groupPlan,
  humanizeKey,
  jsonText,
  labelledEntries,
  linkableConnections,
  modeHeadline,
  orderedStatuses,
  ownershipLine,
  parseJsonObject,
  planSummary,
  prefillMapping,
  prefillScope,
  providerLabel,
  sameJson,
  schemaFields,
  strategyOptions,
  switchRequest,
  syncBlocker,
  trackerConnections,
  trackingLabel,
  webhookUrl,
} from "./tracking";

// What Pydantic emits for the Jira tracker (`JiraScope` / `JiraConnectionConfig`).
const JIRA_SCOPE = {
  description: "Where in Jira a binding points.",
  properties: {
    project_key: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Project Key" },
    board_id: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Board Id" },
    jql: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Jql" },
  },
  title: "JiraScope",
  type: "object",
};
const JIRA_CONFIG = {
  properties: {
    base_url: { title: "Base Url", type: "string" },
    email: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Email" },
    auth_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Auth Type" },
  },
  required: ["base_url"],
  title: "JiraConnectionConfig",
  type: "object",
};

const ALL_CAPS: TrackerCapabilities = {
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
// An MCP/file-fed tracker: canopy never reads or writes it directly.
const INGEST_ONLY: TrackerCapabilities = {
  ...ALL_CAPS,
  direct_read: false,
  hierarchy: true,
  iterations: false,
  webhooks: false,
  create_items: false,
  update_items: false,
  oauth: false,
};

function tracker(overrides: Partial<TrackerInfo> = {}): TrackerInfo {
  return {
    provider: "jira",
    label: "Jira",
    enabled: true,
    capabilities: ALL_CAPS,
    config_schema: JIRA_CONFIG,
    scope_schema: JIRA_SCOPE,
    webhook_path: "/webhooks/jira",
    webhook_secret_setting: "JIRA_WEBHOOK_SECRET",
    ...overrides,
  };
}

const CATALOG: TrackerCatalog = {
  trackers: [
    tracker(),
    tracker({ provider: "generic", label: "Generic tracker", capabilities: INGEST_ONLY, enabled: false }),
  ],
  default_tracking_mode: "native",
};

function connection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: 1,
    provider: "jira",
    name: "Jira Cloud",
    config: {},
    watermark: null,
    active: true,
    authorized: true,
    allow_user_connect: false,
    user_connected: false,
    read_strategy: "direct",
    write_strategy: "direct",
    ...overrides,
  };
}

function binding(overrides: Partial<TrackerBinding> = {}): TrackerBinding {
  return {
    id: 7,
    connection_id: 1,
    connection_name: "Jira Cloud",
    provider: "jira",
    label: "Jira",
    scope_kind: "project",
    scope: { project_key: "SHOP", board_id: 1 },
    mapping: { estimate_field: "customfield_10016" },
    status_map: [],
    sync_iterations: true,
    active: true,
    last_synced_at: null,
    detached_at: null,
    created_at: "2026-11-01T09:00:00",
    ...overrides,
  };
}

function action(task_id: number, act: string, overrides: Partial<TrackingSwitchAction> = {}): TrackingSwitchAction {
  return { task_id, name: `Task ${task_id}`, key: null, action: act, detail: null, ...overrides };
}

describe("schemaFields", () => {
  it("reads Pydantic's optional anyOf fields, in the schema's order", () => {
    expect(schemaFields(JIRA_SCOPE)).toEqual([
      { key: "project_key", label: "Project key", type: "string", required: false, format: null, description: null },
      { key: "board_id", label: "Board ID", type: "integer", required: false, format: null, description: null },
      { key: "jql", label: "JQL", type: "string", required: false, format: null, description: null },
    ]);
  });

  it("marks required fields and reads plain types", () => {
    const fields = schemaFields(JIRA_CONFIG);
    expect(fields.map((f) => [f.key, f.type, f.required])).toEqual([
      ["base_url", "string", true],
      ["email", "string", false],
      ["auth_type", "string", false],
    ]);
    expect(fields[0].label).toBe("Base URL");
  });

  it("keeps a custom title and description, and the format", () => {
    const [field] = schemaFields({
      properties: {
        site: { type: "string", format: "uri", title: "Workspace site", description: "Where it lives." },
      },
    });
    expect(field).toMatchObject({ label: "Workspace site", format: "uri", description: "Where it lives." });
  });

  it("skips objects, arrays, refs and ambiguous unions; tolerates junk", () => {
    expect(
      schemaFields({
        properties: {
          tags: { type: "array", items: { type: "string" } },
          nested: { $ref: "#/$defs/Nested" },
          either: { anyOf: [{ type: "string" }, { type: "integer" }] },
          list_form: { type: ["boolean", "null"] },
        },
      }).map((f) => [f.key, f.type]),
    ).toEqual([["list_form", "boolean"]]);
    expect(schemaFields(null)).toEqual([]);
    expect(schemaFields({ properties: [] })).toEqual([]);
  });
});

describe("labels", () => {
  it("humanizes keys with acronyms", () => {
    expect(humanizeKey("board_id")).toBe("Board ID");
    expect(humanizeKey("team_key")).toBe("Team key");
    expect(humanizeKey("jql")).toBe("JQL");
    expect(fieldLabel("api_url", "Api Url")).toBe("API URL");
    expect(fieldLabel("api_url", "Endpoint")).toBe("Endpoint");
  });

  it("labels providers from the catalog, then the built-ins", () => {
    expect(providerLabel("jira", CATALOG)).toBe("Jira");
    expect(providerLabel("generic", CATALOG)).toBe("Generic tracker");
    expect(providerLabel("gdrive", CATALOG)).toBe("Google Drive");
    expect(providerLabel("linear", null)).toBe("linear");
  });

  it("reads the mode and who owns the statuses", () => {
    expect(modeHeadline("native", null)).toBe("Native — canopy owns every status");
    expect(modeHeadline("mirrored", "Jira")).toBe("Mirrored from Jira");
    expect(modeHeadline("mirrored", null)).toBe("Mirrored — no tracker bound yet");
    expect(ownershipLine({ mode: "mirrored", canopy_owned: 4, tracker_owned: 9 }, "Jira")).toBe(
      "canopy owns 4 · Jira owns 9",
    );
    expect(ownershipLine({ mode: "native", canopy_owned: 1, tracker_owned: 0 }, null)).toBe("canopy owns all 1 task");
    expect(ownershipLine({ mode: "native", canopy_owned: 0, tracker_owned: 0 }, null)).toBe("No tasks yet");
  });

  it("names the tracker from the binding, else the legacy connection's provider", () => {
    expect(trackingLabel({ binding: binding(), legacy_connection_id: null }, null)).toBe("Jira");
    expect(trackingLabel({ binding: null, legacy_connection_id: 3 }, "generic", CATALOG)).toBe("Generic tracker");
    expect(trackingLabel({ binding: null, legacy_connection_id: 3 }, null)).toBe("its tracker");
    expect(
      trackingLabel({ binding: null, legacy_connection_id: 3, legacy_label: "Linear" }, null),
    ).toBe("Linear");
    expect(trackingLabel({ binding: null, legacy_connection_id: null }, "jira")).toBeNull();
  });

  it("orders statuses and labels scope entries", () => {
    expect(
      orderedStatuses([
        { name: "Done", category: "done", position: 2 },
        { name: "To Do", category: "todo", position: 0 },
      ]).map((s) => s.name),
    ).toEqual(["To Do", "Done"]);
    expect(labelledEntries({ board_id: 1, project_key: "SHOP", extra: "x", jql: "" }, schemaFields(JIRA_SCOPE))).toEqual([
      { key: "project_key", label: "Project key", value: "SHOP" },
      { key: "board_id", label: "Board ID", value: "1" },
      { key: "extra", label: "Extra", value: "x" },
    ]);
    expect(labelledEntries({ epic_types: ["Epic", "Initiative"] })).toEqual([
      { key: "epic_types", label: "Epic types", value: "Epic, Initiative" },
    ]);
  });

  it("notes what a tracker supports", () => {
    expect(capabilityNotes(ALL_CAPS)).toEqual([
      "canopy reads it directly",
      "sprints",
      "status history",
      "webhooks",
      "canopy can create items in it",
    ]);
    expect(capabilityNotes({ ...INGEST_ONLY, status_history: false, webhooks: true })).toEqual([
      "its items arrive by MCP or file ingest",
      "webhooks",
    ]);
  });

  it("builds the webhook URL", () => {
    expect(webhookUrl("https://canopy.example.com/", "/webhooks/jira")).toBe("https://canopy.example.com/webhooks/jira");
    expect(webhookUrl("http://localhost:5173", "webhooks/linear")).toBe("http://localhost:5173/webhooks/linear");
  });
});

describe("form values ↔ payload", () => {
  const fields = schemaFields(JIRA_SCOPE);

  it("round-trips a stored scope", () => {
    const values = formValues(fields, { project_key: "SHOP", board_id: 1 });
    expect(values).toEqual({ project_key: "SHOP", board_id: "1", jql: "" });
    expect(formPayload(fields, values)).toEqual({ payload: { project_key: "SHOP", board_id: 1 }, errors: [] });
  });

  it("drops empties, trims, parses integers and reports bad ones", () => {
    expect(formPayload(fields, { project_key: "  OPS ", board_id: " 42 ", jql: "   " }).payload).toEqual({
      project_key: "OPS",
      board_id: 42,
    });
    expect(formPayload(fields, { board_id: "4.5" })).toEqual({ payload: {}, errors: ["Board ID must be a whole number."] });
  });

  it("requires required fields; numbers and booleans", () => {
    const config = schemaFields(JIRA_CONFIG);
    expect(formPayload(config, {}).errors).toEqual(["Base URL is required."]);
    const more = schemaFields({
      properties: { weight: { type: "number" }, flag: { type: "boolean" } },
      required: ["flag"],
    });
    expect(formPayload(more, { weight: "2.5", flag: "" }).payload).toEqual({ weight: 2.5, flag: false });
    expect(formPayload(more, { weight: "x", flag: "true" })).toEqual({
      payload: { flag: true },
      errors: ["Weight must be a number."],
    });
    expect(formValues(more, { flag: true, weight: 3 })).toEqual({ weight: "3", flag: "true" });
  });

  it("prefills a scope from a connection's config as the server reads it", () => {
    expect(prefillScope(fields, { jira_project_key: "SHOP", board_id: 1, project_id: 4 })).toEqual({
      project_key: "SHOP",
      board_id: "1",
      jql: "",
    });
    expect(configScope({ jira_project_key: "SHOP", project_key: "OTHER", jql: "x", project_id: 4 })).toEqual({
      project_key: "SHOP",
      jql: "x",
    });
    // Linear's scope has a `project_id` of its own: the config's is canopy's project, never it.
    const linear = schemaFields({
      properties: {
        team_key: { anyOf: [{ type: "string" }, { type: "null" }], title: "Team Key" },
        project_id: { anyOf: [{ type: "string" }, { type: "null" }], title: "Project Id" },
      },
    });
    expect(prefillScope(linear, { team_key: "ENG", project_id: 4 })).toEqual({ team_key: "ENG", project_id: "" });
    expect(prefillScope(fields, null)).toEqual({ project_key: "", board_id: "", jql: "" });
  });

  it("prefills the mapping a connection's config carries", () => {
    expect(
      prefillMapping({ epic_issue_type: "Epic", story_issue_type: "Story", story_point_field: "customfield_10016" }),
    ).toEqual({ epic_types: ["Epic"], item_type: "Story", estimate_field: "customfield_10016" });
    expect(prefillMapping({ jira_project_key: "SHOP" })).toEqual({});
  });

  it("parses an Advanced JSON box", () => {
    expect(parseJsonObject("")).toEqual({ value: {}, error: null });
    expect(parseJsonObject('{"a": 1}')).toEqual({ value: { a: 1 }, error: null });
    expect(parseJsonObject("{oops").error).toBe("Mapping must be valid JSON.");
    expect(parseJsonObject("[1]", "Scope").error).toBe("Scope must be a JSON object.");
    expect(jsonText({})).toBe("");
    expect(JSON.parse(jsonText({ a: [1] }))).toEqual({ a: [1] });
  });

  it("compares JSON whatever the key order", () => {
    expect(sameJson({ a: 1, b: [1, { c: 2, d: 3 }] }, { b: [1, { d: 3, c: 2 }], a: 1 })).toBe(true);
    expect(sameJson({ a: 1 }, { a: "1" })).toBe(false);
    expect(sameJson([1, 2], [2, 1])).toBe(false);
  });
});

describe("connections", () => {
  it("offers active connections of enabled trackers for a switch", () => {
    const conns = [
      connection({ id: 1 }),
      connection({ id: 2, active: false }),
      connection({ id: 3, provider: "github" }),
      connection({ id: 4, provider: "generic" }),
    ];
    expect(trackerConnections(conns, ["jira"]).map((c) => c.id)).toEqual([1]);
    expect(trackerConnections(conns, []).map((c) => c.id)).toEqual([]);
  });

  it("links only through authorized trackers that read directly with a hierarchy", () => {
    const conns = [
      connection({ id: 1 }),
      connection({ id: 2, authorized: false }),
      connection({ id: 3, provider: "generic" }),
      connection({ id: 4, provider: "gdrive" }),
    ];
    expect(linkableConnections(conns, CATALOG).map((c) => c.id)).toEqual([1]);
    expect(linkableConnections(conns, null)).toEqual([]);
  });
});

describe("strategyOptions", () => {
  it("offers all three for a tracker canopy reads and writes", () => {
    const options = strategyOptions(tracker(), connection());
    expect(options.map((o) => [o.value, o.disabledReason])).toEqual([
      ["keep_separate", null],
      ["match", null],
      ["publish", null],
    ]);
    expect(options[1].description).toContain("Jira");
  });

  it("explains what a tracker without direct reads or item creation can't do", () => {
    const [keep, match, publish] = strategyOptions({ label: "Generic tracker", capabilities: INGEST_ONLY });
    expect(keep.disabledReason).toBeNull();
    expect(match.disabledReason).toBe("canopy can't read Generic tracker directly, and matching needs its items.");
    expect(publish.disabledReason).toBe("Generic tracker can't create items from canopy.");
  });

  it("follows the integration policy and the credential", () => {
    const routed = strategyOptions(tracker(), connection({ read_strategy: "mcp", write_strategy: "disabled" }));
    expect(routed[1].disabledReason).toContain("routed through Claude (MCP)");
    expect(routed[2].disabledReason).toBe("Jira writes are disabled by integration policy.");
    const unauthorized = strategyOptions(tracker(), connection({ authorized: false }));
    expect(unauthorized[1].disabledReason).toContain("isn't authorized");
    expect(unauthorized[2].disabledReason).toContain("isn't authorized");
    const personal = strategyOptions(tracker(), connection({ authorized: false, user_connected: true }));
    expect(personal.every((o) => o.disabledReason === null)).toBe(true);
  });
});

describe("syncBlocker", () => {
  it("syncs a directly-read tracker with a credential", () => {
    expect(syncBlocker("Jira", ALL_CAPS, connection())).toBeNull();
    expect(syncBlocker("Jira", ALL_CAPS, null)).toBeNull();
    expect(syncBlocker("Jira", null, connection({ authorized: false, user_connected: true }))).toBeNull();
  });

  it("says why it can't", () => {
    expect(syncBlocker("Generic", INGEST_ONLY, connection())).toBe(
      "canopy doesn't read Generic directly — its items arrive by MCP or file ingest.",
    );
    expect(syncBlocker("Jira", ALL_CAPS, connection({ read_strategy: "file" }))).toBe(
      "Jira reads are loaded from file drops by integration policy.",
    );
    expect(syncBlocker("Jira", ALL_CAPS, connection({ authorized: false }))).toContain("isn't authorized");
  });
});

describe("groupPlan / planSummary", () => {
  const plan = [
    action(1, "keep"),
    action(2, "adopt", { key: "SHOP-1", detail: "matched SHOP-1" }),
    action(3, "remap", { detail: "In Review → In progress" }),
    action(4, "keep"),
    action(5, "split"),
    action(6, "release", { detail: "jira" }),
  ];

  it("groups in reading order, unknown actions last", () => {
    const groups = groupPlan(plan, { from: "Jira", to: null, toMode: "native" });
    expect(groups.map((g) => [g.action, g.items.map((i) => i.task_id)])).toEqual([
      ["adopt", [2]],
      ["release", [6]],
      ["remap", [3]],
      ["keep", [1, 4]],
      ["split", [5]],
    ]);
    expect(groups[1].hint).toContain("leave Jira");
    expect(groups[3].label).toBe("Unchanged");
    expect(groups[4]).toMatchObject({ label: "split", hint: "" });
  });

  it("words keep and publish for a switch onto a tracker", () => {
    const groups = groupPlan([action(1, "keep"), action(2, "publish")], { from: null, to: "Jira", toMode: "mirrored" });
    expect(groups.map((g) => g.label)).toEqual(["Published to Jira", "Stay canopy-owned"]);
    expect(groupPlan([], { from: null, to: "Jira", toMode: "mirrored" })).toEqual([]);
  });

  it("words a row's detail", () => {
    expect(actionDetail({ action: "release", detail: "generic" }, CATALOG)).toBe("from Generic tracker");
    expect(actionDetail({ action: "remap", detail: "Todo → Backlog" }, CATALOG)).toBe("Todo → Backlog");
    expect(actionDetail({ action: "keep", detail: null })).toBe("");
  });

  it("summarises the counts", () => {
    expect(planSummary({ keep: 10, adopt: 3, release: 0 })).toBe("3 adopted · 10 kept");
    expect(planSummary({ split: 2, publish: 1 })).toBe("1 published · 2 split");
    expect(planSummary({})).toBe("No tasks to move");
  });
});

describe("switchRequest", () => {
  const base = {
    scopeFields: schemaFields(JIRA_SCOPE),
    scopeValues: { project_key: "OPS", board_id: "", jql: "" },
    mappingText: '{"estimate_field": "customfield_10016"}',
    syncIterations: true,
    strategy: "match" as const,
    capabilities: ALL_CAPS,
  };

  it("needs a target", () => {
    expect(switchRequest({ ...base, target: null }).request).toBeNull();
  });

  it("sends a native switch without scope or strategy", () => {
    expect(switchRequest({ ...base, target: "native" }).request).toEqual({
      to_mode: "native",
      connection_id: null,
      scope: {},
      mapping: {},
      sync_iterations: false,
      strategy: "keep_separate",
      dry_run: true,
    });
  });

  it("previews a mirrored switch with the typed scope and mapping", () => {
    expect(switchRequest({ ...base, target: 4 })).toEqual({
      request: {
        to_mode: "mirrored",
        connection_id: 4,
        scope: { project_key: "OPS" },
        mapping: { estimate_field: "customfield_10016" },
        sync_iterations: true,
        strategy: "match",
        dry_run: true,
      },
      errors: [],
    });
    // Sprint mirroring only where the tracker has iterations.
    expect(switchRequest({ ...base, target: 4, capabilities: INGEST_ONLY }).request?.sync_iterations).toBe(false);
  });

  it("reports what can't be sent", () => {
    expect(
      switchRequest({ ...base, target: 4, scopeValues: { board_id: "one" }, mappingText: "[]" }),
    ).toEqual({ request: null, errors: ["Board ID must be a whole number.", "Mapping must be a JSON object."] });
  });
});

describe("bindingUpdate", () => {
  const fields = schemaFields(JIRA_SCOPE);

  it("sends nothing for an untouched binding", () => {
    const b = binding();
    expect(bindingUpdate(b, fields, bindingDraft(b, fields), ALL_CAPS)).toEqual({
      update: {},
      errors: [],
      scopeChanged: false,
    });
  });

  it("sends only what changed, flagging a new scope", () => {
    const b = binding();
    const draft = { ...bindingDraft(b, fields), scopeValues: { project_key: "SHOP", board_id: "", jql: "" }, syncIterations: false };
    expect(bindingUpdate(b, fields, draft, ALL_CAPS)).toEqual({
      update: { scope: { project_key: "SHOP" }, sync_iterations: false },
      errors: [],
      scopeChanged: true,
    });
    const mapped = { ...bindingDraft(b, fields), mappingText: '{"estimate_field": "customfield_1"}' };
    expect(bindingUpdate(b, fields, mapped, ALL_CAPS).update).toEqual({ mapping: { estimate_field: "customfield_1" } });
  });

  it("keeps scope keys the form can't show, and ignores sprints without iterations", () => {
    const b = binding({ scope: { project_key: "SHOP", components: ["web"] } });
    const draft = { ...bindingDraft(b, fields), syncIterations: false };
    expect(bindingUpdate(b, fields, draft, INGEST_ONLY)).toEqual({ update: {}, errors: [], scopeChanged: false });
  });

  it("reports bad input instead of sending it", () => {
    const b = binding();
    const draft = { ...bindingDraft(b, fields), mappingText: "{" };
    expect(bindingUpdate(b, fields, draft, ALL_CAPS)).toEqual({
      update: {},
      errors: ["Mapping must be valid JSON."],
      scopeChanged: false,
    });
  });
});
