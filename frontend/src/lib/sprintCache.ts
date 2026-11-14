import type { QueryClient } from "@tanstack/react-query";

/** Refresh everything a sprint change can touch: the team's sprints and their details and
 *  reports, its delivery (the active sprint), velocity, every board (sprint filters), the
 *  tasks' sprint field and "My sprint". Resolves once the views on screen have refetched. */
export function invalidateSprintData(qc: QueryClient, teamId: number): Promise<unknown> {
  return Promise.all(
    [
      ["sprints", teamId],
      ["sprint"],
      ["sprint-report"],
      ["team-delivery", teamId],
      ["velocity", teamId],
      ["team-board", teamId],
      ["board"],
      ["task"],
      ["my-workspace"],
    ].map((queryKey) => qc.invalidateQueries({ queryKey })),
  );
}
