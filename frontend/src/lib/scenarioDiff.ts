import type { ScenarioDiff } from "../api/types";

/** Human phrasing of a day delta (positive = later/slower, negative = earlier/faster). */
export function formatDayDelta(days: number | null): string {
  if (days === null) return "—";
  if (days === 0) return "no change";
  const n = Math.abs(days);
  return days > 0 ? `${n} day${n === 1 ? "" : "s"} later` : `${n} day${n === 1 ? "" : "s"} earlier`;
}

/** Total number of edited entities a scenario carries (for an at-a-glance badge). */
export function totalChanges(diff: ScenarioDiff): number {
  return (
    diff.tasks_added +
    diff.tasks_removed +
    diff.tasks_changed +
    diff.deps_added +
    diff.deps_removed +
    diff.milestones_changed +
    diff.allocations_changed +
    diff.availability_changed
  );
}

/** Tailwind tone for a delta: green when it pulls the date in, red when it pushes out. */
export function deltaTone(days: number | null): string {
  if (days === null || days === 0) return "text-slate-500";
  return days > 0 ? "text-red-600" : "text-canopy-700";
}
