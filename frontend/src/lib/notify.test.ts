import { describe, expect, it } from "vitest";

import type { OutboundWebhook } from "../api/types";
import { draftFromHook, emptyHookDraft, hookBody, hookProblem, hookStatusText } from "./notify";

const HOOK: OutboundWebhook = {
  id: 3,
  scope_level: "project",
  scope_id: 2,
  scope_name: "Payments",
  name: "runner",
  url: "https://runner.example.com/hook",
  format: "json",
  events: ["work.ready", "gate.decided"],
  has_secret: true,
  enabled: true,
  last_delivery_at: "2026-11-15T10:00:00",
  last_status: "200",
  consecutive_failures: 0,
  can_edit: true,
  created_at: "2026-11-01T10:00:00",
};

describe("webhook wording", () => {
  it("says how a hook is doing", () => {
    const ago = () => "4 min ago";
    expect(hookStatusText(HOOK, ago)).toBe("200 · 4 min ago");
    expect(hookStatusText({ ...HOOK, consecutive_failures: 3, last_status: "500 from the destination" }, ago)).toBe(
      "failing (3 in a row): 500 from the destination",
    );
    expect(hookStatusText({ ...HOOK, last_delivery_at: null }, ago)).toBe("never sent");
    expect(hookStatusText({ ...HOOK, enabled: false }, ago)).toBe("switched off");
  });
});

describe("webhook form", () => {
  it("builds the create body with its scope, and keeps a stored secret on edit", () => {
    const draft = {
      ...emptyHookDraft({ scope_level: "team", scope_id: 4, name: "Shop", can_edit: true }),
      name: " slack ",
      url: "https://hooks.slack.example.com/x",
      format: "slack" as const,
      events: ["gate.opened" as const],
    };
    expect(hookBody(draft, false)).toEqual({
      name: "slack",
      url: "https://hooks.slack.example.com/x",
      format: "slack",
      events: ["gate.opened"],
      enabled: true,
      scope_level: "team",
      scope_id: 4,
    });
    const edit = draftFromHook(HOOK);
    expect(hookBody(edit, true)).not.toHaveProperty("secret");
    expect(hookBody({ ...edit, secret: "new" }, true).secret).toBe("new");
    expect(hookBody({ ...edit, clearSecret: true }, true).secret).toBe("");
  });

  it("explains what is missing", () => {
    const draft = emptyHookDraft(undefined);
    expect(hookProblem(draft, false)).toMatch(/where/);
    const scoped = emptyHookDraft({ scope_level: "project", scope_id: 1, name: "P", can_edit: true });
    expect(hookProblem(scoped, false)).toMatch(/Name/);
    expect(hookProblem({ ...scoped, name: "x", url: "runner" }, false)).toMatch(/https/);
    expect(hookProblem({ ...scoped, name: "x", url: "https://a.example.com", events: [] }, false)).toMatch(/event/);
    expect(hookProblem({ ...scoped, name: "x", url: "https://a.example.com" }, false)).toBeNull();
  });
});
