import { lazy, Suspense, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Initiative, Project, ProjectAccess, Sprint, Team, TeamDelivery } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { QueryError } from "../components/QueryError";
import TaskDetailPanel from "../components/TaskDetailPanel";
import { Icon, type IconName } from "../components/icons";
import type { BoardProject } from "../components/board/KanbanBoard";
import DeliverySettings from "../components/sprints/DeliverySettings";
import { teamSeatsLabel } from "../lib/initiativeAccess";
import { canContribute, isPlanner } from "../lib/permissions";
import { METHOD_LABELS, teamProjects, usesSprints } from "../lib/sprints";
import { useCurrentUser } from "../lib/useCurrentUser";
import { featureOn, useFeatures } from "../lib/useFeatures";

// dnd-kit / Recharts — code-split like the project cockpit's views.
const KanbanBoard = lazy(() => import("../components/board/KanbanBoard"));
const SprintsPanel = lazy(() => import("../components/sprints/SprintsPanel"));
const SprintReportView = lazy(() => import("../components/sprints/SprintReportView"));

type TeamTab = "board" | "sprints" | "report" | "settings";

const TABS: { key: TeamTab; label: string; icon: IconName }[] = [
  { key: "board", label: "Board", icon: "board" },
  { key: "sprints", label: "Sprints", icon: "scenarios" },
  { key: "report", label: "Sprint report", icon: "burndown" },
  { key: "settings", label: "Settings", icon: "edit" },
];

const loading = (what: string) => <p className="text-sm text-slate-500">Loading {what}…</p>;

/** A team's page (USER_FLOWS §C11): one board over every project the team runs, and — when
 *  the team runs sprints — its sprints, sprint planning, the sprint report and velocity; plus
 *  how the team works (Kanban, sprints or both). */
export default function TeamView() {
  const { teamId } = useParams();
  const id = Number(teamId);
  const [params, setParams] = useSearchParams();
  const features = useFeatures();
  const { data: me } = useCurrentUser();

  const teams = useQuery({ queryKey: ["teams"], queryFn: () => api.get<Team[]>("/teams") });
  const delivery = useQuery({
    queryKey: ["team-delivery", id],
    queryFn: () => api.get<TeamDelivery>(`/teams/${id}/delivery`),
  });
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
  const initiatives = useQuery({
    queryKey: ["initiatives"],
    queryFn: () => api.get<Initiative[]>("/initiatives"),
  });
  const team = teams.data?.find((t) => t.id === id);
  const runs = useMemo<BoardProject[]>(
    () =>
      teams.data && projects.data && initiatives.data
        ? teamProjects(id, projects.data, teams.data, initiatives.data).map((p) => ({
            id: p.id,
            key: p.key,
            name: p.name,
            pod_id: p.pod_id ?? null,
          }))
        : [],
    [id, teams.data, projects.data, initiatives.data],
  );
  const projectKeys = useMemo(() => new Map(runs.map((p) => [p.id, p.key] as const)), [runs]);

  const sprinting = featureOn(features, "tracking.sprints") && usesSprints(delivery.data?.effective_method);
  const boardOn = featureOn(features, "tracking.board");
  const tabs = TABS.filter(
    (t) => (t.key === "board" && boardOn) || ((t.key === "sprints" || t.key === "report") && sprinting) || t.key === "settings",
  );
  const requested = params.get("tab");
  const tab: TeamTab = tabs.find((t) => t.key === requested)?.key ?? tabs[0].key;
  const reportSprint = params.get("sprint") ? Number(params.get("sprint")) : null;
  const goTo = (next: TeamTab, sprintId?: number) =>
    setParams(sprintId != null ? { tab: next, sprint: String(sprintId) } : { tab: next }, {
      replace: true,
    });

  const sprints = useQuery({
    queryKey: ["sprints", id],
    queryFn: () => api.get<Sprint[]>(`/teams/${id}/sprints`),
    enabled: sprinting && tab === "report",
  });

  // The task drawer, opened from a card: may the caller plan that card's project?
  const [selected, setSelected] = useState<{ taskId: number; projectId: number } | null>(null);
  const access = useQuery({
    queryKey: ["project-access", selected?.projectId],
    queryFn: () => api.get<ProjectAccess>(`/projects/${selected?.projectId}/access`),
    enabled: selected !== null,
  });

  if (teams.isError) {
    return <QueryError error={teams.error} onRetry={() => void teams.refetch()} label="Couldn’t load the team" />;
  }
  if (teams.data && !team) {
    return <p className="text-sm text-slate-500">This team doesn’t exist (any more).</p>;
  }

  const seats = team ? teamSeatsLabel(team.members) : "";
  const d = delivery.data;
  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Team", to: "/team" }, { label: team?.name ?? "Team" }]}
        title={team ? `${team.name}` : "Team"}
        subtitle={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            {d && (
              <span className="rounded bg-canopy-50 px-1.5 py-0.5 font-medium text-canopy-700">
                {METHOD_LABELS[d.effective_method]}
              </span>
            )}
            {d && d.delivery_method !== d.effective_method && (
              <span className="text-slate-400">
                ({METHOD_LABELS[d.delivery_method]} once sprints are turned on)
              </span>
            )}
            {team && team.pods.length > 0 && (
              <span>Pods: {team.pods.map((p) => p.name).join(", ")}</span>
            )}
            {seats && <span>· {seats}</span>}
            {runs.length > 0 && (
              <span>
                · {runs.length} project{runs.length === 1 ? "" : "s"}
              </span>
            )}
          </span>
        }
      />

      <div role="tablist" aria-label="Team views" className="flex gap-1 overflow-x-auto border-b border-slate-200">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => goTo(t.key)}
            className={`-mb-px flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-4 py-2 text-sm font-medium ${
              tab === t.key
                ? "border-canopy-500 text-canopy-700"
                : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            <Icon name={t.icon} size={15} />
            {t.label}
          </button>
        ))}
      </div>

      {tab === "board" && (
        <Suspense fallback={loading("the board")}>
          <KanbanBoard
            source={{ kind: "team", id }}
            onTaskClick={(taskId, projectId) => setSelected({ taskId, projectId })}
            projects={runs}
            pods={team?.pods}
            canEditColumns={d?.can_manage ?? false}
          />
        </Suspense>
      )}

      {tab === "sprints" && (
        <Suspense fallback={loading("sprints")}>
          <SprintsPanel
            teamId={id}
            pods={team?.pods ?? []}
            projectKeys={projectKeys}
            onReport={(sprintId) => goTo("report", sprintId)}
          />
        </Suspense>
      )}

      {tab === "report" &&
        (sprints.isError ? (
          <QueryError error={sprints.error} onRetry={() => void sprints.refetch()} label="Couldn’t load the sprints" />
        ) : !sprints.data ? (
          loading("sprints")
        ) : (
          <Suspense fallback={loading("the report")}>
            <SprintReportView
              teamId={id}
              sprints={sprints.data}
              sprintId={reportSprint}
              onSprintChange={(sprintId) => goTo("report", sprintId)}
            />
          </Suspense>
        ))}

      {tab === "settings" &&
        (delivery.isError ? (
          <QueryError error={delivery.error} onRetry={() => void delivery.refetch()} label="Couldn’t load the settings" />
        ) : d ? (
          <DeliverySettings key={`${d.delivery_method}-${d.sprint_length_days}-${d.estimate_unit}`} teamId={id} delivery={d} />
        ) : (
          loading("the settings")
        ))}

      {selected !== null && (
        <TaskDetailPanel
          taskId={selected.taskId}
          projectId={selected.projectId}
          mayPlan={isPlanner(me?.role) && (access.data?.can_edit ?? false)}
          mayContribute={canContribute(me?.role)}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
