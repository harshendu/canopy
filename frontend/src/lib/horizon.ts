export type Horizon = "now" | "next" | "later";

/** Bucket a target date into now (≤30d/overdue) / next (31–90d) / later (90+/undated). */
export function horizon(target: string | null, now: number = Date.now()): Horizon {
  if (!target) return "later";
  const days = Math.round((new Date(target).getTime() - now) / 86_400_000);
  if (days <= 30) return "now";
  if (days <= 90) return "next";
  return "later";
}
