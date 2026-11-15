import type { TrackerCatalog, TrackerInfo } from "../api/types";
import { CONFIG_SCOPE_KEYS, schemaFields, type SchemaField } from "./tracking";

/** How a connector-config field is rendered/coerced. "project" is a canopy-project picker whose
 *  value is stored as a numeric `project_id`; "integer"/"number" are parsed; "boolean" is a
 *  checkbox; the rest are plain typed text inputs. */
export type ConnectorFieldKind =
  | "text"
  | "url"
  | "email"
  | "integer"
  | "number"
  | "boolean"
  | "project";

export interface ConnectorField {
  key: string;
  label: string;
  kind: ConnectorFieldKind;
  placeholder?: string;
  help?: string;
  required?: boolean;
}

/** The providers whose fields are written by hand (every other tracker renders its schema). */
export type BuiltinProvider = "jira" | "github" | "gdrive" | "claude";

export const MIRROR_PROJECT_LABEL = "Mirror into canopy project (optional)";

/** What picking a project on a tracker connection does: it binds the project (§C12). */
export function mirrorProjectHelp(trackerLabel: string): string {
  return (
    `Binds that project to this connection: it becomes mirrored from ${trackerLabel}, and its ` +
    "existing tasks stay canopy-owned. Leave it empty to bind a project later from its Tracking tab."
  );
}

function mirrorField(trackerLabel: string): ConnectorField {
  return {
    key: "project_id",
    label: MIRROR_PROJECT_LABEL,
    kind: "project",
    help: mirrorProjectHelp(trackerLabel),
  };
}

/** The common config keys promoted out of raw JSON into typed inputs. Anything not listed here
 *  still goes through the Advanced (JSON) escape hatch, so power users lose nothing. */
export const CONNECTOR_FIELDS: Record<BuiltinProvider, ConnectorField[]> = {
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
    mirrorField("Jira"),
  ],
  github: [
    { key: "owner", label: "Owner / org", kind: "text", placeholder: "acme" },
    { key: "repo", label: "Repository", kind: "text", placeholder: "platform" },
    { key: "project_id", label: "canopy project", kind: "project" },
  ],
  gdrive: [{ key: "project_id", label: "canopy project", kind: "project" }],
  // The organization artifact sync (USER_FLOWS §V11): the token is the Compliance API key.
  claude: [
    {
      key: "api_version",
      label: "API version (optional)",
      kind: "text",
      placeholder: "2026-10-21",
      help: "The anthropic-version header. Organization ids to limit it to go in Advanced as organization_ids.",
    },
  ],
};

/** What the Claude artifacts connection does, shown next to its form. */
export const CLAUDE_SYNC_HELP =
  "Metadata only: canopy lists your organization's Claude artifacts through the Compliance API " +
  "to keep the docs it already tracks current — published version, who can open them, whether " +
  "they still exist. It never downloads content and never registers anything by itself.";

const BUILTIN_OPTIONS: { value: string; label: string }[] = [
  { value: "github", label: "GitHub" },
  { value: "gdrive", label: "Google Drive" },
];

/** Admin-only: the organization's Claude artifacts (the server refuses anyone else). */
const ADMIN_OPTIONS: { value: string; label: string }[] = [
  { value: "claude", label: "Claude artifacts (organization)" },
];

/** The provider picker: every tracker this instance enables — those canopy reads directly first
 *  (the usual pick), each group by label — then GitHub and Google Drive, and for an admin the
 *  Claude artifact sync. Until the catalog loads (or on a server without one), Jira stands in. */
export function providerOptions(
  catalog: TrackerCatalog | null | undefined,
  { admin = false }: { admin?: boolean } = {},
): { value: string; label: string }[] {
  const trackers = catalog
    ? catalog.trackers
        .filter((t) => t.enabled)
        .sort(
          (a, b) =>
            Number(b.capabilities.direct_read) - Number(a.capabilities.direct_read) ||
            (a.label || a.provider).localeCompare(b.label || b.provider),
        )
        .map((t) => ({ value: t.provider, label: t.label || t.provider }))
    : [{ value: "jira", label: "Jira" }];
  return [...trackers, ...BUILTIN_OPTIONS, ...(admin ? ADMIN_OPTIONS : [])];
}

function schemaKind(field: SchemaField): ConnectorFieldKind {
  if (field.type === "integer" || field.type === "number" || field.type === "boolean") return field.type;
  const key = field.key.toLowerCase();
  if (field.format === "email" || key.includes("email")) return "email";
  if (field.format === "uri" || key.endsWith("url")) return "url";
  return "text";
}

function fromSchema(field: SchemaField, help?: string): ConnectorField {
  return {
    key: field.key,
    label: field.label,
    kind: schemaKind(field),
    required: field.required,
    help: field.description ?? help,
  };
}

/**
 * The connection form for a provider. GitHub and Drive keep their fields, and Jira its typed
 * ones; any other tracker renders its `config_schema`, then the mirror-project picker — and, once
 * a project is picked (`mirroring`), the scope fields the server reads from a new connection's
 * config to bind it (`CONFIG_SCOPE_KEYS`; the rest of a scope is set on the Tracking tab).
 */
export function connectorFields(
  provider: string,
  tracker: TrackerInfo | null,
  { mirroring }: { mirroring: boolean },
): ConnectorField[] {
  if (provider === "github" || provider === "gdrive" || provider === "claude") {
    return CONNECTOR_FIELDS[provider];
  }
  if (provider === "jira") {
    const label = tracker?.label || "Jira";
    return CONNECTOR_FIELDS.jira.map((f) => (f.kind === "project" ? mirrorField(label) : f));
  }
  if (!tracker) return [];
  const config = schemaFields(tracker.config_schema).map((f) => fromSchema(f));
  const fields = [...config.filter((f) => f.key !== "project_id"), mirrorField(tracker.label)];
  if (!mirroring) return fields;
  const taken = new Set(fields.map((f) => f.key));
  const scope = schemaFields(tracker.scope_schema)
    .filter((f) => CONFIG_SCOPE_KEYS.includes(f.key) && !taken.has(f.key))
    .map((f) => fromSchema(f, `Where in ${tracker.label} the project mirrors from.`));
  return [...fields, ...scope];
}

/** Merge the typed field values with the Advanced-JSON escape hatch into the final `config`
 *  object sent to the API. Rules (pure):
 *   - Advanced JSON is the base; typed values override same-named keys (the form is the truth).
 *   - Empty/whitespace-only typed values are omitted (don't clobber an advanced key with "").
 *   - A `project` field coerces to a number; a non-numeric value is dropped.
 *   - An `integer`/`number` field is parsed; a value that isn't one throws (a form error).
 *   - A `boolean` field sends `true` when ticked.
 *   - Invalid or non-object Advanced JSON throws (surfaced as a form error).
 */
export function buildConnectorConfig(
  fields: readonly ConnectorField[],
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
  for (const field of fields) {
    const raw = (values[field.key] ?? "").trim();
    if (!raw) continue;
    if (field.kind === "project") {
      const n = Number(raw);
      if (Number.isFinite(n)) typed[field.key] = n;
    } else if (field.kind === "integer") {
      if (!/^[+-]?\d+$/.test(raw)) throw new Error(`${field.label} must be a whole number`);
      typed[field.key] = Number.parseInt(raw, 10);
    } else if (field.kind === "number") {
      const n = Number(raw);
      if (!Number.isFinite(n)) throw new Error(`${field.label} must be a number`);
      typed[field.key] = n;
    } else if (field.kind === "boolean") {
      if (raw === "true") typed[field.key] = true;
    } else {
      typed[field.key] = raw;
    }
  }
  return { ...advanced, ...typed };
}

/** The required typed fields left empty (the form says which before sending). */
export function missingRequired(
  fields: readonly ConnectorField[],
  values: Record<string, string>,
): string[] {
  return fields
    .filter((f) => f.required && f.kind !== "boolean" && !(values[f.key] ?? "").trim())
    .map((f) => f.label);
}
