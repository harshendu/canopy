import type {
  GanttResponse,
  PreviewCounts,
  PreviewIssue,
  PreviewTaskKind,
  ProjectPlanPreview,
  Proposal,
  ProposalEntityType,
  ProposalItem,
  ProposalLookups,
} from "../api/types";

/**
 * Pure presentation helpers for the change-proposal review workspace.
 *
 * The review reads in two passes — the plan as a whole (current ⇄ proposed), then the
 * fine-grained list of changes — and both are driven from here so the wording, the field
 * labels and the "what is editable" rules live in one unit-tested place rather than in JSX.
 */

// --------------------------------------------------------------------------- //
// Field catalog: how each staged field reads and how it is edited
// --------------------------------------------------------------------------- //

export type FieldKind =
  | "text"
  | "longtext"
  | "number"
  | "date"
  | "enum"
  | "engineer"
  | "task"
  | "project"
  | "spec"
  | "list";

export interface FieldMeta {
  label: string;
  kind: FieldKind;
  /** suffix for numbers ("d", "%") */
  unit?: string;
  /** allowed values for an enum */
  options?: readonly string[];
}

const GRADE = ["low", "medium", "high"] as const;

/** Field meta by name — shared across entities unless overridden below. */
const FIELDS: Record<string, FieldMeta> = {
  name: { label: "Name", kind: "text" },
  title: { label: "Title", kind: "text" },
  statement: { label: "Outcome", kind: "longtext" },
  description: { label: "Description", kind: "longtext" },
  reason: { label: "What's blocking", kind: "longtext" },
  duration: { label: "Duration", kind: "number", unit: "d" },
  lag: { label: "Lag", kind: "number", unit: "d" },
  percent_complete: { label: "Progress", kind: "number", unit: "%" },
  constraint_start: { label: "Start no earlier than", kind: "date" },
  start: { label: "Start", kind: "date" },
  deadline: { label: "Deadline", kind: "date" },
  target_date: { label: "Target date", kind: "date" },
  needed_by: { label: "Needed by", kind: "date" },
  target_resolution_date: { label: "Resolve by", kind: "date" },
  decide_by: { label: "Decide by", kind: "date" },
  assignee_engineer_id: { label: "Assignee", kind: "engineer" },
  owner_engineer_id: { label: "Owner", kind: "engineer" },
  raised_by_engineer_id: { label: "Raised by", kind: "engineer" },
  decision_owner_id: { label: "Decision owner", kind: "engineer" },
  proposed_by_id: { label: "Proposed by", kind: "engineer" },
  parent_id: { label: "Under", kind: "task" },
  predecessor_id: { label: "After", kind: "task" },
  successor_id: { label: "Before", kind: "task" },
  task_id: { label: "On task", kind: "task" },
  blocking_task_id: { label: "Waiting on", kind: "task" },
  project_id: { label: "Project", kind: "project" },
  spec_id: { label: "Spec", kind: "spec" },
  tags: { label: "Tags", kind: "list" },
  alternatives: { label: "Alternatives", kind: "list" },
  estimate_optimistic: { label: "Estimate (optimistic)", kind: "number", unit: "d" },
  estimate_likely: { label: "Estimate (likely)", kind: "number", unit: "d" },
  estimate_pessimistic: { label: "Estimate (pessimistic)", kind: "number", unit: "d" },
  probability: { label: "Probability", kind: "enum", options: GRADE },
  impact: { label: "Impact", kind: "enum", options: GRADE },
  severity: { label: "Severity", kind: "enum", options: ["low", "medium", "high", "critical"] },
  mitigation: { label: "Mitigation", kind: "longtext" },
  contingency: { label: "Contingency", kind: "longtext" },
  metric: { label: "Metric", kind: "text" },
  unit: { label: "Unit", kind: "text" },
  baseline_value: { label: "Baseline", kind: "number" },
  target_value: { label: "Target", kind: "number" },
  current_value: { label: "Current", kind: "number" },
  context: { label: "Context", kind: "longtext" },
  decision: { label: "Decision", kind: "longtext" },
  consequences: { label: "Consequences", kind: "longtext" },
  reversibility: { label: "Reversibility", kind: "enum", options: ["two_way", "one_way"] },
  rfc_url: { label: "RFC link", kind: "text" },
  url: { label: "Link", kind: "text" },
};

/** Fields whose meaning (or option list) depends on the entity. */
const ENTITY_FIELDS: Partial<Record<ProposalEntityType, Record<string, FieldMeta>>> = {
  task: {
    type: { label: "Kind", kind: "enum", options: ["task", "summary", "milestone"] },
  },
  dependency: {
    type: { label: "Link type", kind: "enum", options: ["FS", "SS", "FF", "SF"] },
  },
  milestone: {
    status: {
      label: "Status",
      kind: "enum",
      options: ["planned", "at_risk", "hit", "missed"],
    },
  },
  blocker: {
    category: {
      label: "Category",
      kind: "enum",
      options: ["dependency", "resource", "decision", "external", "technical"],
    },
  },
  risk: {
    status: {
      label: "Status",
      kind: "enum",
      options: ["open", "mitigating", "accepted", "resolved", "occurred"],
    },
    category: {
      label: "Category",
      kind: "enum",
      options: ["schedule", "scope", "technical", "resource", "external", "quality", "security"],
    },
  },
  outcome: {
    status: {
      label: "Status",
      kind: "enum",
      options: ["pending", "on_track", "at_risk", "validated", "invalidated"],
    },
  },
  doc_reference: {
    kind: {
      label: "Doc type",
      kind: "enum",
      options: ["prd", "design", "tech_design", "architecture", "release", "qa", "runbook", "other"],
    },
    title: { label: "Title", kind: "text" },
  },
};

/** Enum values that read badly when merely title-cased. */
const OPTION_LABELS: Record<string, string> = {
  FS: "Finish → start",
  SS: "Start → start",
  FF: "Finish → finish",
  SF: "Start → finish",
  summary: "Phase",
  one_way: "One-way door",
  two_way: "Two-way door",
  prd: "PRD",
  qa: "QA",
  tech_design: "Tech design",
};

/** "at_risk" → "At risk". */
export function humanize(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function optionLabel(value: string): string {
  return OPTION_LABELS[value] ?? humanize(value);
}

/** A `*_ref` key points at something created earlier in the same proposal; it reads (and
 *  is labelled) like the `*_id` field it stands in for. */
function baseField(field: string): string {
  return field.endsWith("_ref") ? `${field.slice(0, -4)}_id` : field;
}

export function fieldMeta(entity: ProposalEntityType, field: string): FieldMeta {
  const base = baseField(field);
  return (
    ENTITY_FIELDS[entity]?.[base] ??
    FIELDS[base] ?? { label: humanize(base.replace(/_id$/, "")), kind: "text" }
  );
}

// --------------------------------------------------------------------------- //
// Values
// --------------------------------------------------------------------------- //

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-03-16" → "Mar 16, 2026" (no Date object: a calendar day has no timezone). */
export function formatDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  return `${MONTHS[Number(match[2]) - 1]} ${Number(match[3])}, ${match[1]}`;
}

/** "2026-03-16" → "Mar 16" — for dense tables where the year is not in doubt. */
export function formatDayShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const match = /^\d{4}-(\d{2})-(\d{2})/.exec(iso);
  return match ? `${MONTHS[Number(match[1]) - 1]} ${Number(match[2])}` : iso;
}

/** Calendar days between two ISO days (after − before). */
export function dayDiff(before: string, after: string): number {
  const day = (iso: string) => {
    const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
    return Math.floor(Date.UTC(y, m - 1, d) / 86_400_000);
  };
  return day(after) - day(before);
}

/** Compact signed day count for chips: "+7d", "−3d", "±0". */
export function formatDelta(days: number | null | undefined): string {
  if (days == null) return "—";
  if (days === 0) return "±0";
  return days > 0 ? `+${days}d` : `−${Math.abs(days)}d`;
}

/** Generic rendering of a raw payload value (the fallback when no field meta applies). */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.map(formatValue).join(", ") : "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const LABEL_KEYS: Partial<Record<ProposalEntityType, string>> = {
  task: "name",
  milestone: "name",
  blocker: "reason",
  risk: "title",
  outcome: "statement",
  decision: "title",
  doc_reference: "url",
};

/** What the reader needs to turn ids and handles into names. */
export interface ItemContext {
  lookups: ProposalLookups;
  /** ref handle → the title of the staged item that declares it */
  refs: Map<string, string>;
}

/** The payload that will actually apply: the reviewer's overrides layered on the agent's. */
export function effectivePayload(item: ProposalItem): Record<string, unknown> {
  return { ...item.payload, ...(item.overrides ?? {}) };
}

/** The field an item is titled by. A doc link reads better by its title than its URL. */
function labelField(item: ProposalItem): string | undefined {
  if (item.entity_type === "doc_reference") {
    const title = effectivePayload(item).title;
    if (typeof title === "string" && title) return "title";
  }
  return LABEL_KEYS[item.entity_type];
}

function ownLabel(item: ProposalItem): string | null {
  const key = labelField(item);
  if (!key) return null;
  const staged = effectivePayload(item)[key];
  if (typeof staged === "string" && staged) return staged;
  const before = item.before?.[key];
  if (typeof before === "string" && before) return before;
  return null;
}

export function buildContext(detail: {
  items: ProposalItem[];
  lookups?: ProposalLookups;
}): ItemContext {
  const refs = new Map<string, string>();
  for (const item of detail.items) {
    if (item.ref) refs.set(item.ref, ownLabel(item) ?? item.ref);
  }
  return { lookups: detail.lookups ?? {}, refs };
}

const EMPTY_CONTEXT: ItemContext = { lookups: {}, refs: new Map() };

function lookupName(ctx: ItemContext, kind: keyof ProposalLookups, id: unknown): string {
  return ctx.lookups[kind]?.[String(id)] ?? `#${String(id)}`;
}

/** Render one staged value the way a person would say it: dates as days, ids as names,
 *  enums as words, a ref handle as the staged item it points at. */
export function displayValue(
  entity: ProposalEntityType,
  field: string,
  value: unknown,
  ctx: ItemContext = EMPTY_CONTEXT
): string {
  if (value === null || value === undefined || value === "") return "—";
  if (field.endsWith("_ref")) return `${ctx.refs.get(String(value)) ?? String(value)} (new)`;
  const meta = fieldMeta(entity, field);
  switch (meta.kind) {
    case "date":
      return formatDay(String(value));
    case "number":
      return `${String(value)}${meta.unit ?? ""}`;
    case "enum":
      return optionLabel(String(value));
    case "engineer":
    case "task":
    case "project":
    case "spec":
      return lookupName(ctx, meta.kind, value);
    default:
      return formatValue(value);
  }
}

// --------------------------------------------------------------------------- //
// One change, in plain words
// --------------------------------------------------------------------------- //

/** "New task", "Update risk", "Resolve blocker" — the change's kind, phrased as an action. */
export function itemKindLabel(item: ProposalItem): string {
  const create = item.action === "create";
  switch (item.entity_type) {
    case "task": {
      if (!create) return "Update task";
      const type = effectivePayload(item).type;
      if (type === "summary") return "New phase";
      return type === "milestone" ? "New milestone marker" : "New task";
    }
    case "dependency":
      return "Link tasks";
    case "milestone":
      return create ? "New milestone" : "Update milestone";
    case "blocker":
      return create ? "Raise blocker" : "Resolve blocker";
    case "risk":
      return create ? "New risk" : "Update risk";
    case "outcome":
      return create ? "New outcome" : "Update outcome";
    case "decision":
      return "Propose decision";
    case "doc_reference":
      return "Link doc";
  }
}

/** The thing a change is about: the new name for creates, the live name for updates, the
 *  two ends for a dependency. */
export function itemTitle(item: ProposalItem, ctx: ItemContext = EMPTY_CONTEXT): string {
  if (item.entity_type === "dependency") {
    const p = effectivePayload(item);
    const end = (refKey: string, idKey: string) =>
      p[refKey] != null
        ? (ctx.refs.get(String(p[refKey])) ?? String(p[refKey]))
        : p[idKey] != null
          ? lookupName(ctx, "task", p[idKey])
          : "?";
    return `${end("predecessor_ref", "predecessor_id")} → ${end("successor_ref", "successor_id")}`;
  }
  if (item.action !== "create") {
    // An update is titled by what the thing is called *now*; a rename shows as a fact.
    const key = labelField(item);
    const before = key ? item.before?.[key] : null;
    if (typeof before === "string" && before) return before;
  }
  return ownLabel(item) ?? (item.entity_id != null ? `#${item.entity_id}` : "Untitled");
}

/** Where a change lands when that isn't obvious from the proposal's own scope: the task a
 *  risk/doc hangs off, or the project inside an initiative-wide proposal. */
export function itemScopeNote(
  item: ProposalItem,
  ctx: ItemContext,
  proposalScope: Proposal["scope_level"]
): string | null {
  const p = effectivePayload(item);
  if (p.scope_level === "task" && p.scope_id != null) {
    return `on ${lookupName(ctx, "task", p.scope_id)}`;
  }
  if (proposalScope !== "initiative") return null;
  if (p.scope_level === "project" && p.scope_id != null) {
    return lookupName(ctx, "project", p.scope_id);
  }
  return p.project_id != null ? lookupName(ctx, "project", p.project_id) : null;
}

/** Scope plumbing the stager fills in — never shown as a "value" (see itemScopeNote). */
const HIDDEN_FIELDS = new Set(["project_id", "scope_level", "scope_id"]);
/** A dependency's two ends are its title, not facts. */
const DEPENDENCY_ENDS = new Set([
  "predecessor_id",
  "predecessor_ref",
  "successor_id",
  "successor_ref",
]);
const EDITABLE_KINDS = new Set<FieldKind>([
  "text",
  "longtext",
  "number",
  "date",
  "enum",
  "engineer",
]);

/** Reading order: what it is, how long, when, who — then everything else as staged. */
const FIELD_ORDER = [
  "name",
  "title",
  "statement",
  "reason",
  "type",
  "parent_id",
  "parent_ref",
  "task_id",
  "task_ref",
  "duration",
  "constraint_start",
  "start",
  "deadline",
  "target_date",
  "needed_by",
  "status",
  "severity",
  "category",
  "probability",
  "impact",
  "assignee_engineer_id",
  "owner_engineer_id",
];

export interface Fact {
  field: string;
  label: string;
  /** the value when this was staged (updates only; null when there is no "before") */
  before: string | null;
  /** the value that will apply: the reviewer's override if set, else the agent's proposal */
  after: string;
  /** the agent's original value, when the reviewer overrode it (shown struck through) */
  proposed: string | null;
  /** the live value, when it moved after staging (staleness); else null */
  current: string | null;
  /** the reviewer added this field — the agent's proposal didn't set it */
  added: boolean;
  /** can be edited inline (a plain value, not structure) */
  editable: boolean;
  /** it is the item's own title (hidden in the read view of a create — the card shows it) */
  isLabel: boolean;
  /** an update that sets the value the thing already has — worth seeing, not a change */
  unchanged: boolean;
  /** free text that may run long — rendered as a block, not a table cell */
  long: boolean;
}

/** The facts of one change, field by field, in reading order. Creates list what will be set;
 *  updates pair each value with what it replaces. */
export function itemFacts(item: ProposalItem, ctx: ItemContext = EMPTY_CONTEXT): Fact[] {
  const overrides = item.overrides ?? {};
  const fields = [...new Set([...Object.keys(item.payload), ...Object.keys(overrides)])].filter(
    (f) =>
      !HIDDEN_FIELDS.has(f) && !(item.entity_type === "dependency" && DEPENDENCY_ENDS.has(f))
  );
  const rank = (f: string) => {
    const index = FIELD_ORDER.indexOf(f);
    return index === -1 ? FIELD_ORDER.length : index;
  };
  fields.sort((a, b) => rank(a) - rank(b));

  const isUpdate = item.action !== "create";
  const label = labelField(item);
  const show = (field: string, value: unknown) =>
    displayValue(item.entity_type, field, value, ctx);

  return fields.map((field) => {
    const meta = fieldMeta(item.entity_type, field);
    const inPayload = field in item.payload;
    const overridden = field in overrides;
    const before =
      isUpdate && item.before && field in item.before ? show(field, item.before[field]) : null;
    const live =
      isUpdate && item.current && field in item.current
        ? show(field, item.current[field])
        : null;
    const after = show(field, overridden ? overrides[field] : item.payload[field]);
    return {
      field,
      label: meta.label,
      before,
      after,
      proposed: overridden && inPayload ? show(field, item.payload[field]) : null,
      current: live !== null && live !== before ? live : null,
      added: overridden && !inPayload,
      editable: !field.endsWith("_ref") && EDITABLE_KINDS.has(meta.kind),
      isLabel: field === label,
      unchanged: before !== null && before === after,
      long: meta.kind === "longtext",
    };
  });
}

/** The facts a card shows when read (not edited). On a create, what the card heading
 *  already says is left out: its own title, and a task's kind ("New phase"). */
export function visibleFacts(item: ProposalItem, facts: Fact[]): Fact[] {
  if (item.action !== "create") return facts;
  return facts.filter((f) => !f.isLabel && !(item.entity_type === "task" && f.field === "type"));
}

// --------------------------------------------------------------------------- //
// Editing
// --------------------------------------------------------------------------- //

/** Fields the reviewer may add to this change that the catalog knows how to edit. */
export function addableFields(item: ProposalItem): string[] {
  return (item.addable_fields ?? []).filter((field) =>
    EDITABLE_KINDS.has(fieldMeta(item.entity_type, field).kind)
  );
}

/** A staged value as the string a form control holds. */
export function inputValue(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

/** A form control's string back to the typed value the API validates. Empty → null
 *  ("no value"); numbers and people ids become numbers; everything else stays text. */
export function coerceInput(meta: FieldMeta, raw: string): unknown {
  const text = raw.trim();
  if (text === "") return null;
  if (meta.kind === "number" || meta.kind === "engineer") {
    const n = Number(text);
    return Number.isFinite(n) ? n : text; // let the server explain a non-number
  }
  return meta.kind === "longtext" || meta.kind === "text" ? raw : text;
}

/** The override map to send after an edit. A field put back to the agent's own value is
 *  dropped (that *is* a revert), and a field the agent never set is dropped when cleared —
 *  so the override records only what the reviewer genuinely changed. */
export function buildOverrides(
  item: ProposalItem,
  edits: Record<string, unknown>
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...(item.overrides ?? {}) };
  for (const [field, value] of Object.entries(edits)) {
    const inPayload = field in item.payload;
    const same = inPayload && (item.payload[field] ?? null) === (value ?? null);
    const emptyAddition = !inPayload && (value === null || value === undefined);
    if (same || emptyAddition) delete next[field];
    else next[field] = value;
  }
  return next;
}

// --------------------------------------------------------------------------- //
// The list of changes
// --------------------------------------------------------------------------- //

export interface ChangeGroup {
  key: string;
  label: string;
  entities: readonly ProposalEntityType[];
}

/** Changes are grouped by what part of the plan they touch, schedule first. */
export const CHANGE_GROUPS: readonly ChangeGroup[] = [
  { key: "schedule", label: "Schedule", entities: ["task", "dependency"] },
  { key: "milestones", label: "Milestones", entities: ["milestone"] },
  { key: "blockers", label: "Blockers", entities: ["blocker"] },
  { key: "risks", label: "Risks", entities: ["risk"] },
  { key: "outcomes", label: "Outcomes", entities: ["outcome"] },
  { key: "decisions", label: "Decisions", entities: ["decision"] },
  { key: "docs", label: "Docs", entities: ["doc_reference"] },
];

export function groupItems(
  items: ProposalItem[]
): { group: ChangeGroup; items: ProposalItem[] }[] {
  return CHANGE_GROUPS.map((group) => ({
    group,
    items: items.filter((i) => group.entities.includes(i.entity_type)),
  })).filter((g) => g.items.length > 0);
}

/** The ref handles an item points at (its `parent_ref`, `predecessor_ref`, …). */
function refsUsed(item: ProposalItem): string[] {
  return Object.entries(item.payload)
    .filter(([key, value]) => key.endsWith("_ref") && typeof value === "string")
    .map(([, value]) => value as string);
}

/** `ids` plus every change that can't apply without them — whatever (transitively) points
 *  at something they create. Excluding a new phase takes the tasks under it along, rather
 *  than leaving each one flagged as broken. Returned in the items' own order. */
export function withDependents(items: ProposalItem[], ids: number[]): number[] {
  const out = new Set(ids);
  for (let grew = true; grew; ) {
    grew = false;
    const declared = new Set(items.filter((i) => out.has(i.id) && i.ref).map((i) => i.ref));
    for (const item of items) {
      if (!out.has(item.id) && refsUsed(item).some((handle) => declared.has(handle))) {
        out.add(item.id);
        grew = true;
      }
    }
  }
  return items.filter((i) => out.has(i.id)).map((i) => i.id);
}

/** `ids` plus every change they need in order to apply — the (transitive) creators of the
 *  refs they point at. Re-including a task brings back the phase it hangs under. */
export function withPrerequisites(items: ProposalItem[], ids: number[]): number[] {
  const byRef = new Map(items.filter((i) => i.ref).map((i) => [i.ref as string, i]));
  const out = new Set(ids);
  const queue = items.filter((i) => out.has(i.id));
  for (let item = queue.shift(); item; item = queue.shift()) {
    for (const handle of refsUsed(item)) {
      const needed = byRef.get(handle);
      if (needed && !out.has(needed.id)) {
        out.add(needed.id);
        queue.push(needed);
      }
    }
  }
  return items.filter((i) => out.has(i.id)).map((i) => i.id);
}

export interface Attention {
  tone: "error" | "warn";
  message: string;
}

/** Why a change needs a look before applying: it would fail (error) or the plan moved
 *  under it since it was staged (warn). An excluded change needs nothing — it's out. */
export function itemAttention(
  item: ProposalItem,
  issues: PreviewIssue[] | undefined,
  ctx: ItemContext = EMPTY_CONTEXT
): Attention | null {
  if (item.excluded) return null;
  const issue = issues?.find((i) => i.item_id === item.id)?.error ?? item.error;
  if (issue) {
    const missingRef = /_ref '([^']+)' does not match/.exec(issue);
    if (missingRef) {
      const name = ctx.refs.get(missingRef[1]) ?? missingRef[1];
      return {
        tone: "error",
        message: `Needs “${name}”, which is excluded or missing — include that change or exclude this one.`,
      };
    }
    return { tone: "error", message: issue.charAt(0).toUpperCase() + issue.slice(1) };
  }
  if (item.stale) {
    return {
      tone: "warn",
      message:
        item.current == null
          ? "The thing this changes no longer exists in canopy."
          : "Changed in canopy since this was staged — check the values.",
    };
  }
  return null;
}

/** Counts for a proposal header chip: included vs total. */
export function includedCount(items: ProposalItem[]): number {
  return items.filter((i) => !i.excluded).length;
}

export interface ProposalShapeChip {
  action: "create" | "update" | "resolve";
  count: number;
  /** compact prefix used in the chip: + / ~ / ✓ */
  glyph: string;
}

/** Non-zero create/update/resolve tallies (in that fixed order) for the queue card's shape
 *  summary, so a reviewer reads the change's shape without opening it. Pure. */
export function proposalShape(counts: Record<string, number> | undefined): ProposalShapeChip[] {
  const spec: ProposalShapeChip[] = [
    { action: "create", count: counts?.create ?? 0, glyph: "+" },
    { action: "update", count: counts?.update ?? 0, glyph: "~" },
    { action: "resolve", count: counts?.resolve ?? 0, glyph: "✓" },
  ];
  return spec.filter((c) => c.count > 0);
}

// --------------------------------------------------------------------------- //
// The plan as a whole: current ⇄ proposed
// --------------------------------------------------------------------------- //

export type PlanMode = "current" | "proposed";

/** One time window covering both states, so the chart doesn't rescale (and bars don't
 *  appear to move for the wrong reason) when the reviewer flips the toggle. */
export function planDomain(plan: ProjectPlanPreview): { min: string; max: string } | null {
  const days = [plan.current, plan.proposed]
    .flatMap((g) => g?.tasks ?? [])
    .flatMap((t) => [t.start_date, t.end_date, t.deadline])
    .filter((d): d is string => Boolean(d))
    .sort();
  return days.length ? { min: days[0], max: days[days.length - 1] } : null;
}

/** The chart data for one side of the toggle. The proposed side carries each moved task's
 *  *current* dates in the chart's ghost-bar slot, so the "+5d" overlay reads current →
 *  proposed. (While the staged graph has a cycle there is no proposed side to draw.) */
export function ganttForMode(plan: ProjectPlanPreview, mode: PlanMode): GanttResponse {
  if (mode === "current" || !plan.proposed) return plan.current;
  const now = new Map(plan.current.tasks.map((t) => [t.id, t]));
  return {
    ...plan.proposed,
    tasks: plan.proposed.tasks.map((t) => {
      const was = now.get(t.id);
      const moved =
        was !== undefined && (was.start_date !== t.start_date || was.end_date !== t.end_date);
      return {
        ...t,
        baseline_start: moved ? was.start_date : null,
        baseline_end: moved ? was.end_date : null,
      };
    }),
  };
}

/** Which rows to tint. A task the proposal adds doesn't exist on the current side. */
export function planHighlights(
  plan: ProjectPlanPreview,
  mode: PlanMode
): Map<number, PreviewTaskKind> {
  const out = new Map<number, PreviewTaskKind>();
  for (const change of plan.task_changes) {
    if (mode === "current" && change.kind === "added") continue;
    out.set(change.task_id, change.kind);
  }
  return out;
}

export interface ImpactChip {
  key: string;
  label: string;
  tone: "add" | "edit" | "shift" | "neutral";
}

function count(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The proposal's shape as a row of plain-language chips ("3 new tasks", "4 tasks move"). */
export function impactChips(counts: PreviewCounts): ImpactChip[] {
  const chips: (ImpactChip | false)[] = [
    counts.tasks_added > 0 && {
      key: "tasks_added",
      label: count(counts.tasks_added, "new task"),
      tone: "add",
    },
    counts.tasks_edited > 0 && {
      key: "tasks_edited",
      label: `${count(counts.tasks_edited, "task")} edited`,
      tone: "edit",
    },
    counts.tasks_shifted > 0 && {
      key: "tasks_shifted",
      label: `${count(counts.tasks_shifted, "task")} ${counts.tasks_shifted === 1 ? "moves" : "move"} as a result`,
      tone: "shift",
    },
    counts.dependencies_added > 0 && {
      key: "dependencies_added",
      label: count(counts.dependencies_added, "new dependency", "new dependencies"),
      tone: "add",
    },
    counts.milestones_added > 0 && {
      key: "milestones_added",
      label: count(counts.milestones_added, "new milestone"),
      tone: "add",
    },
    counts.milestones_edited > 0 && {
      key: "milestones_edited",
      label: `${count(counts.milestones_edited, "milestone")} changed`,
      tone: "edit",
    },
    counts.blockers_raised > 0 && {
      key: "blockers_raised",
      label: `${count(counts.blockers_raised, "blocker")} raised`,
      tone: "add",
    },
    counts.blockers_resolved > 0 && {
      key: "blockers_resolved",
      label: `${count(counts.blockers_resolved, "blocker")} resolved`,
      tone: "edit",
    },
    counts.risks_added > 0 && {
      key: "risks_added",
      label: count(counts.risks_added, "new risk"),
      tone: "add",
    },
    counts.risks_edited > 0 && {
      key: "risks_edited",
      label: `${count(counts.risks_edited, "risk")} updated`,
      tone: "edit",
    },
    counts.outcomes_added > 0 && {
      key: "outcomes_added",
      label: count(counts.outcomes_added, "new outcome"),
      tone: "add",
    },
    counts.outcomes_edited > 0 && {
      key: "outcomes_edited",
      label: `${count(counts.outcomes_edited, "outcome")} updated`,
      tone: "edit",
    },
    counts.decisions_added > 0 && {
      key: "decisions_added",
      label: count(counts.decisions_added, "proposed decision"),
      tone: "add",
    },
    counts.docs_added > 0 && {
      key: "docs_added",
      label: count(counts.docs_added, "doc link"),
      tone: "add",
    },
  ];
  return chips.filter((c): c is ImpactChip => c !== false);
}

/** True when nothing in the proposal moves a schedule (it only touches registers). */
export function scheduleUntouched(counts: PreviewCounts): boolean {
  return (
    counts.tasks_added +
      counts.tasks_edited +
      counts.tasks_shifted +
      counts.dependencies_added ===
    0
  );
}

// --------------------------------------------------------------------------- //
// Reviewing together with Claude
// --------------------------------------------------------------------------- //

/** A starter line to paste into a Claude session that has the canopy plugin, so the
 *  reviewer can refine the open proposal in conversation while this page updates live. */
export function reviewPrompt(proposal: Pick<Proposal, "id" | "title">, url: string): string {
  return (
    `Let's review canopy proposal #${proposal.id} (“${proposal.title}”) together — ` +
    `I have it open at ${url}. Start by telling me what it does to the plan, then I'll ` +
    `tell you what to change.`
  );
}

/** Timestamps from the API are naive UTC ("2026-11-14T04:15:36"); mark them as such so the
 *  browser doesn't read them as local time. */
export function parseUtc(iso: string): Date {
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`);
}

/** "just now", "5 min ago", "3 h ago", then a calendar date. */
export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const then = parseUtc(iso);
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return formatDay(then.toISOString());
}
