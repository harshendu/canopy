import type { OutboundWebhook, RuleScopeInfo, WebhookEvent } from "../api/types";

/**
 * Outbound webhooks in plain language (USER_FLOWS §AE9): what each event means, a hook's health
 * in one line, and the form's draft → request body. Pure and unit-tested.
 */

export const EVENT_LABEL: Record<WebhookEvent, string> = {
  "work.ready": "Work is ready",
  "gate.opened": "A decision opens",
  "gate.reminder": "A decision waits past its reminder",
  "gate.escalated": "A decision escalates",
  "gate.decided": "A decision is made",
};

export const EVENT_HELP: Record<WebhookEvent, string> = {
  "work.ready":
    "Delegated work became ready for a role — point a runner here. The payload is the task key and role only; the session still claims through canopy.",
  "gate.opened": "A plan, hand-off, sign-off or question is waiting on a person.",
  "gate.reminder": "It has waited past its reminder.",
  "gate.escalated": "More people may decide it now.",
  "gate.decided": "Someone decided it (resume a paused session here).",
};

/** "200 · 4 min ago", "failing (3 in a row): 500 from the destination", "never sent". */
export function hookStatusText(
  hook: Pick<OutboundWebhook, "last_status" | "last_delivery_at" | "consecutive_failures" | "enabled">,
  ago: (iso: string) => string,
): string {
  if (!hook.enabled) return "switched off";
  if (!hook.last_delivery_at) return "never sent";
  if (hook.consecutive_failures > 0) {
    return `failing (${hook.consecutive_failures} in a row): ${hook.last_status ?? "error"}`;
  }
  return `${hook.last_status ?? "sent"} · ${ago(hook.last_delivery_at)}`;
}

export interface HookDraft {
  scope: string; // "<level>:<id>"
  name: string;
  url: string;
  format: "json" | "slack";
  events: WebhookEvent[];
  secret: string;
  clearSecret: boolean;
  enabled: boolean;
}

export function emptyHookDraft(scope: RuleScopeInfo | undefined): HookDraft {
  return {
    scope: scope ? `${scope.scope_level}:${scope.scope_id}` : "",
    name: "",
    url: "",
    format: "json",
    events: ["work.ready"],
    secret: "",
    clearSecret: false,
    enabled: true,
  };
}

export function draftFromHook(hook: OutboundWebhook): HookDraft {
  return {
    scope: `${hook.scope_level}:${hook.scope_id}`,
    name: hook.name,
    url: hook.url,
    format: hook.format,
    events: [...hook.events],
    secret: "",
    clearSecret: false,
    enabled: hook.enabled,
  };
}

/** The create (no `editing`) or update body. An empty secret on an edit keeps the stored one. */
export function hookBody(draft: HookDraft, editing: boolean): Record<string, unknown> {
  const body: Record<string, unknown> = {
    name: draft.name.trim(),
    url: draft.url.trim(),
    format: draft.format,
    events: draft.events,
    enabled: draft.enabled,
  };
  if (!editing) {
    const [level, id] = draft.scope.split(":");
    body.scope_level = level;
    body.scope_id = Number(id);
  }
  if (draft.format === "json" && draft.secret.trim()) body.secret = draft.secret.trim();
  else if (editing && (draft.clearSecret || draft.format === "slack")) body.secret = "";
  return body;
}

/** Why the form can't be sent yet, or null. */
export function hookProblem(draft: HookDraft, editing: boolean): string | null {
  if (!editing && !draft.scope) return "Pick where the webhook lives";
  if (!draft.name.trim()) return "Name it";
  if (!/^https?:\/\/\S+$/.test(draft.url.trim())) return "Give a full https:// URL";
  if (draft.events.length === 0) return "Pick at least one event";
  return null;
}
