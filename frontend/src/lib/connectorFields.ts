import type { Provider } from "../api/types";

/** How a connector-config field is rendered/coerced. "project" is a canopy-project picker whose
 *  value is stored as a numeric `project_id`; the rest are plain typed text inputs. */
export type ConnectorFieldKind = "text" | "url" | "email" | "project";

export interface ConnectorField {
  key: string;
  label: string;
  kind: ConnectorFieldKind;
  placeholder?: string;
  help?: string;
}

/** The common config keys promoted out of raw JSON into typed inputs, per provider. Anything not
 *  listed here still goes through the Advanced (JSON) escape hatch, so power users lose nothing. */
export const CONNECTOR_FIELDS: Record<Provider, ConnectorField[]> = {
  jira: [
    { key: "base_url", label: "Site URL", kind: "url", placeholder: "https://you.atlassian.net" },
    { key: "email", label: "Account email", kind: "email", placeholder: "you@co.com" },
    {
      key: "jira_project_key",
      label: "Jira project key",
      kind: "text",
      placeholder: "PLAT",
      help: "The short key in issue ids, e.g. PLAT-123 → PLAT.",
    },
    {
      key: "project_id",
      label: "canopy project",
      kind: "project",
      help: "Which canopy project synced issues land in.",
    },
  ],
  github: [
    { key: "owner", label: "Owner / org", kind: "text", placeholder: "acme" },
    { key: "repo", label: "Repository", kind: "text", placeholder: "platform" },
    { key: "project_id", label: "canopy project", kind: "project" },
  ],
  gdrive: [{ key: "project_id", label: "canopy project", kind: "project" }],
};

/** Merge the typed field values with the Advanced-JSON escape hatch into the final `config`
 *  object sent to the API. Rules (pure):
 *   - Advanced JSON is the base; typed values override same-named keys (the form is the truth).
 *   - Empty/whitespace-only typed values are omitted (don't clobber an advanced key with "").
 *   - A `project` field coerces to a number; a non-numeric value is dropped.
 *   - Invalid or non-object Advanced JSON throws (surfaced as a form error).
 */
export function buildConnectorConfig(
  provider: Provider,
  values: Record<string, string>,
  advancedJson: string,
): Record<string, unknown> {
  let advanced: Record<string, unknown> = {};
  const trimmed = advancedJson.trim();
  if (trimmed) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      throw new Error("Advanced config must be valid JSON");
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error("Advanced config must be a JSON object");
    }
    advanced = parsed as Record<string, unknown>;
  }
  const typed: Record<string, unknown> = {};
  for (const field of CONNECTOR_FIELDS[provider]) {
    const raw = (values[field.key] ?? "").trim();
    if (!raw) continue;
    if (field.kind === "project") {
      const n = Number(raw);
      if (Number.isFinite(n)) typed[field.key] = n;
    } else {
      typed[field.key] = raw;
    }
  }
  return { ...advanced, ...typed };
}
