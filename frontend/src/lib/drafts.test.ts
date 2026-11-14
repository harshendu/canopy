import { describe, expect, it } from "vitest";

import type { TrackerBinding, TrackerCapabilities } from "../api/types";
import {
  alreadyFinalized,
  finalizeBlocker,
  finalizeConfirm,
  finalizeLabel,
  finalizeModeOf,
  finalizeSplit,
} from "./drafts";

const CAPS: TrackerCapabilities = {
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

const fresh = { task_id: null, external_id: null, jira_issue_id: null };
const native = { task_id: 12, external_id: null, jira_issue_id: null };
const pushed = { task_id: null, external_id: "10001", jira_issue_id: null };
const legacyPushed = { task_id: null, external_id: null, jira_issue_id: "10002" };

describe("finalize mode + split", () => {
  it("follows the project's tracking mode", () => {
    expect(finalizeModeOf({ mode: "native" })).toBe("native");
    expect(finalizeModeOf({ mode: "mirrored" })).toBe("tracker");
  });

  it("counts what already exists in this mode as an update", () => {
    expect(alreadyFinalized(native, "native")).toBe(true);
    expect(alreadyFinalized(native, "tracker")).toBe(false);
    expect(alreadyFinalized(pushed, "tracker")).toBe(true);
    expect(alreadyFinalized(legacyPushed, "tracker")).toBe(true);
    expect(alreadyFinalized(pushed, "native")).toBe(false);
    expect(finalizeSplit([fresh, native, pushed], "native")).toEqual({ creates: 2, updates: 1 });
    expect(finalizeSplit([fresh, native, pushed, legacyPushed], "tracker")).toEqual({ creates: 2, updates: 2 });
    expect(finalizeSplit([], "native")).toEqual({ creates: 0, updates: 0 });
  });
});

describe("finalize wording", () => {
  it("creates until everything exists, then updates", () => {
    expect(finalizeLabel("native", "Jira", { creates: 2, updates: 1 })).toBe("Create tasks");
    expect(finalizeLabel("native", "Jira", { creates: 0, updates: 3 })).toBe("Update tasks");
    expect(finalizeLabel("tracker", "Linear", { creates: 1, updates: 0 })).toBe("Create Linear tickets");
    expect(finalizeLabel("tracker", "Jira", { creates: 0, updates: 2 })).toBe("Update Jira tickets");
    expect(finalizeLabel("tracker", "Jira", { creates: 0, updates: 0 })).toBe("Create Jira tickets");
  });

  it("states the split before the write", () => {
    const nativeMsg = finalizeConfirm("Q3 plan", "native", "", { creates: 1, updates: 2 });
    expect(nativeMsg).toContain("• create 1 new task\n");
    expect(nativeMsg).toContain("• update 2 existing tasks");
    expect(nativeMsg).toContain("replans");
    const trackerMsg = finalizeConfirm("Q3 plan", "tracker", "Jira", { creates: 3, updates: 0 });
    expect(trackerMsg.startsWith("Push “Q3 plan” to Jira?")).toBe(true);
    expect(trackerMsg).toContain("• create 3 new tickets");
    expect(trackerMsg).toContain("never status");
  });
});

describe("finalizeBlocker", () => {
  const binding: TrackerBinding = {
    id: 1,
    connection_id: 1,
    connection_name: "Jira Cloud",
    provider: "jira",
    label: "Jira",
    scope_kind: "project",
    scope: { project_key: "SHOP" },
    mapping: {},
    status_map: [],
    sync_iterations: false,
    active: true,
    last_synced_at: null,
    detached_at: null,
    created_at: "2026-11-01T09:00:00",
  };
  const bound = { binding, legacy_connection_id: null };
  const conn = { write_strategy: "direct" as const, authorized: true, user_connected: false };

  it("never blocks a native finalise", () => {
    expect(
      finalizeBlocker({ mode: "native", tracking: { binding: null, legacy_connection_id: null }, trackerLabel: "", capabilities: null, connection: null }),
    ).toBeNull();
  });

  it("needs a binding, item creation, direct writes and a credential", () => {
    const input = { mode: "tracker" as const, tracking: bound, trackerLabel: "Jira", capabilities: CAPS, connection: conn };
    expect(finalizeBlocker(input)).toBeNull();
    expect(finalizeBlocker({ ...input, tracking: { binding: null, legacy_connection_id: null } })).toMatchObject({
      fix: "tracking",
      message: expect.stringContaining("no tracker bound"),
    });
    expect(finalizeBlocker({ ...input, tracking: { binding: null, legacy_connection_id: 4 } })).toBeNull();
    expect(finalizeBlocker({ ...input, capabilities: { ...CAPS, create_items: false } })).toMatchObject({
      fix: null,
      message: expect.stringContaining("can't create items"),
    });
    expect(finalizeBlocker({ ...input, connection: { ...conn, write_strategy: "mcp" } })?.message).toContain("via Claude");
    expect(finalizeBlocker({ ...input, connection: { ...conn, write_strategy: "disabled" } })).toEqual({
      message: "Jira writes are disabled by integration policy.",
      fix: null,
    });
    expect(finalizeBlocker({ ...input, connection: { ...conn, authorized: false } })).toEqual({
      message: "The Jira connection isn't authorized yet.",
      fix: "connectors",
    });
    expect(finalizeBlocker({ ...input, connection: { ...conn, authorized: false, user_connected: true } })).toBeNull();
    // Unknown connection (integrations off): the server decides.
    expect(finalizeBlocker({ ...input, connection: null })).toBeNull();
  });
});
