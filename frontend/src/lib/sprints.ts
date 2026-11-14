/**
 * Delivery methods and sprints — the UI's pure logic (USER_FLOWS §C11), unit-tested in
 * `sprints.test.ts`: which surfaces a team's method turns on, the board's sprint selector,
 * the planning view's capacity bar and optimistic lists, the burndown and velocity chart
 * series, where unfinished work can go, and which team a project belongs to.
 */
import type {
  DeliveryMethod,
  EstimateUnit,
  Initiative,
  Project,
  Sprint,
  SprintCapacity,
  SprintReport,
  SprintState,
  Team,
  Velocity,
} from "../api/types";

// --------------------------------------------------------------------------- //
// Delivery method
// --------------------------------------------------------------------------- //

/** The methods that run sprints (sprint surfaces show only for these). */
export function usesSprints(method: DeliveryMethod | null | undefined): boolean {
  return method === "sprint" || method === "both";
}

export const METHOD_LABELS: Record<DeliveryMethod, string> = {
  kanban: "Kanban",
  sprint: "Sprints",
  both: "Sprints + Kanban",
};

export const DELIVERY_METHODS: { value: DeliveryMethod; label: string; hint: string }[] = [
  {
    value: "kanban",
    label: "Kanban",
    hint: "Continuous flow — WIP limits, cycle time and a weekly throughput forecast.",
  },
  {
    value: "sprint",
    label: "Sprints",
    hint: "Time boxes — plan each sprint against capacity, then follow its burndown and the team’s velocity.",
  },
  {
    value: "both",
    label: "Sprints on a Kanban board",
    hint: "Plan in sprints while work flows across the team’s WIP-limited columns.",
  },
];

export const ESTIMATE_UNITS: { value: EstimateUnit; label: string; hint: string }[] = [
  {
    value: "points",
    label: "Story points",
    hint: "Each task’s story points (a sprint where nothing is estimated counts tasks instead).",
  },
  {
    value: "days",
    label: "Days",
    hint: "Each task’s duration in working days, compared with the team’s person-days.",
  },
  { value: "count", label: "Task count", hint: "Every task counts 1 — no estimating needed." },
];

/** "13 pts", "4.5 d", "1 task". */
export function formatEstimate(value: number, unit: EstimateUnit | string): string {
  const n = Number.isInteger(value) ? String(value) : value.toFixed(1);
  if (unit === "points") return `${n} pt${value === 1 ? "" : "s"}`;
  if (unit === "days") return `${n} d`;
  return `${n} task${value === 1 ? "" : "s"}`;
}

/** 0.856 → "86%"; nothing to show → "—". */
export function percent(ratio: number | null | undefined): string {
  return ratio == null ? "—" : `${Math.round(ratio * 100)}%`;
}

// --------------------------------------------------------------------------- //
// Dates (calendar days, no time zones: `YYYY-MM-DD`)
// --------------------------------------------------------------------------- //

const DAY_MS = 86_400_000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function dayNumber(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Math.round(Date.UTC(y, m - 1, d) / DAY_MS);
}

function isoOf(day: number): string {
  return new Date(day * DAY_MS).toISOString().slice(0, 10);
}

/** Today in the viewer's time zone, as `YYYY-MM-DD` (deadlines and sprints are calendar days). */
export function localToday(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Whole days from `a` to `b` (negative when `b` is earlier). */
export function daysBetween(a: string, b: string): number {
  return dayNumber(b) - dayNumber(a);
}

/** "2026-11-03" → "Nov 3". */
export function formatDay(iso: string): string {
  const [, m, d] = iso.split("-").map(Number);
  return m >= 1 && m <= 12 && d ? `${MONTHS[m - 1]} ${d}` : iso;
}

export function formatSprintDates(sprint: Pick<Sprint, "start_date" | "end_date">): string {
  if (!sprint.start_date || !sprint.end_date) return "No dates yet";
  return `${formatDay(sprint.start_date)} – ${formatDay(sprint.end_date)}`;
}

/** How long an active sprint has left, from `today`, in words. */
export function timeLeftLabel(
  sprint: Pick<Sprint, "end_date" | "state">,
  today: string,
): string | null {
  if (sprint.state !== "active" || !sprint.end_date) return null;
  const left = daysBetween(today, sprint.end_date);
  if (left > 1) return `${left} days left`;
  if (left === 1) return "1 day left";
  if (left === 0) return "ends today";
  return `ended ${-left} day${left === -1 ? "" : "s"} ago`;
}

export const STATE_LABELS: Record<SprintState, string> = {
  planned: "Planned",
  active: "Active",
  completed: "Completed",
};

// --------------------------------------------------------------------------- //
// Sprint lists
// --------------------------------------------------------------------------- //

function byStart(a: Sprint, b: Sprint): number {
  return (a.start_date ?? "9999").localeCompare(b.start_date ?? "9999") || a.id - b.id;
}

/** Sprints work can still be planned into: the active one(s) first, then planned by start. */
export function liveSprints(sprints: readonly Sprint[]): Sprint[] {
  const active = sprints.filter((s) => s.state === "active").sort(byStart);
  const planned = sprints.filter((s) => s.state === "planned").sort(byStart);
  return [...active, ...planned];
}

/** Where a completing sprint's unfinished work can move: another canopy sprint of the team
 *  that isn't completed (the server refuses anything else), soonest first. */
export function carryOverTargets(sprints: readonly Sprint[], completing: Sprint): Sprint[] {
  return sprints
    .filter(
      (s) =>
        s.id !== completing.id &&
        s.team_id === completing.team_id &&
        s.state !== "completed" &&
        s.owner === "canopy",
    )
    .sort(byStart);
}

/** The sprint the planning view opens on: the active one, else the next planned, else the
 *  latest completed. */
export function defaultPlanningSprint(sprints: readonly Sprint[]): Sprint | null {
  const live = liveSprints(sprints);
  if (live.length > 0) return live[0];
  const done = sprints
    .filter((s) => s.state === "completed")
    .sort((a, b) => -byStart(a, b));
  return done[0] ?? null;
}

/** The sprint a report opens on: the active one, else the latest completed. */
export function defaultReportSprint(sprints: readonly Sprint[]): Sprint | null {
  const active = sprints.find((s) => s.state === "active");
  if (active) return active;
  return sprints.filter((s) => s.state === "completed").sort((a, b) => -byStart(a, b))[0] ?? null;
}

// --------------------------------------------------------------------------- //
// The board's sprint selector
// --------------------------------------------------------------------------- //

/** What a board shows: the active sprint, the backlog (open work in no live sprint), all
 *  work, or one sprint by id — the `?sprint=` filter of the board endpoints. */
export type SprintSelection = "active" | "backlog" | "all" | number;

/** The active sprint when the team has one, else all work. */
export function defaultSprintSelection(activeSprintId: number | null | undefined): SprintSelection {
  return activeSprintId != null ? "active" : "all";
}

/** The `?sprint=` value (and the selector's option value). */
export function sprintParam(selection: SprintSelection): string {
  return typeof selection === "number" ? String(selection) : selection;
}

export function parseSprintSelection(value: string): SprintSelection {
  if (value === "active" || value === "backlog" || value === "all") return value;
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : "all";
}

/** The one sprint a board selection shows (its name/dates/goal go in the toolbar), if any. */
export function shownSprint(
  selection: SprintSelection,
  sprints: readonly Sprint[],
  boardSprintId: number | null | undefined,
): Sprint | null {
  if (typeof selection === "number") return sprints.find((s) => s.id === selection) ?? null;
  if (selection === "active") {
    const id = boardSprintId ?? sprints.find((s) => s.state === "active")?.id;
    return sprints.find((s) => s.id === id) ?? null;
  }
  return null;
}

// --------------------------------------------------------------------------- //
// Planning: capacity bar + optimistic lists
// --------------------------------------------------------------------------- //

export interface CapacityView {
  committed: number;
  /** What the open estimate is compared with (null = nothing to compare yet). */
  limit: number | null;
  basis: "person-days" | "velocity" | null;
  /** Bar fill, 0–100 (capped; `over` says when the plan goes past the limit). */
  fillPct: number;
  /** The server's verdict: planned beyond capacity. Warns, never blocks. */
  over: boolean;
  summary: string;
}

/** The capacity bar: open estimate vs person-days (unit days) or mean velocity (points/count). */
export function capacityView(capacity: SprintCapacity): CapacityView {
  const { unit, committed } = capacity;
  let limit: number | null = null;
  let basis: CapacityView["basis"] = null;
  if (unit === "days") {
    if (capacity.person_days > 0) {
      limit = capacity.person_days;
      basis = "person-days";
    }
  } else if (capacity.velocity_mean != null && capacity.velocity_mean > 0) {
    limit = capacity.velocity_mean;
    basis = "velocity";
  }
  const fillPct = limit ? Math.min(100, Math.round((committed / limit) * 100)) : 0;
  const planned = `${formatEstimate(committed, unit)} planned`;
  const summary =
    limit == null
      ? `${planned} — no ${unit === "days" ? "allocated person-days" : "velocity history"} to compare with yet`
      : basis === "person-days"
        ? `${planned} of ${limit} person-days`
        : `${planned} against a mean velocity of ${formatEstimate(limit, unit)}`;
  return { committed, limit, basis, fillPct, over: capacity.over_capacity === true, summary };
}

export type PlanSide = "backlog" | "sprint";

/**
 * The planning view's two lists with the moves still in flight applied (`pending`: task id →
 * the side it is moving to), so a card moves at once and stays put until the server's lists
 * catch up. A card the server lists on both sides (mid-refetch) counts as in the sprint.
 */
export function planLists<T extends { id: number }>(
  backlog: readonly T[],
  sprint: readonly T[],
  pending: Readonly<Record<number, PlanSide>>,
): { backlog: T[]; sprint: T[] } {
  const inSprint = new Set(sprint.map((t) => t.id));
  const fromBacklog = backlog.filter((t) => !inSprint.has(t.id));
  const side = (t: T, natural: PlanSide): PlanSide => pending[t.id] ?? natural;
  return {
    backlog: [
      ...fromBacklog.filter((t) => side(t, "backlog") === "backlog"),
      ...sprint.filter((t) => side(t, "sprint") === "backlog"),
    ],
    sprint: [
      ...sprint.filter((t) => side(t, "sprint") === "sprint"),
      ...fromBacklog.filter((t) => side(t, "backlog") === "sprint"),
    ],
  };
}

// --------------------------------------------------------------------------- //
// Charts
// --------------------------------------------------------------------------- //

export interface BurndownRow {
  day: string;
  label: string;
  /** Null for days still ahead (the line stops at today). */
  remaining: number | null;
  ideal: number;
  scopeAdded: number | null;
}

/** One row per day of the sprint. The server reports days up to today; the ideal line runs on
 *  to the end with the same formula (the commitment down to zero over the sprint). */
export function burndownSeries(report: SprintReport): BurndownRow[] {
  const { start_date: start, end_date: end } = report.sprint;
  const rows = report.burndown.map((d) => ({
    day: d.day,
    label: formatDay(d.day),
    remaining: d.remaining,
    ideal: d.ideal,
    scopeAdded: d.scope_added,
  }));
  if (!start || !end || daysBetween(start, end) < 0) return rows;
  const byDay = new Map(rows.map((r) => [r.day, r]));
  const span = Math.max(daysBetween(start, end), 1);
  const out: BurndownRow[] = [];
  for (let offset = 0; offset <= daysBetween(start, end); offset += 1) {
    const day = isoOf(dayNumber(start) + offset);
    out.push(
      byDay.get(day) ?? {
        day,
        label: formatDay(day),
        remaining: null,
        ideal: Math.round(Math.max(report.committed * (1 - offset / span), 0) * 100) / 100,
        scopeAdded: null,
      },
    );
  }
  return out;
}

export interface VelocityRow {
  name: string;
  committed: number;
  completed: number;
  reliability: number | null;
}

/** Committed vs completed per completed sprint, oldest first. */
export function velocitySeries(velocity: Velocity): VelocityRow[] {
  return velocity.points.map((p) => ({
    name: p.name,
    committed: p.committed,
    completed: p.completed,
    reliability: p.reliability,
  }));
}

// --------------------------------------------------------------------------- //
// Teams
// --------------------------------------------------------------------------- //

/** A project's team, as the server resolves it: its pod's team, else its initiative's team
 *  (null = no team: the project is Kanban-only). */
export function projectTeamId(
  project: Pick<Project, "pod_id" | "initiative_id">,
  teams: readonly Pick<Team, "id" | "pods">[],
  initiatives: readonly Pick<Initiative, "id" | "team_id">[],
): number | null {
  if (project.pod_id != null) {
    const team = teams.find((t) => t.pods.some((p) => p.id === project.pod_id));
    if (team) return team.id;
  }
  if (project.initiative_id != null) {
    return initiatives.find((i) => i.id === project.initiative_id)?.team_id ?? null;
  }
  return null;
}

/** The live projects a team runs (the server's `team_project_ids`): through one of its pods,
 *  or — pod-less — through one of its initiatives. */
export function teamProjects<P extends Pick<Project, "id" | "pod_id" | "initiative_id" | "archived">>(
  teamId: number,
  projects: readonly P[],
  teams: readonly Pick<Team, "id" | "pods">[],
  initiatives: readonly Pick<Initiative, "id" | "team_id">[],
): P[] {
  const pods = new Set(teams.find((t) => t.id === teamId)?.pods.map((p) => p.id) ?? []);
  const owned = new Set(initiatives.filter((i) => i.team_id === teamId).map((i) => i.id));
  return projects.filter((p) => {
    if (p.archived) return false;
    if (p.pod_id != null) return pods.has(p.pod_id);
    return p.initiative_id != null && owned.has(p.initiative_id);
  });
}
