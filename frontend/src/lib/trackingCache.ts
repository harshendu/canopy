import type { QueryClient } from "@tanstack/react-query";

import { trackingKey } from "../api/trackers";

/** Refresh everything a tracking change can touch: the project's tracking and the project
 *  itself (its mode), its tasks (owners, keys, statuses), Gantt, board (any sprint view) and the
 *  team boards that show it, its workflow (a tracker's columns), burndown, draft plans (a
 *  mirrored project finalises into its tracker) and the connections (a new binding). Resolves
 *  once the views on screen have refetched. */
export function invalidateTracking(qc: QueryClient, projectId: number): Promise<unknown> {
  return Promise.all(
    [
      trackingKey(projectId),
      ["project", projectId],
      ["projects"],
      ["tasks", projectId],
      ["task"],
      ["gantt", projectId],
      ["board", projectId],
      ["team-board"],
      ["workflow", "project", projectId],
      ["burndown", projectId],
      ["draft-plans", projectId],
      ["connections"],
    ].map((queryKey) => qc.invalidateQueries({ queryKey })),
  );
}
