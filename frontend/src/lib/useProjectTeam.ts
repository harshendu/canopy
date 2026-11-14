import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Initiative, Project, ProjectAccess, Team } from "../api/types";
import { projectTeamId } from "./sprints";

/**
 * The team that runs a project — its pod's team, else its initiative's (USER_FLOWS §C11.1) —
 * whose board, workflow and sprints it uses. The server says which (`ProjectAccess.team_id`);
 * against a server that doesn't, it is derived here from the project, teams and initiatives.
 * `teamId` is undefined while loading and null when the project has no team (it is then
 * Kanban-only). Shares the `project-access`, `project`, `teams` and `initiatives` caches with
 * the pages that already load them.
 */
export function useProjectTeam(projectId: number | null): {
  teamId: number | null | undefined;
  team: Team | null;
} {
  const access = useQuery({
    queryKey: ["project-access", projectId],
    queryFn: () => api.get<ProjectAccess>(`/projects/${projectId}/access`),
    enabled: projectId !== null,
  });
  const teams = useQuery({ queryKey: ["teams"], queryFn: () => api.get<Team[]>("/teams") });
  const serverTeam = access.data?.team_id;
  // Fall back to deriving it when the access read failed or predates `team_id`.
  const derive = projectId !== null && (access.isError || (access.data !== undefined && serverTeam === undefined));

  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.get<Project>(`/projects/${projectId}`),
    enabled: derive,
  });
  const p = project.data;
  const viaPod =
    p?.pod_id != null && (teams.data ?? []).some((t) => t.pods.some((pod) => pod.id === p.pod_id));
  const needsInitiative = derive && p != null && teams.data != null && !viaPod && p.initiative_id != null;
  const initiatives = useQuery({
    queryKey: ["initiatives"],
    queryFn: () => api.get<Initiative[]>("/initiatives"),
    enabled: needsInitiative,
  });

  let teamId: number | null | undefined;
  if (projectId === null) teamId = null;
  else if (!derive) teamId = access.data ? (serverTeam ?? null) : undefined;
  else if (project.isError || teams.isError) teamId = null;
  else if (!p || !teams.data) teamId = undefined;
  else if (!needsInitiative) teamId = projectTeamId(p, teams.data, []);
  else if (initiatives.isError) teamId = null;
  else if (!initiatives.data) teamId = undefined;
  else teamId = projectTeamId(p, teams.data, initiatives.data);

  return { teamId, team: (teams.data ?? []).find((t) => t.id === teamId) ?? null };
}
