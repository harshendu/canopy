import type { ADRStatus, DecisionQueueItem } from "../api/types";

export const ADR_STATUSES: ADRStatus[] = [
  "proposed",
  "under_discussion",
  "accepted",
  "rejected",
  "superseded",
  "deprecated",
  "deferred",
];

export const STATUS_LABELS: Record<ADRStatus, string> = {
  proposed: "Proposed",
  under_discussion: "Under discussion",
  accepted: "Accepted",
  rejected: "Rejected",
  superseded: "Superseded",
  deprecated: "Deprecated",
  deferred: "Deferred",
};

// Mirrors the backend lifecycle in app/services/decisions.py (valid_transition).
const TRANSITIONS: Record<ADRStatus, ADRStatus[]> = {
  proposed: ["under_discussion", "deferred", "accepted", "rejected"],
  under_discussion: ["accepted", "rejected", "deferred", "proposed"],
  deferred: ["under_discussion", "proposed", "accepted", "rejected"],
  accepted: ["superseded", "deprecated"],
  rejected: ["proposed", "under_discussion"],
  superseded: ["deprecated"],
  deprecated: [],
};

/** The statuses an ADR may move to, including its current status (a legal no-op). */
export function legalNextStatuses(current: ADRStatus): ADRStatus[] {
  return [current, ...TRANSITIONS[current]];
}

export interface BucketMeta {
  key: string;
  label: string;
  hint: string;
}

// Triage priority order — most-actionable first.
export const BUCKETS: BucketMeta[] = [
  { key: "needs_triage", label: "Needs triage", hint: "Proposed, awaiting the owner" },
  { key: "stuck", label: "Stuck", hint: "Under discussion too long" },
  { key: "deferred_soon", label: "Deferred — coming due", hint: "decide-by is near or past" },
  { key: "discussing", label: "In discussion", hint: "Open for comment" },
];

export interface QueueGroup {
  meta: BucketMeta;
  items: DecisionQueueItem[];
}

/** Group queue items by bucket, in triage-priority order, dropping empty buckets. */
export function groupQueue(items: DecisionQueueItem[]): QueueGroup[] {
  return BUCKETS.map((meta) => ({
    meta,
    items: items.filter((i) => i.bucket === meta.key),
  })).filter((g) => g.items.length > 0);
}
