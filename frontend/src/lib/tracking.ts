/**
 * A project's tracking (USER_FLOWS §C12), kept pure so the Tracking tab, the switch wizard and
 * the Connectors form share one tested reading of the tracker catalog: forms rendered from a
 * tracker's JSON Schemas (`config_schema` / `scope_schema`), the switch plan grouped for review,
 * which strategies a tracker + connection allow (and why not), and the labels. Nothing here
 * assumes Jira — a tracker is whatever `GET /meta/trackers` lists.
 */
import type {
  Connection,
  ProjectTracking,
  ProjectTrackingUpdate,
  TrackerBinding,
  TrackerCapabilities,
  TrackerCatalog,
  TrackerInfo,
  TrackerStatus,
  TrackingMode,
  TrackingStrategy,
  TrackingSwitchAction,
  TrackingSwitchRequest,
} from "../api/types";

// --------------------------------------------------------------------------- //
// Forms from JSON Schema
// --------------------------------------------------------------------------- //

export type SchemaFieldType = "string" | "integer" | "number" | "boolean";

/** One input a tracker's JSON Schema describes. */
export interface SchemaField {
  key: string;
  label: string;
  type: SchemaFieldType;
  required: boolean;
  /** The schema's `format` ("uri", "email"…), when it gives one. */
  format: string | null;
  description: string | null;
}

/** A form's raw input text by field key ("true" / "" for a checkbox). */
export type FormValues = Record<string, string>;

const FIELD_TYPES: readonly string[] = ["string", "integer", "number", "boolean"];
const ACRONYMS: Record<string, string> = {
  api: "API",
  id: "ID",
  jql: "JQL",
  sso: "SSO",
  uri: "URI",
  url: "URL",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** "board_id" → "Board ID", "project_key" → "Project key", "jql" → "JQL". */
export function humanizeKey(key: string): string {
  const words = key
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => ACRONYMS[w.toLowerCase()] ?? w.toLowerCase());
  if (words.length === 0) return key;
  const [first, ...rest] = words;
  return [first.charAt(0).toUpperCase() + first.slice(1), ...rest].join(" ");
}

/** Pydantic's default title for a field: each `_`-separated word capitalised ("Board Id"). */
function defaultTitle(key: string): string {
  return key
    .split("_")
    .map((w) => (w ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : w))
    .join(" ");
}

/** A field's label: the schema's own title, unless it is only the key title-cased (Pydantic's
 *  default, "Board Id") — that reads better humanized ("Board ID"). */
export function fieldLabel(key: string, title: unknown): string {
  if (typeof title === "string" && title.trim() && title !== defaultTitle(key)) return title;
  return humanizeKey(key);
}

function scalarType(prop: Record<string, unknown>): { type: SchemaFieldType; format: string | null } | null {
  const format = typeof prop.format === "string" ? prop.format : null;
  if (typeof prop.type === "string") {
    return FIELD_TYPES.includes(prop.type) ? { type: prop.type as SchemaFieldType, format } : null;
  }
  if (Array.isArray(prop.type)) {
    // `{"type": ["string", "null"]}`
    const types = prop.type.filter((t) => t !== "null");
    return types.length === 1 && typeof types[0] === "string" && FIELD_TYPES.includes(types[0])
      ? { type: types[0] as SchemaFieldType, format }
      : null;
  }
  return null;
}

function propertyType(prop: Record<string, unknown>): { type: SchemaFieldType; format: string | null } | null {
  const direct = scalarType(prop);
  if (direct) return direct;
  // Pydantic's optional field: `{anyOf: [{type: X}, {type: "null"}], default: null}`.
  for (const combinator of ["anyOf", "oneOf"] as const) {
    const options = prop[combinator];
    if (!Array.isArray(options)) continue;
    const typed = options.filter((o): o is Record<string, unknown> => isRecord(o) && o.type !== "null");
    if (typed.length === 1) return scalarType(typed[0]);
  }
  return null;
}

/**
 * The inputs a JSON Schema describes, in its own order: plain `{type}` properties and Pydantic's
 * optional `{anyOf: [{type: X}, {type: "null"}]}`. Objects, arrays and `$ref`s aren't simple
 * inputs — the Advanced (JSON) box carries them.
 */
export function schemaFields(schema: unknown): SchemaField[] {
  if (!isRecord(schema) || !isRecord(schema.properties)) return [];
  const required = new Set(
    Array.isArray(schema.required)
      ? schema.required.filter((r): r is string => typeof r === "string")
      : [],
  );
  const out: SchemaField[] = [];
  for (const [key, raw] of Object.entries(schema.properties)) {
    if (!isRecord(raw)) continue;
    const typed = propertyType(raw);
    if (!typed) continue;
    out.push({
      key,
      label: fieldLabel(key, raw.title),
      type: typed.type,
      required: required.has(key),
      format: typed.format,
      description: typeof raw.description === "string" ? raw.description : null,
    });
  }
  return out;
}

function asText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** A stored payload (a binding's scope, a connection's config) as form text. */
export function formValues(
  fields: readonly SchemaField[],
  source: Record<string, unknown> | null | undefined,
): FormValues {
  const out: FormValues = {};
  for (const f of fields) {
    const value = source?.[f.key];
    out[f.key] = f.type === "boolean" ? (value === true || value === "true" ? "true" : "") : asText(value);
  }
  return out;
}

export interface PayloadResult {
  payload: Record<string, unknown>;
  /** One sentence per field that can't be sent as typed. */
  errors: string[];
}

/** Form text → the payload the API takes: strings trimmed, integers and numbers parsed, a
 *  checkbox `true` when ticked; empty inputs are dropped (a required one is an error). */
export function formPayload(fields: readonly SchemaField[], values: FormValues): PayloadResult {
  const payload: Record<string, unknown> = {};
  const errors: string[] = [];
  for (const f of fields) {
    const raw = (values[f.key] ?? "").trim();
    if (f.type === "boolean") {
      if (raw === "true") payload[f.key] = true;
      else if (f.required) payload[f.key] = false;
      continue;
    }
    if (!raw) {
      if (f.required) errors.push(`${f.label} is required.`);
      continue;
    }
    if (f.type === "integer") {
      if (/^[+-]?\d+$/.test(raw)) payload[f.key] = Number.parseInt(raw, 10);
      else errors.push(`${f.label} must be a whole number.`);
    } else if (f.type === "number") {
      const n = Number(raw);
      if (Number.isFinite(n)) payload[f.key] = n;
      else errors.push(`${f.label} must be a number.`);
    } else {
      payload[f.key] = raw;
    }
  }
  return { payload, errors };
}

function present(value: unknown): boolean {
  return value !== undefined && value !== null && value !== "";
}

/**
 * The scope keys the server reads from a tracker connection's config when it binds a project
 * (`tracker_sync.config_scope`); the rest of a scope is set on the project's Tracking tab.
 */
export const CONFIG_SCOPE_KEYS: readonly string[] = ["project_key", "team_key", "board_id", "jql"];

/** The scope a connection's config names, read as the server reads it: Jira's pre-binding
 *  `jira_project_key` stands for `project_key`. */
export function configScope(config: Record<string, unknown> | null | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (present(config?.jira_project_key)) out.project_key = asText(config?.jira_project_key);
  for (const key of CONFIG_SCOPE_KEYS) {
    if (!(key in out) && present(config?.[key])) out[key] = config?.[key];
  }
  return out;
}

/** A binding scope prefilled from a tracker connection's config (e.g. Jira's project key and
 *  board, Linear's team key). */
export function prefillScope(
  fields: readonly SchemaField[],
  config: Record<string, unknown> | null | undefined,
): FormValues {
  return formValues(fields, configScope(config));
}

/** The type/field mapping a connection's config carries (the server's `config_mapping`). */
export function prefillMapping(
  config: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  const text = (key: string): string => {
    const value = config?.[key];
    return typeof value === "string" || typeof value === "number" ? String(value).trim() : "";
  };
  const out: Record<string, unknown> = {};
  if (text("epic_issue_type")) out.epic_types = [text("epic_issue_type")];
  if (text("story_issue_type")) out.item_type = text("story_issue_type");
  if (text("story_point_field")) out.estimate_field = text("story_point_field");
  return out;
}

/** An "Advanced (JSON)" box: empty is `{}`; anything but a JSON object is an error. */
export function parseJsonObject(
  text: string,
  what = "Mapping",
): { value: Record<string, unknown>; error: string | null } {
  const trimmed = text.trim();
  if (!trimmed) return { value: {}, error: null };
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return { value: {}, error: `${what} must be valid JSON.` };
  }
  if (!isRecord(parsed)) return { value: {}, error: `${what} must be a JSON object.` };
  return { value: parsed, error: null };
}

/** Pretty JSON for an Advanced box ("" for an empty object). */
export function jsonText(value: Record<string, unknown>): string {
  return Object.keys(value).length === 0 ? "" : JSON.stringify(value, null, 2);
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value ?? null);
}

/** Two JSON values are equal whatever their key order. */
export function sameJson(a: unknown, b: unknown): boolean {
  return canonical(a) === canonical(b);
}

// --------------------------------------------------------------------------- //
// Catalog + labels
// --------------------------------------------------------------------------- //

const FALLBACK_LABELS: Record<string, string> = {
  claude: "Claude artifacts",
  gdrive: "Google Drive",
  github: "GitHub",
  jira: "Jira",
};

export function trackerInfo(
  catalog: TrackerCatalog | null | undefined,
  provider: string | null | undefined,
): TrackerInfo | null {
  if (!catalog || !provider) return null;
  return catalog.trackers.find((t) => t.provider === provider) ?? null;
}

/** A provider's display name: the tracker catalog's label, else GitHub / Google Drive, else
 *  its key. */
export function providerLabel(provider: string, catalog?: TrackerCatalog | null): string {
  return trackerInfo(catalog, provider)?.label || FALLBACK_LABELS[provider] || provider;
}

/** Connections a project can be switched onto: active, of a tracker this instance enables. */
export function trackerConnections(
  connections: readonly Connection[] | undefined,
  trackersEnabled: readonly string[],
): Connection[] {
  const enabled = new Set(trackersEnabled);
  return (connections ?? []).filter((c) => c.active && enabled.has(c.provider));
}

/** Connections a tracker link reads through: active and authorized, of a tracker that reads
 *  directly and has a hierarchy (an item's subtree). */
export function linkableConnections(
  connections: readonly Connection[] | undefined,
  catalog: TrackerCatalog | null | undefined,
): Connection[] {
  return (connections ?? []).filter((c) => {
    const tracker = trackerInfo(catalog, c.provider);
    return (
      c.active &&
      c.authorized &&
      tracker !== null &&
      tracker.capabilities.direct_read &&
      tracker.capabilities.hierarchy
    );
  });
}

/** The tracker a project's tracking names: its binding's (null when nothing is bound). */
export function trackingLabel(tracking: Pick<ProjectTracking, "binding">): string | null {
  return tracking.binding?.label ?? null;
}

/** "Native — canopy owns every status" / "Mirrored from Jira". */
export function modeHeadline(mode: TrackingMode, label: string | null): string {
  if (mode === "native") return "Native — canopy owns every status";
  return label ? `Mirrored from ${label}` : "Mirrored — no tracker bound yet";
}

function tasks(n: number): string {
  return `${n} task${n === 1 ? "" : "s"}`;
}

/** Who owns how many statuses: "canopy owns 12 · Jira owns 30". */
export function ownershipLine(
  tracking: Pick<ProjectTracking, "mode" | "canopy_owned" | "tracker_owned">,
  label: string | null,
): string {
  if (tracking.mode === "native" && tracking.tracker_owned === 0) {
    return tracking.canopy_owned === 0 ? "No tasks yet" : `canopy owns all ${tasks(tracking.canopy_owned)}`;
  }
  return `canopy owns ${tracking.canopy_owned} · ${label ?? "the tracker"} owns ${tracking.tracker_owned}`;
}

/** A tracker's statuses in its own order. */
export function orderedStatuses(statusMap: readonly TrackerStatus[]): TrackerStatus[] {
  return [...statusMap].sort((a, b) => a.position - b.position);
}

export interface LabelledEntry {
  key: string;
  label: string;
  value: string;
}

/** A scope or mapping as labelled entries: the schema's fields in order, other keys after. */
export function labelledEntries(
  values: Record<string, unknown>,
  fields: readonly SchemaField[] = [],
): LabelledEntry[] {
  const show = (v: unknown): string =>
    Array.isArray(v) ? v.map((x) => asText(x)).join(", ") : asText(v);
  const known = new Set(fields.map((f) => f.key));
  const out: LabelledEntry[] = [];
  for (const f of fields) {
    if (present(values[f.key])) out.push({ key: f.key, label: f.label, value: show(values[f.key]) });
  }
  for (const [key, value] of Object.entries(values)) {
    if (!known.has(key) && present(value)) out.push({ key, label: humanizeKey(key), value: show(value) });
  }
  return out;
}

/** What a tracker supports, a few words each — enough to choose one by. */
export function capabilityNotes(capabilities: TrackerCapabilities): string[] {
  const out = [capabilities.direct_read ? "canopy reads it directly" : "its items arrive by MCP or file ingest"];
  if (capabilities.iterations) out.push("sprints");
  if (capabilities.status_history) out.push("status history");
  if (capabilities.webhooks) out.push("webhooks");
  if (capabilities.create_items) out.push("canopy can create items in it");
  return out;
}

/** The URL a tracker posts its webhooks to. */
export function webhookUrl(origin: string, path: string): string {
  return `${origin.replace(/\/+$/, "")}${path.startsWith("/") ? path : `/${path}`}`;
}

// --------------------------------------------------------------------------- //
// Switching
// --------------------------------------------------------------------------- //

export interface StrategyOption {
  value: TrackingStrategy;
  label: string;
  /** One line: what happens to the project's existing tasks. */
  description: string;
  /** Why it can't be picked for this tracker and connection (null = it can). */
  disabledReason: string | null;
}

type ConnectionAccess = Pick<
  Connection,
  "read_strategy" | "write_strategy" | "authorized" | "user_connected"
>;

const ROUTED: Record<string, string> = {
  disabled: "disabled",
  file: "loaded from file drops",
  mcp: "routed through Claude (MCP)",
};

/**
 * The three strategies for a switch onto `tracker` through `connection`. `match` needs canopy
 * to read the tracker's items (direct reads + a credential); `publish` needs it to create items
 * (the capability, direct writes + a credential) — as the server checks before it plans.
 */
export function strategyOptions(
  tracker: Pick<TrackerInfo, "label" | "capabilities">,
  connection?: ConnectionAccess | null,
): StrategyOption[] {
  const { label, capabilities } = tracker;
  const credential = connection ? connection.authorized || connection.user_connected : true;
  let match: string | null = null;
  if (!capabilities.direct_read) {
    match = `canopy can't read ${label} directly, and matching needs its items.`;
  } else if (connection && connection.read_strategy !== "direct") {
    match = `${label} reads are ${ROUTED[connection.read_strategy] ?? connection.read_strategy} by integration policy, and matching needs canopy to read its items.`;
  } else if (!credential) {
    match = `This connection isn't authorized yet — connect it so canopy can read ${label}.`;
  }
  let publish: string | null = null;
  if (!capabilities.create_items) {
    publish = `${label} can't create items from canopy.`;
  } else if (connection && connection.write_strategy !== "direct") {
    publish = `${label} writes are ${ROUTED[connection.write_strategy] ?? connection.write_strategy} by integration policy.`;
  } else if (!credential) {
    publish = `This connection isn't authorized yet — connect it so canopy can write to ${label}.`;
  }
  return [
    {
      value: "keep_separate",
      label: "Keep separate",
      description: `Existing tasks stay canopy-owned work beside the items mirrored from ${label}.`,
      disabledReason: null,
    },
    {
      value: "match",
      label: "Match",
      description: `A task whose key — else unique title — matches a ${label} item is adopted by it, and ${label} owns its status from then on. The rest stay canopy-owned.`,
      disabledReason: match,
    },
    {
      value: "publish",
      label: "Publish",
      description: `Open tasks are created as ${label} items (content only — they start in ${label}'s first status) and owned by ${label}. Done and cancelled work stays canopy history.`,
      disabledReason: publish,
    },
  ];
}

/** Why "Sync now" can't pull this tracker through this connection (null = it can): canopy
 *  must read it directly, by policy, with a credential — as `POST /tracking/sync` checks. */
export function syncBlocker(
  label: string,
  capabilities: TrackerCapabilities | null,
  connection?: ConnectionAccess | null,
): string | null {
  if (capabilities && !capabilities.direct_read) {
    return `canopy doesn't read ${label} directly — its items arrive by MCP or file ingest.`;
  }
  if (connection && connection.read_strategy !== "direct") {
    return `${label} reads are ${ROUTED[connection.read_strategy] ?? connection.read_strategy} by integration policy.`;
  }
  if (connection && !connection.authorized && !connection.user_connected) {
    return `The ${label} connection isn't authorized yet — connect it on the Connectors page.`;
  }
  return null;
}

/** Plan groups in reading order: what changes owner first, what stays last. */
export const ACTION_ORDER: readonly string[] = ["adopt", "publish", "release", "remap", "keep"];

const ACTION_VERBS: Record<string, string> = {
  adopt: "adopted",
  keep: "kept",
  publish: "published",
  release: "released",
  remap: "remapped",
};

export interface PlanContext {
  /** The tracker the project leaves (null: it was native). */
  from: string | null;
  /** The tracker it moves to (null: native). */
  to: string | null;
  toMode: TrackingMode;
}

export interface PlanGroup {
  action: string;
  label: string;
  hint: string;
  items: TrackingSwitchAction[];
}

function actionText(action: string, ctx: PlanContext): { label: string; hint: string } {
  const to = ctx.to ?? "the tracker";
  const from = ctx.from ?? "the old tracker";
  switch (action) {
    case "adopt":
      return { label: `Adopted by ${to}`, hint: `Matched to a ${to} item — ${to} owns their status from now on.` };
    case "publish":
      return { label: `Published to ${to}`, hint: `Created as new ${to} items (content only), then owned by ${to}.` };
    case "release":
      return { label: "Released to canopy", hint: `They leave ${from}: canopy owns their status from now on, and their links stay as history.` };
    case "remap":
      return {
        label: "Released and remapped",
        hint: `They leave ${from}, and their status moves to the native column of the same category (the native columns lack it).`,
      };
    case "keep":
      return ctx.toMode === "mirrored"
        ? { label: "Stay canopy-owned", hint: `canopy keeps owning their status — canopy-only work in a project mirrored from ${to}.` }
        : { label: "Unchanged", hint: "Already canopy-owned." };
    default:
      return { label: action, hint: "" };
  }
}

/** A switch plan's actions grouped by what happens to each task, in reading order. */
export function groupPlan(
  actions: readonly TrackingSwitchAction[],
  ctx: PlanContext,
): PlanGroup[] {
  const byAction = new Map<string, TrackingSwitchAction[]>();
  for (const a of actions) {
    const list = byAction.get(a.action) ?? [];
    list.push(a);
    byAction.set(a.action, list);
  }
  const order = [
    ...ACTION_ORDER.filter((a) => byAction.has(a)),
    ...[...byAction.keys()].filter((a) => !ACTION_ORDER.includes(a)).sort(),
  ];
  return order.map((action) => ({ action, ...actionText(action, ctx), items: byAction.get(action) ?? [] }));
}

/** A plan row's detail in words: a released task names the tracker it leaves (the server
 *  sends its provider key). */
export function actionDetail(
  action: Pick<TrackingSwitchAction, "action" | "detail">,
  catalog?: TrackerCatalog | null,
): string {
  if (!action.detail) return "";
  return action.action === "release" ? `from ${providerLabel(action.detail, catalog)}` : action.detail;
}

/** "3 adopted · 10 kept" from a plan's counts. */
export function planSummary(counts: Record<string, number>): string {
  const order = [
    ...ACTION_ORDER.filter((a) => (counts[a] ?? 0) > 0),
    ...Object.keys(counts).filter((a) => !ACTION_ORDER.includes(a) && counts[a] > 0).sort(),
  ];
  if (order.length === 0) return "No tasks to move";
  return order.map((a) => `${counts[a]} ${ACTION_VERBS[a] ?? a}`).join(" · ");
}

/** The wizard's inputs for one switch. */
export interface SwitchDraft {
  /** "native", or the tracker connection to mirror from. */
  target: "native" | number | null;
  scopeFields: readonly SchemaField[];
  scopeValues: FormValues;
  mappingText: string;
  syncIterations: boolean;
  strategy: TrackingStrategy;
  /** The target tracker's (sprint mirroring only where it has iterations). */
  capabilities: TrackerCapabilities | null;
}

/** The switch request a draft makes (a preview — apply resends it with `dry_run: false`). */
export function switchRequest(draft: SwitchDraft): {
  request: TrackingSwitchRequest | null;
  errors: string[];
} {
  if (draft.target === null) return { request: null, errors: ["Pick where the project's statuses should live."] };
  if (draft.target === "native") {
    return {
      request: {
        to_mode: "native",
        connection_id: null,
        scope: {},
        mapping: {},
        sync_iterations: false,
        strategy: "keep_separate",
        dry_run: true,
      },
      errors: [],
    };
  }
  const scope = formPayload(draft.scopeFields, draft.scopeValues);
  const mapping = parseJsonObject(draft.mappingText, "Mapping");
  const errors = [...scope.errors, ...(mapping.error ? [mapping.error] : [])];
  if (errors.length > 0) return { request: null, errors };
  return {
    request: {
      to_mode: "mirrored",
      connection_id: draft.target,
      scope: scope.payload,
      mapping: mapping.value,
      sync_iterations: draft.syncIterations && Boolean(draft.capabilities?.iterations),
      strategy: draft.strategy,
      dry_run: true,
    },
    errors: [],
  };
}

// --------------------------------------------------------------------------- //
// Editing a binding in place
// --------------------------------------------------------------------------- //

export interface BindingDraft {
  scopeValues: FormValues;
  mappingText: string;
  syncIterations: boolean;
}

export function bindingDraft(binding: TrackerBinding, scopeFields: readonly SchemaField[]): BindingDraft {
  return {
    scopeValues: formValues(scopeFields, binding.scope),
    mappingText: jsonText(binding.mapping),
    syncIterations: binding.sync_iterations,
  };
}

/** The `PUT /tracking` body for an edited binding — only what changed. `scopeChanged` warns
 *  that the next sync re-reads everything (a new scope resets the watermark). */
export function bindingUpdate(
  binding: TrackerBinding,
  scopeFields: readonly SchemaField[],
  draft: BindingDraft,
  capabilities: TrackerCapabilities | null,
): { update: ProjectTrackingUpdate; errors: string[]; scopeChanged: boolean } {
  const scope = formPayload(scopeFields, draft.scopeValues);
  const mapping = parseJsonObject(draft.mappingText, "Mapping");
  const errors = [...scope.errors, ...(mapping.error ? [mapping.error] : [])];
  const update: ProjectTrackingUpdate = {};
  if (errors.length > 0) return { update, errors, scopeChanged: false };
  // Keys the form can't show (not in the schema's simple fields) ride along unchanged.
  const shown = new Set(scopeFields.map((f) => f.key));
  const kept = Object.fromEntries(Object.entries(binding.scope).filter(([k]) => !shown.has(k)));
  const nextScope = { ...kept, ...scope.payload };
  const scopeChanged = !sameJson(nextScope, binding.scope);
  if (scopeChanged) update.scope = nextScope;
  if (!sameJson(mapping.value, binding.mapping)) update.mapping = mapping.value;
  if (capabilities?.iterations && draft.syncIterations !== binding.sync_iterations) {
    update.sync_iterations = draft.syncIterations;
  }
  return { update, errors, scopeChanged };
}
