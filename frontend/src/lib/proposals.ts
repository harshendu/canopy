import type { ProposalItem } from "../api/types";

/** Pure presentation helpers for the change-proposal review queue. */

const ENTITY_LABELS: Record<string, string> = {
  task: "task",
  dependency: "dependency",
  milestone: "milestone",
  blocker: "blocker",
  risk: "risk",
  outcome: "outcome",
  decision: "decision",
  doc_reference: "doc link",
};

const LABEL_KEYS: Record<string, string> = {
  task: "name",
  milestone: "name",
  blocker: "reason",
  risk: "title",
  outcome: "statement",
  decision: "title",
  doc_reference: "url",
};

const VERBS: Record<string, string> = { create: "Add", update: "Update", resolve: "Resolve" };

/** Render one payload/snapshot value for the diff table. */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.map(formatValue).join(", ") : "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** The item's display label: the new name for creates, the live/staged name for updates. */
export function targetLabel(item: ProposalItem): string | null {
  if (item.entity_type === "dependency") {
    const p = item.payload;
    const pred = p.predecessor_ref ?? p.predecessor_id;
    const succ = p.successor_ref ?? p.successor_id;
    return `${formatValue(pred)} → ${formatValue(succ)}`;
  }
  const key = LABEL_KEYS[item.entity_type];
  if (!key) return null;
  const fromPayload = item.payload[key];
  if (typeof fromPayload === "string" && fromPayload) return fromPayload;
  const fromBefore = item.before?.[key];
  if (typeof fromBefore === "string" && fromBefore) return fromBefore;
  return item.entity_id != null ? `#${item.entity_id}` : null;
}

/** One-line headline for an item row, e.g. "Update task — Build ingest". */
export function itemHeadline(item: ProposalItem): string {
  const entity = ENTITY_LABELS[item.entity_type] ?? item.entity_type;
  const verb = VERBS[item.action] ?? item.action;
  const label = targetLabel(item);
  return label ? `${verb} ${entity} — ${label}` : `${verb} ${entity}`;
}

export interface DiffRow {
  field: string;
  /** stage-time value (null for creates — there is no before) */
  before: string | null;
  after: string;
  /** live value when it moved since staging (staleness), else null */
  current: string | null;
}

/** Field-by-field rows for the review diff. Creates list payload values; updates pair
 *  them with the before-snapshot; a `*_ref` value renders as a pointer to an earlier
 *  item's handle. */
export function diffRows(item: ProposalItem): DiffRow[] {
  const before = item.before;
  const current = item.current ?? null;
  return Object.entries(item.payload).map(([field, value]) => {
    const isRef = field.endsWith("_ref");
    const after = isRef ? `→ ${formatValue(value)}` : formatValue(value);
    const beforeVal =
      item.action !== "create" && before && field in before
        ? formatValue(before[field])
        : null;
    const liveVal =
      item.action !== "create" && current && field in current
        ? formatValue(current[field])
        : null;
    return {
      field,
      before: beforeVal,
      after,
      current: liveVal !== null && liveVal !== beforeVal ? liveVal : null,
    };
  });
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

/** Non-zero create/update/resolve tallies (in that fixed order) for the collapsed-card shape
 *  summary, so a reviewer reads the change's shape without expanding it. Pure. */
export function proposalShape(counts: Record<string, number> | undefined): ProposalShapeChip[] {
  const spec: ProposalShapeChip[] = [
    { action: "create", count: counts?.create ?? 0, glyph: "+" },
    { action: "update", count: counts?.update ?? 0, glyph: "~" },
    { action: "resolve", count: counts?.resolve ?? 0, glyph: "✓" },
  ];
  return spec.filter((c) => c.count > 0);
}
