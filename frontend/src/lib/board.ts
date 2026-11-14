/**
 * The Kanban board's pure logic (USER_FLOWS §C9), kept free of React and dnd-kit so it is
 * unit-testable (`board.test.ts`): normalising the board response, who may move which card
 * (mirrors `POST /tasks/{id}/move`), the optimistic move the UI shows before the server
 * answers, filters, swimlanes, WIP, the neighbour ids a drop sends, and reading a refusal.
 */
import type {
  BoardLane,
  BoardResponse,
  BoardTaskItem,
  BoardViewer,
  StatusCategory,
  TaskExternalLinks,
  TaskMoveRequest,
  TrackerItemLink,
} from "../api/types";

/** The column the server puts cards without a status in (always first). */
export const NO_STATUS = "(no status)";
/** `status_owner` of a card whose status canopy owns (else a tracker's provider key). */
export const CANOPY_OWNER = "canopy";

/** Status names match case-insensitively, as on the server. */
export function fold(name: string): string {
  return name.trim().toLowerCase();
}

// --------------------------------------------------------------------------- //
// Data source
// --------------------------------------------------------------------------- //

/** Where a board's cards come from: one project, or every project a team runs (on the
 *  team's columns — §C11.2). */
export type BoardSource = { kind: "project"; id: number } | { kind: "team"; id: number };

/** The board's cache key. A sprint filter extends it, so `boardQueryKey(source)` is the
 *  prefix every variant of the board shares (the task drawer invalidates by it). */
export function boardQueryKey(
  source: BoardSource,
  sprint?: string | null,
): readonly (string | number)[] {
  const base = source.kind === "project" ? ["board", source.id] : ["team-board", source.id];
  return sprint ? [...base, sprint] : base;
}

export function boardPath(source: BoardSource, sprint?: string | null): string {
  const path =
    source.kind === "project" ? `/projects/${source.id}/board` : `/teams/${source.id}/board`;
  return sprint ? `${path}?sprint=${encodeURIComponent(sprint)}` : path;
}

export function workflowQueryKey(source: BoardSource): readonly (string | number)[] {
  return ["workflow", source.kind, source.id];
}

export function workflowPath(source: BoardSource): string {
  return source.kind === "project"
    ? `/projects/${source.id}/workflow`
    : `/teams/${source.id}/workflow`;
}

// --------------------------------------------------------------------------- //
// The normalised board
// --------------------------------------------------------------------------- //

/** A card with every field the API may omit filled in (see `normalizeBoard`). */
export type Card = Required<BoardTaskItem>;
export interface Lane extends Omit<Required<BoardLane>, "tasks"> {
  tasks: Card[];
}
export interface Board extends Omit<Required<BoardResponse>, "lanes"> {
  lanes: Lane[];
}

/** Fill the optional board fields with the server's defaults, so the board code reads one
 *  shape whether or not a projection (the scenario board) omitted card detail. */
export function normalizeBoard(raw: BoardResponse): Board {
  return {
    project_id: raw.project_id,
    cycle_time_p85_days: raw.cycle_time_p85_days,
    aging_count: raw.aging_count,
    mode: raw.mode ?? "native",
    wip_enforcement: raw.wip_enforcement ?? "warn",
    viewer: raw.viewer ?? null,
    team_id: raw.team_id ?? null,
    sprint_id: raw.sprint_id ?? null,
    delivery_method: raw.delivery_method ?? "kanban",
    lanes: raw.lanes.map((lane, index) => {
      const wip_limit = lane.wip_limit ?? null;
      const scope_wip = lane.scope_wip ?? null;
      return {
        status: lane.status,
        is_done: lane.is_done,
        wip: lane.wip,
        tasks: lane.tasks.map((t) => normalizeCard(t, raw.project_id)),
        category: lane.category ?? null,
        position: lane.position ?? index,
        wip_limit,
        scope_wip,
        over_limit: lane.over_limit ?? overLimit({ wip: lane.wip, scope_wip, wip_limit }),
        in_workflow: lane.in_workflow ?? true,
      };
    }),
  };
}

function normalizeCard(t: BoardTaskItem, projectId: number): Card {
  const status_owner = t.status_owner ?? CANOPY_OWNER;
  return {
    id: t.id,
    name: t.name,
    status: t.status,
    assignee_engineer_id: t.assignee_engineer_id,
    is_done: t.is_done,
    age_days: t.age_days,
    aging: t.aging,
    project_id: t.project_id ?? projectId,
    key: t.key ?? null,
    status_category: t.status_category ?? null,
    status_owner,
    movable: t.movable ?? status_owner === CANOPY_OWNER,
    external_url: t.external_url ?? null,
    rank: t.rank ?? 0,
    parent_id: t.parent_id ?? null,
    blocked: t.blocked ?? false,
    is_critical: t.is_critical ?? false,
    deadline: t.deadline ?? null,
    tags: t.tags ?? [],
    sprint_id: t.sprint_id ?? null,
    story_points: t.story_points ?? null,
    duration: t.duration ?? null,
  };
}

export function findCard(board: Board, taskId: number): { card: Card; lane: Lane } | null {
  for (const lane of board.lanes) {
    const card = lane.tasks.find((t) => t.id === taskId);
    if (card) return { card, lane };
  }
  return null;
}

/** How a card reads to people and screen readers: "CHK-12 Build the retry worker". */
export function cardLabel(card: Pick<Card, "key" | "name">): string {
  return card.key ? `${card.key} ${card.name}` : card.name;
}

// --------------------------------------------------------------------------- //
// Categories, WIP and trackers
// --------------------------------------------------------------------------- //

export const CATEGORY_LABELS: Record<StatusCategory, string> = {
  todo: "To do",
  in_progress: "In progress",
  done: "Done",
  cancelled: "Cancelled",
};

const CLOSED: ReadonlySet<StatusCategory> = new Set<StatusCategory>(["done", "cancelled"]);

/** Done and cancelled work is closed: it leaves WIP. */
export function isClosedCategory(category: StatusCategory | null | undefined): boolean {
  return category != null && CLOSED.has(category);
}

/** Counts as work in progress in its column (the server's `flow._is_open`). */
export function isOpenCard(card: Pick<Card, "status_category" | "is_done">): boolean {
  return card.status_category != null ? !CLOSED.has(card.status_category) : !card.is_done;
}

/** The open cards a column's WIP limit is judged on: across the WIP scope (every project
 *  sharing the columns) when the server says, else those on this board. */
export function limitWip(lane: Pick<Lane, "wip"> & { scope_wip?: number | null }): number {
  return lane.scope_wip ?? lane.wip;
}

/** A column holds more open cards than its WIP limit (the server's `over_limit`). */
export function overLimit(
  lane: Pick<Lane, "wip" | "wip_limit"> & { scope_wip?: number | null },
): boolean {
  return lane.wip_limit != null && limitWip(lane) > lane.wip_limit;
}

/** The column header's count: cards in a closed column, else WIP against the limit (counted
 *  across the WIP scope), else the open cards on this board. */
export function laneCount(
  lane: Pick<Lane, "wip" | "wip_limit" | "scope_wip" | "category" | "is_done" | "tasks">,
): string {
  if (isClosedCategory(lane.category) || (lane.category == null && lane.is_done)) {
    return String(lane.tasks.length);
  }
  return lane.wip_limit != null ? `${limitWip(lane)}/${lane.wip_limit}` : String(lane.wip);
}

/** The column's WIP counts more open cards than this board shows (others are in projects,
 *  sprints or pods sharing the columns but not on screen). */
export function wipBeyondBoard(lane: Pick<Lane, "wip" | "scope_wip">): boolean {
  return lane.scope_wip != null && lane.scope_wip !== lane.wip;
}

const TRACKER_NAMES: Record<string, string> = { jira: "Jira", github: "GitHub" };

/** Display name of the tracker that owns a mirrored card's status ("jira" → "Jira"). */
export function trackerName(statusOwner: string): string {
  return TRACKER_NAMES[statusOwner] ?? statusOwner.charAt(0).toUpperCase() + statusOwner.slice(1);
}

/** The tracker item behind a task: the neutral `tracker` link, else the deprecated `jira`. */
export function trackerItemOf(
  links: Pick<TaskExternalLinks, "tracker" | "jira">,
): TrackerItemLink | null {
  if (links.tracker) return links.tracker;
  if (links.jira) return { provider: "jira", label: "Jira", key: links.jira.key, url: links.jira.url };
  return null;
}

// --------------------------------------------------------------------------- //
// Who may move what
// --------------------------------------------------------------------------- //

export interface MoveIntent {
  /** Into another column (a status change) — vs. reordering within the card's column. */
  changesStatus: boolean;
}

/**
 * May this viewer make this move? Mirrors `POST /tasks/{id}/move`: a planner moves any card;
 * an engineer moves their own cards and pulls an unassigned one into a column (the server then
 * assigns it to them — merely reordering someone else's backlog is planning); only a
 * canopy-owned card changes status (a mirrored one may still be reordered). While canopy-owned
 * status is off (`native_enabled`), the board is read-only.
 */
export function canMove(
  card: Pick<Card, "movable" | "assignee_engineer_id">,
  viewer: BoardViewer | null | undefined,
  { changesStatus }: MoveIntent,
): boolean {
  if (!viewer || !viewer.native_enabled) return false;
  if (changesStatus && !card.movable) return false;
  if (viewer.can_plan) return true;
  if (viewer.engineer_id == null) return false;
  if (card.assignee_engineer_id === viewer.engineer_id) return true;
  return changesStatus && card.assignee_engineer_id == null;
}

/** Whether any move of this card is open to the viewer (shows its drag handle). */
export function canDrag(
  card: Pick<Card, "movable" | "assignee_engineer_id">,
  viewer: BoardViewer | null | undefined,
): boolean {
  return (
    canMove(card, viewer, { changesStatus: false }) ||
    canMove(card, viewer, { changesStatus: true })
  );
}

export interface ViewerRole {
  /** A planning role (admin/architect/engineering manager). */
  planner: boolean;
  /** Any role that may write (everyone but `viewer`). */
  contributor: boolean;
}

/**
 * Belt and braces over the server's `viewer`: a read-only `viewer` role moves nothing (the
 * server already sends no engineer for one). A planner who may not plan here keeps the
 * engineer rules — their own cards, or pulling an unassigned one. An unknown role (still
 * loading) leaves the viewer as the server sent it.
 */
export function viewerForRole(
  viewer: BoardViewer | null | undefined,
  role: ViewerRole | null,
): BoardViewer | null {
  if (!viewer) return null;
  if (role && !role.contributor) return { ...viewer, can_plan: false, engineer_id: null };
  return viewer;
}

/** The columns a card can be moved into: the workflow's columns other than its own (a
 *  status the workflow doesn't name can't be a target). */
export function moveTargets(lanes: readonly Lane[], card: Pick<Card, "status">): string[] {
  return lanes
    .filter((lane) => lane.in_workflow && fold(lane.status) !== fold(card.status))
    .map((lane) => lane.status);
}

/** A card's own status when the board shows it in a column of another name — the team board
 *  puts a status its columns don't name (a mirrored status, a project override) in the first
 *  column of the same category (§C11.2). Null when the column is the card's status. */
export function foldedStatus(card: Pick<Card, "status">, lane: Pick<Lane, "status">): string | null {
  if (card.status === NO_STATUS || lane.status === NO_STATUS) return null;
  return fold(card.status) === fold(lane.status) ? null : card.status;
}

/** What `expected_status` should say for a card: its status, or "" for a card shown in the
 *  "(no status)" column (the server compares against `status or ""`). */
export function expectedStatusOf(card: Pick<Card, "status">): string {
  return card.status === NO_STATUS ? "" : card.status;
}

// --------------------------------------------------------------------------- //
// Moves
// --------------------------------------------------------------------------- //

/** A move as the UI makes it: the request body plus what the client needs to show it. */
export interface CardMove extends TaskMoveRequest {
  taskId: number;
  /** The card's project (refreshes its Gantt and task list once the move settles). */
  projectId?: number | null;
  /** An engineer pulling unassigned work: the server assigns it to them. */
  assignTo?: number | null;
}

/** The `POST /tasks/{id}/move` body for a move. */
export function toMoveRequest(move: CardMove): TaskMoveRequest {
  return {
    to_status: move.to_status,
    after_task_id: move.after_task_id,
    before_task_id: move.before_task_id,
    position: move.position,
    expected_status: move.expected_status,
  };
}

function withTasks(lane: Lane, tasks: Card[]): Lane {
  const wip = tasks.filter(isOpenCard).length;
  // The scope-wide count moves by what moved on this board.
  const scope_wip = lane.scope_wip == null ? null : Math.max(0, lane.scope_wip + wip - lane.wip);
  return {
    ...lane,
    tasks,
    wip,
    scope_wip,
    over_limit: overLimit({ wip, scope_wip, wip_limit: lane.wip_limit }),
  };
}

/**
 * Whether the server will refuse `move` for a full column — enforcement `block`, and the
 * target column (a started-work column with a limit) already holds its limit across the WIP
 * scope. The board skips the optimistic move then, so the card doesn't hop over and back;
 * the server still has the last word (our counts may be stale).
 */
export function wouldBlockOnWip(board: Board, move: CardMove): boolean {
  const toStatus = move.to_status;
  if (board.wip_enforcement !== "block" || toStatus === undefined) return false;
  const target = board.lanes.find((l) => fold(l.status) === fold(toStatus));
  if (!target || target.wip_limit == null || isClosedCategory(target.category)) return false;
  if (target.tasks.some((t) => t.id === move.taskId)) return false; // a reorder, not an entry
  return limitWip(target) + 1 > target.wip_limit;
}

function insertionIndex(tasks: readonly Card[], move: CardMove): number {
  if (move.after_task_id != null) {
    const i = tasks.findIndex((t) => t.id === move.after_task_id);
    if (i >= 0) return i + 1;
  }
  if (move.before_task_id != null) {
    const i = tasks.findIndex((t) => t.id === move.before_task_id);
    if (i >= 0) return i;
  }
  return move.position === "top" ? 0 : tasks.length;
}

/**
 * The board as it will look once the server accepts `move` — shown at once, rolled back if it
 * refuses. Moving into another column stamps the card with that column's status and category
 * and restarts its age; both columns' WIP and over-limit flags are recomputed. A move the
 * server would refuse outright (unknown card or column) leaves the board as it is.
 */
export function applyOptimisticMove(board: Board, move: CardMove): Board {
  const from = board.lanes.findIndex((l) => l.tasks.some((t) => t.id === move.taskId));
  if (from < 0) return board;
  const toStatus = move.to_status;
  const to =
    toStatus === undefined ? from : board.lanes.findIndex((l) => fold(l.status) === fold(toStatus));
  if (to < 0) return board;
  const changesStatus = to !== from;
  const placed =
    move.after_task_id != null || move.before_task_id != null || toStatus === undefined;
  // Naming the card's own column without neighbours changes nothing (as on the server).
  if (!changesStatus && !placed) return board;

  const source = board.lanes[from];
  const target = board.lanes[to];
  const card = source.tasks.find((t) => t.id === move.taskId) as Card;
  const assignee = card.assignee_engineer_id ?? move.assignTo ?? null;
  const moved: Card = changesStatus
    ? {
        ...card,
        status: target.status,
        status_category: target.category,
        is_done: target.category != null ? target.category === "done" : target.is_done,
        age_days: 0,
        aging: false,
        assignee_engineer_id: assignee,
      }
    : { ...card, assignee_engineer_id: assignee };

  const remaining = source.tasks.filter((t) => t.id !== move.taskId);
  const into = changesStatus ? [...target.tasks] : [...remaining];
  into.splice(insertionIndex(into, move), 0, moved);

  const lanes = board.lanes.map((lane, i) => {
    if (i === to) return withTasks(lane, into);
    if (i === from) return withTasks(lane, remaining);
    return lane;
  });
  const agingCount = board.aging_count - (card.aging && !moved.aging ? 1 : 0);
  return { ...board, lanes, aging_count: agingCount };
}

/** Where a drop lands, as the move request's neighbour fields. */
export type Placement = Pick<TaskMoveRequest, "after_task_id" | "before_task_id" | "position">;

/**
 * The neighbours of a card dropped at `index` among a column's visible cards (`ids`, without
 * the moved card): the card above (`after_task_id`) and below (`before_task_id`) it. The
 * server ranks the card between them, so cards hidden by a filter keep their own places. An
 * empty column takes the card at its `position` end.
 */
export function placementAt(ids: readonly number[], index: number): Placement {
  const i = Math.max(0, Math.min(Math.trunc(index), ids.length));
  if (ids.length === 0) return { position: "bottom" };
  const placement: Placement = {};
  if (i > 0) placement.after_task_id = ids[i - 1];
  if (i < ids.length) placement.before_task_id = ids[i];
  return placement;
}

/** The neighbours of `cardId` in a column's visible order as a drop left it (with the card). */
export function placementOf(ids: readonly number[], cardId: number): Placement {
  const index = ids.indexOf(cardId);
  const rest = ids.filter((id) => id !== cardId);
  return placementAt(rest, index < 0 ? rest.length : index);
}

// --------------------------------------------------------------------------- //
// Filters
// --------------------------------------------------------------------------- //

/** "all", "none" (unassigned) or an engineer id. */
export type OwnerFilter = "all" | "none" | number;

export interface CardFilter {
  owner: OwnerFilter;
  /** Only cards carrying this tag (null = any). */
  tag: string | null;
  /** Only cards with an open blocker. */
  blocked: boolean;
  /** Only cards aging past the team's cycle-time P85. */
  aging: boolean;
  /** Team board: only this project's cards (null = every project). */
  project: number | null;
  /** Team board: only cards of projects in this pod (null = every pod). */
  pod: number | null;
}

export const NO_FILTER: CardFilter = {
  owner: "all",
  tag: null,
  blocked: false,
  aging: false,
  project: null,
  pod: null,
};

export function isFiltering(filter: CardFilter): boolean {
  return (
    filter.owner !== "all" ||
    filter.tag !== null ||
    filter.blocked ||
    filter.aging ||
    filter.project !== null ||
    filter.pod !== null
  );
}

/** `podOf` maps a project to its pod (the pod filter needs it; cards carry only a project). */
export function matchesFilter(
  card: Card,
  filter: CardFilter,
  podOf: ReadonlyMap<number, number | null> = new Map(),
): boolean {
  if (filter.owner === "none" && card.assignee_engineer_id !== null) return false;
  if (typeof filter.owner === "number" && card.assignee_engineer_id !== filter.owner) return false;
  if (filter.tag !== null && !card.tags.includes(filter.tag)) return false;
  if (filter.blocked && !card.blocked) return false;
  if (filter.aging && !card.aging) return false;
  if (filter.project !== null && card.project_id !== filter.project) return false;
  if (filter.pod !== null && (podOf.get(card.project_id ?? -1) ?? null) !== filter.pod) return false;
  return true;
}

/** The lanes showing only the cards that pass the filter. A lane's `wip` stays the column's
 *  real WIP — a filter narrows what you see, not what the limit counts. */
export function filterCards(
  lanes: readonly Lane[],
  filter: CardFilter,
  podOf?: ReadonlyMap<number, number | null>,
): Lane[] {
  if (!isFiltering(filter)) return [...lanes];
  return lanes.map((lane) => ({
    ...lane,
    tasks: lane.tasks.filter((card) => matchesFilter(card, filter, podOf)),
  }));
}

/** The tags present on the board, sorted. */
export function boardTags(lanes: readonly Lane[]): string[] {
  return [...new Set(lanes.flatMap((l) => l.tasks.flatMap((t) => t.tags)))].sort((a, b) =>
    a.localeCompare(b),
  );
}

/** The engineers owning cards on the board. */
export function boardOwners(lanes: readonly Lane[]): number[] {
  const ids = lanes.flatMap((l) => l.tasks.map((t) => t.assignee_engineer_id));
  return [...new Set(ids.filter((id): id is number => id !== null))];
}

// --------------------------------------------------------------------------- //
// Swimlanes
// --------------------------------------------------------------------------- //

export type SwimlaneMode = "none" | "owner" | "parent" | "project";

export interface Swimlane {
  key: string;
  /** Empty for the single swimlane of an ungrouped board. */
  label: string;
  /** The owner / phase / project this row groups; null = none. */
  groupId: number | null;
  /** Every column, holding only this row's cards. */
  lanes: Lane[];
  count: number;
}

const NONE_LABELS: Record<Exclude<SwimlaneMode, "none">, string> = {
  owner: "Unassigned",
  parent: "No phase",
  project: "No project",
};

/**
 * Split the board into horizontal rows: one per owner or per project (alphabetical, the
 * "none" row last) or per WBS phase (in `labels` order, "No phase" last). `labels` names the
 * owners, phases or projects; an id it doesn't know reads "#id". Only rows that hold cards
 * appear; a board without cards is one empty row, so its columns still show.
 */
export function groupIntoSwimlanes(
  lanes: readonly Lane[],
  mode: SwimlaneMode,
  labels: ReadonlyMap<number, string> = new Map(),
): Swimlane[] {
  const total = lanes.reduce((n, l) => n + l.tasks.length, 0);
  const all: Swimlane = { key: "all", label: "", groupId: null, lanes: [...lanes], count: total };
  if (mode === "none" || total === 0) return [all];

  const groupOf = (card: Card): number | null =>
    mode === "owner" ? card.assignee_engineer_id : mode === "parent" ? card.parent_id : card.project_id;
  const present = new Set<number | null>(lanes.flatMap((l) => l.tasks.map(groupOf)));
  const labelOf = (id: number): string => labels.get(id) ?? `#${id}`;
  const known = [...labels.keys()];

  const ids = [...present].filter((id): id is number => id !== null);
  ids.sort((a, b) => {
    if (mode !== "parent") return labelOf(a).localeCompare(labelOf(b));
    const ia = known.indexOf(a);
    const ib = known.indexOf(b);
    if (ia !== ib) return (ia < 0 ? Infinity : ia) - (ib < 0 ? Infinity : ib);
    return a - b;
  });
  const groups: (number | null)[] = present.has(null) ? [...ids, null] : ids;

  return groups.map((id) => {
    const rowLanes = lanes.map((lane) => ({
      ...lane,
      tasks: lane.tasks.filter((card) => groupOf(card) === id),
    }));
    return {
      key: `${mode}:${id ?? "none"}`,
      label: id === null ? NONE_LABELS[mode] : labelOf(id),
      groupId: id,
      lanes: rowLanes,
      count: rowLanes.reduce((n, l) => n + l.tasks.length, 0),
    };
  });
}

/** A drag's working layout: cell id → the card ids it shows, in order. */
export type Layout = Record<string, number[]>;

/** The cell an id belongs to: a cell id is its own container; a card id is in the cell that
 *  lists it. */
export function containerOf(id: string | number, layout: Readonly<Layout>): string | null {
  if (typeof id === "string") return id in layout ? id : null;
  for (const [cell, ids] of Object.entries(layout)) {
    if (ids.includes(id)) return cell;
  }
  return null;
}

/** Two card orders are the same (a drop that changed nothing). */
export function sameOrder(a: readonly number[] | undefined, b: readonly number[] | undefined): boolean {
  if (!a || !b || a.length !== b.length) return false;
  return a.every((id, i) => id === b[i]);
}

/** The id of one swimlane × column cell (a drop container). Encoded, so any status name works. */
export function cellId(swimlaneKey: string, status: string): string {
  return `cell:${encodeURIComponent(swimlaneKey)}:${encodeURIComponent(status)}`;
}

export function parseCellId(id: unknown): { swimlane: string; status: string } | null {
  if (typeof id !== "string" || !id.startsWith("cell:")) return null;
  const parts = id.slice("cell:".length).split(":");
  if (parts.length !== 2) return null;
  try {
    return { swimlane: decodeURIComponent(parts[0]), status: decodeURIComponent(parts[1]) };
  } catch {
    return null;
  }
}

// --------------------------------------------------------------------------- //
// Refusals
// --------------------------------------------------------------------------- //

export interface TrackingFailure {
  /** The refusal's machine code (`status_externally_owned`, `wip_limit_reached`, `stale`,
   *  `unknown_status`, `column_in_use`, `native_tracking_disabled`, …), when it has one. */
  code: string | null;
  message: string;
  /** For `status_externally_owned`: the tracker and the item's page. */
  provider: string | null;
  url: string | null;
  /** For `column_in_use`: the removed columns that still hold cards. */
  columns: string[];
  /** For `connection_in_use`: the projects still mirrored from the connection. */
  projectIds: number[];
}

/** Read a failed call's body — FastAPI's `{detail: {code, message, …}}`, a plain
 *  `{detail: "…"}`, or validation errors `{detail: [{msg}]}` — into one shape. */
export function trackingFailure(err: unknown): TrackingFailure {
  const raw = err instanceof Error ? err.message : String(err);
  const failure: TrackingFailure = {
    code: null,
    message: raw || "Something went wrong.",
    provider: null,
    url: null,
    columns: [],
    projectIds: [],
  };
  let body: unknown;
  try {
    body = JSON.parse(raw);
  } catch {
    return failure; // not JSON — show it as it came
  }
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return { ...failure, message: detail };
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d as { msg?: unknown } | null)?.msg)
      .filter((m): m is string => typeof m === "string");
    return msgs.length ? { ...failure, message: msgs.join("; ") } : failure;
  }
  if (detail && typeof detail === "object") {
    const d = detail as Record<string, unknown>;
    const code = typeof d.code === "string" ? d.code : null;
    return {
      code,
      message: typeof d.message === "string" ? d.message : (code ?? failure.message),
      provider: typeof d.provider === "string" ? d.provider : null,
      url: typeof d.url === "string" ? d.url : null,
      columns: Array.isArray(d.columns)
        ? d.columns.filter((c): c is string => typeof c === "string")
        : [],
      projectIds: Array.isArray(d.project_ids)
        ? d.project_ids.filter((p): p is number => typeof p === "number")
        : [],
    };
  }
  return failure;
}
