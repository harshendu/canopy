import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Initiative, Project, Team } from "../api/types";
import { projectTeamId } from "./sprints";

/**
 * The team a project belongs to, as the server resolves it — its pod's team, else its
 * initiative's team (USER_FLOWS §C11.1). `teamId` is undefined while the lookups load and null
 * when the project has no team (it is then Kanban-only). Shares the `project`, `teams` and
 * `initiatives` caches with the pages that already load them.
 */
export function useProjectTeam(projectId: number | null): {
  teamId: number | null | undefined;
  team: Team | null;
} {
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.get<Project>(`/projects/${projectId}`),
    enabled: projectId !== null,
  });
  const teams = useQuery({ queryKey: ["teams"], queryFn: () => api.get<Team[]>("/teams") });
  const p = project.data;
  const viaPod = p?.pod_id != null && (teams.data ?? []).some((t) => t.pods.some((pod) => pod.id === p.pod_id));
  const needsInitiative = p != null && teams.data != null && !viaPod && p.initiative_id != null;
  const initiatives = useQuery({
    queryKey: ["initiatives"],
    queryFn: () => api.get<Initiative[]>("/initiatives"),
    enabled: needsInitiative,
  });

  let teamId: number | null | undefined;
  if (projectId === null || project.isError || teams.isError) teamId = null;
  else if (!p || !teams.data) teamId = undefined;
  else if (!needsInitiative) teamId = projectTeamId(p, teams.data, []);
  else if (initiatives.isError) teamId = null;
  else if (!initiatives.data) teamId = undefined;
  else teamId = projectTeamId(p, teams.data, initiatives.data);

  return { teamId, team: (teams.data ?? []).find((t) => t.id === teamId) ?? null };
}
