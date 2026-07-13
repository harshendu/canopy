import type { CapacityResponse } from "../api/types";

/**
 * Count over-allocated engineer-weeks (allocation > 100%, the same threshold the heatmap paints
 * red) for the management "Needs attention" band on /team — a cheap, honest summary that agrees
 * with what the heatmap directly below it shows, rather than a second, divergent computation.
 */
export function countOverAllocatedWeeks(data: CapacityResponse | undefined): number {
  if (!data) return 0;
  let count = 0;
  for (const row of data.rows) {
    for (const week of data.weeks) {
      if ((row.cells[week] ?? 0) > 100) count++;
    }
  }
  return count;
}
