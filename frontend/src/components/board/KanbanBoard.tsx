import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  MeasuringStrategy,
  TouchSensor,
  closestCenter,
  getFirstCollision,
  pointerWithin,
  rectIntersection,
  useSensor,
  useSensors,
  type Active,
  type Announcements,
  type CollisionDetection,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
  type Over,
  type UniqueIdentifier,
} from "@dnd-kit/core";
import { arrayMove, hasSortableData, sortableKeyboardCoordinates } from "@dnd-kit/sortable";

import { api } from "../../api/client";
import type { BoardResponse, Engineer, Sprint, Task, TeamDelivery } from "../../api/types";
import {
  NO_FILTER,
  boardOwners,
  boardPath,
  boardQueryKey,
  boardTags,
  canDrag,
  canMove,
  cardLabel,
  cellId,
  containerOf,
  expectedStatusOf,
  filterCards,
  fold,
  foldedStatus,
  groupIntoSwimlanes,
  isFiltering,
  moveTargets,
  normalizeBoard,
  placementOf,
  sameOrder,
  trackerName,
  trackingFailure,
  viewerForRole,
  wouldBlockOnWip,
  type Board,
  type BoardSource,
  type Card,
  type CardFilter,
  type CardMove,
  type Lane,
  type Layout,
  type Placement,
  type Swimlane,
  type SwimlaneMode,
} from "../../lib/board";
import { canContribute, isPlanner } from "../../lib/permissions";
import {
  defaultSprintSelection,
  localToday,
  shownSprint,
  sprintParam,
  usesSprints,
  type SprintSelection,
} from "../../lib/sprints";
import { useCurrentUser } from "../../lib/useCurrentUser";
import { featureOn, useFeatures } from "../../lib/useFeatures";
import { useMoveCard } from "../../lib/useMoveCard";
import { QueryError } from "../QueryError";
import { BoardCardView, SortableBoardCard } from "./BoardCard";
import { BoardColumnCell, BoardColumnHeader } from "./BoardColumn";
import BoardToolbar from "./BoardToolbar";
import QuickAdd, { type QuickAddDefaults, type QuickAddProject } from "./QuickAdd";
import { MOUSE_ACTIVATION, MouseAndPenSensor, TOUCH_ACTIVATION } from "./sensors";
import WorkflowEditor from "./WorkflowEditor";

const SCREEN_READER_INSTRUCTIONS = {
  draggable:
    "To pick up a card, press space or enter on its drag handle. Use the up and down arrow keys " +
    "to move it within its column, and the left and right arrow keys to move it to another " +
    "column. Press space or enter again to drop it, or escape to cancel. Each card also has a " +
    "Move to menu.",
};

const COLUMN_WIDTH = "16rem";
const COLLAPSED_WIDTH = "2.75rem";

/** A project on a team board. */
export interface BoardProject {
  id: number;
  key: string;
  name: string;
  pod_id: number | null;
}

const NO_PROJECTS: BoardProject[] = [];
const NO_PODS: { id: number; name: string }[] = [];

interface CellInfo {
  swimlane: Swimlane;
  lane: Lane;
  collapsed: boolean;
}

interface DragState {
  activeId: number;
  /** The column the card was picked up from (a team board may show a card in a column that
   *  isn't its own status, so a move is a change of column, not of status name). */
  originLane: string;
  /** The layout when the card was picked up, and as the drag reshapes it. */
  start: Layout;
  items: Layout;
  /** The cells the card may land in. */
  allowed: ReadonlySet<string>;
}

/** The layout a drop left, shown until the optimistic move reaches the cache (so the card
 *  never flashes back to where it came from). */
interface Held {
  taskId: number;
  items: Layout;
  base: Board;
}

interface Notice {
  tone: "error" | "warn";
  text: string;
  link?: { href: string; label: string };
}

function cellName(info: CellInfo | undefined): string {
  if (!info) return "a column";
  return info.swimlane.label ? `${info.lane.status} — ${info.swimlane.label}` : info.lane.status;
}

/**
 * The Kanban board (USER_FLOWS §C9, §C11.2): the workflow's columns in order with their WIP
 * limits, ranked cards, filters and swimlanes — for one project or for every project a team
 * runs (`source`). Cards move by drag and drop (mouse, touch, keyboard), by their "Move to…"
 * menu, or from the task drawer — all through `POST /tasks/{id}/move`, shown optimistically. A
 * mirrored card's status belongs to its tracker: it can be reordered in its column but not
 * moved out of it. For a team that runs sprints, a sprint selector narrows the board.
 */
export default function KanbanBoard({
  source,
  onTaskClick,
  onTaskCreated,
  teamId: projectTeamId,
  projects = NO_PROJECTS,
  pods = NO_PODS,
  canEditColumns,
}: {
  source: BoardSource;
  onTaskClick?: (taskId: number, projectId: number) => void;
  /** After a card is added (the project view re-plans so the new task gets dates). */
  onTaskCreated?: () => void;
  /** Project board: the project's team — its delivery method decides the sprint selector
   *  (undefined while it is being worked out, null = no team). A team board is its own team. */
  teamId?: number | null;
  /** Team board: the team's projects (card labels, the project filter, quick add) and pods. */
  projects?: BoardProject[];
  pods?: { id: number; name: string }[];
  /** Who may edit the columns, when it isn't the board's planners (a team's columns belong to
   *  its directors and managers). */
  canEditColumns?: boolean;
}) {
  const qc = useQueryClient();
  const features = useFeatures();
  const teamId = source.kind === "team" ? source.id : projectTeamId;
  const projectId = source.kind === "project" ? source.id : null;

  // A team that runs sprints gets a sprint selector; the board waits for the team's method so
  // it opens on the active sprint rather than flashing all work first.
  const delivery = useQuery({
    queryKey: ["team-delivery", teamId],
    queryFn: () => api.get<TeamDelivery>(`/teams/${teamId}/delivery`),
    enabled: teamId != null,
  });
  const sprinting =
    teamId != null &&
    featureOn(features, "tracking.sprints") &&
    usesSprints(delivery.data?.effective_method);
  const sprintList = useQuery({
    queryKey: ["sprints", teamId],
    queryFn: () => api.get<Sprint[]>(`/teams/${teamId}/sprints`),
    enabled: sprinting,
  });
  const [sprintChoice, setSprintChoice] = useState<SprintSelection | null>(null);
  const selection = sprintChoice ?? defaultSprintSelection(delivery.data?.active_sprint_id);
  const param = sprinting ? sprintParam(selection) : null;
  const ready = teamId === null || (teamId !== undefined && !delivery.isPending);

  const boardKey = boardQueryKey(source, param);
  const boardQuery = useQuery({
    queryKey: boardKey,
    queryFn: async () => normalizeBoard(await api.get<BoardResponse>(boardPath(source, param))),
    enabled: ready,
    // Switching sprints keeps the last board on screen (dimmed, inert) until the next arrives.
    placeholderData: keepPreviousData,
  });
  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });
  const { data: me } = useCurrentUser();

  const [filter, setFilter] = useState<CardFilter>(NO_FILTER);
  const [swimlaneMode, setSwimlaneMode] = useState<SwimlaneMode>("none");
  const [collapsedOverrides, setCollapsedOverrides] = useState<Record<string, boolean>>({});
  const [notice, setNotice] = useState<Notice | null>(null);
  const [editingColumns, setEditingColumns] = useState(false);
  const [drag, setDrag] = useState<DragState | null>(null);
  // The drag handlers read and write this synchronously: dnd-kit calls onDragEnd with the
  // last committed render's props, which can predate the latest onDragOver on a fast release.
  const dragRef = useRef<DragState | null>(null);
  const updateDrag = (next: DragState | null) => {
    dragRef.current = next;
    setDrag(next);
  };
  const [held, setHeld] = useState<Held | null>(null);

  // Phases name the "By phase" swimlanes (shares the project view's task list cache).
  const phases = useQuery({
    queryKey: ["tasks", projectId],
    queryFn: () => api.get<Task[]>(`/tasks?project_id=${projectId}`),
    enabled: swimlaneMode === "parent" && projectId !== null,
  });

  const placeholder = boardQuery.isPlaceholderData;
  const board = boardQuery.data;
  // The optimistic move reached the cache (or a refetch replaced it): stop holding the drop.
  if (held && held.base !== board) setHeld(null);
  const heldItems = held && held.base === board ? held.items : null;

  const viewer = useMemo(
    () =>
      viewerForRole(
        board?.viewer,
        me ? { planner: isPlanner(me.role), contributor: canContribute(me.role) } : null,
      ),
    [board?.viewer, me],
  );
  // While the next sprint's board loads, the last one shows but nothing on it moves.
  const actor = placeholder ? null : viewer;
  const names = useMemo(
    () => new Map((engineers.data ?? []).map((e) => [e.id, e.name] as const)),
    [engineers.data],
  );
  const projectsById = useMemo(() => new Map(projects.map((p) => [p.id, p] as const)), [projects]);
  const podOf = useMemo(
    () => new Map(projects.map((p) => [p.id, p.pod_id] as const)),
    [projects],
  );
  const swimlaneLabels = useMemo(() => {
    if (swimlaneMode === "owner") return names;
    if (swimlaneMode === "project") {
      return new Map(projects.map((p) => [p.id, `${p.key} · ${p.name}`] as const));
    }
    return new Map(
      (phases.data ?? []).filter((t) => t.type === "summary").map((t) => [t.id, t.name] as const),
    );
  }, [swimlaneMode, names, projects, phases.data]);
  const cardsById = useMemo(
    () => new Map((board?.lanes ?? []).flatMap((l) => l.tasks.map((t) => [t.id, t] as const))),
    [board],
  );
  const visibleLanes = useMemo(
    () => (board ? filterCards(board.lanes, filter, podOf) : []),
    [board, filter, podOf],
  );
  const swimlanes = useMemo(
    () => groupIntoSwimlanes(visibleLanes, swimlaneMode, swimlaneLabels),
    [visibleLanes, swimlaneMode, swimlaneLabels],
  );
  const isCollapsed = useCallback(
    (lane: Lane) => collapsedOverrides[lane.status] ?? lane.category === "cancelled",
    [collapsedOverrides],
  );
  const { cells, baseItems } = useMemo(() => {
    const cellMap = new Map<string, CellInfo>();
    const layout: Layout = {};
    for (const swimlane of swimlanes) {
      for (const lane of swimlane.lanes) {
        const id = cellId(swimlane.key, lane.status);
        cellMap.set(id, { swimlane, lane, collapsed: isCollapsed(lane) });
        layout[id] = lane.tasks.map((t) => t.id);
      }
    }
    return { cells: cellMap, baseItems: layout };
  }, [swimlanes, isCollapsed]);
  const items = drag?.items ?? heldItems ?? baseItems;

  const closeEditor = useCallback(() => setEditingColumns(false), []);

  // --- moves ------------------------------------------------------------------
  // Every sprint variant of this board is updated at once (they share the key prefix).
  const move = useMoveCard(boardQueryKey(source), {
    onSuccess: (res, m) => {
      if (m.to_status !== undefined && res.warnings.includes("wip_limit_exceeded")) {
        const limit = board?.lanes.find((l) => fold(l.status) === fold(m.to_status ?? ""))?.wip_limit;
        setNotice({
          tone: "warn",
          text: `Moved — “${res.task.status ?? m.to_status}” is now over its WIP limit${
            limit != null ? ` of ${limit}` : ""
          }. Consider finishing work there before starting more.`,
        });
      }
    },
    onError: (err) => {
      const failure = trackingFailure(err);
      setNotice({
        tone: "error",
        text: failure.message,
        link: failure.url
          ? { href: failure.url, label: `Open in ${trackerName(failure.provider ?? "tracker")}` }
          : undefined,
      });
    },
    onSettled: (m) => setHeld((h) => (h && h.taskId === m.taskId ? null : h)),
  });

  /** Send a move. `dropped` is the layout a drag left: held on screen until the optimistic
   *  move lands — unless the column is full under `block`, when the card stays put. */
  const commitMove = (
    card: Card,
    toStatus: string | undefined,
    placement: Placement,
    dropped?: Layout,
  ) => {
    const pulling =
      toStatus !== undefined &&
      actor !== null &&
      !actor.can_plan &&
      card.assignee_engineer_id === null;
    const request: CardMove = {
      taskId: card.id,
      projectId: card.project_id,
      to_status: toStatus,
      expected_status: expectedStatusOf(card),
      assignTo: pulling ? actor.engineer_id : null,
      ...placement,
    };
    if (dropped && board && !wouldBlockOnWip(board, request)) {
      setHeld({ taskId: card.id, items: dropped, base: board });
    }
    setNotice(null);
    move.mutate(request);
  };

  const moveTo = (card: Card, status: string) => commitMove(card, status, { position: "bottom" });

  // --- drag and drop -----------------------------------------------------------
  const sensors = useSensors(
    useSensor(MouseAndPenSensor, { activationConstraint: MOUSE_ACTIVATION }),
    useSensor(TouchSensor, { activationConstraint: TOUCH_ACTIVATION }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const lastOverId = useRef<UniqueIdentifier | null>(null);
  const movedToNewCell = useRef(false);
  useEffect(() => {
    requestAnimationFrame(() => {
      movedToNewCell.current = false;
    });
  }, [items]);

  /** Aim at a card rather than the column holding it, and hold the last target steady while
   *  a card that just changed column re-lays out (dnd-kit's multiple-containers pattern). */
  const collisionDetection: CollisionDetection = useCallback(
    (args) => {
      const layout = dragRef.current?.items ?? items;
      const pointerHits = pointerWithin(args);
      const hits = pointerHits.length > 0 ? pointerHits : rectIntersection(args);
      let overId = getFirstCollision(hits, "id");
      if (overId != null) {
        const inCell = typeof overId === "string" ? layout[overId] : undefined;
        if (inCell && inCell.length > 0 && !cells.get(String(overId))?.collapsed) {
          const cell = overId;
          const nearest = closestCenter({
            ...args,
            droppableContainers: args.droppableContainers.filter(
              (c) => c.id !== cell && typeof c.id === "number" && inCell.includes(c.id),
            ),
          })[0]?.id;
          if (nearest != null) overId = nearest;
        }
        lastOverId.current = overId;
        return [{ id: overId }];
      }
      const dragging = dragRef.current;
      if (movedToNewCell.current && dragging) lastOverId.current = dragging.activeId;
      return lastOverId.current != null ? [{ id: lastOverId.current }] : [];
    },
    [items, cells],
  );

  const handleDragStart = ({ active }: DragStartEvent) => {
    const id = Number(active.id);
    const card = cardsById.get(id);
    const origin = containerOf(id, items);
    const originInfo = origin ? cells.get(origin) : undefined;
    if (!card || !origin || !originInfo) return;
    const allowed = new Set<string>([origin]);
    if (canMove(card, actor, { changesStatus: true })) {
      for (const [cell, info] of cells) {
        if (
          info.swimlane.key === originInfo.swimlane.key &&
          info.lane.in_workflow &&
          fold(info.lane.status) !== fold(originInfo.lane.status)
        ) {
          allowed.add(cell);
        }
      }
    }
    lastOverId.current = null;
    setNotice(null);
    updateDrag({ activeId: id, originLane: originInfo.lane.status, start: items, items, allowed });
  };

  // Crossing into another cell moves the card there in the working layout (within a cell,
  // the sortable list animates the reorder itself).
  const handleDragOver = ({ active, over }: DragOverEvent) => {
    const current = dragRef.current;
    if (!current || !over) return;
    const from = containerOf(active.id, current.items);
    const to = containerOf(over.id, current.items);
    if (!from || !to || from === to || !current.allowed.has(to) || cells.get(to)?.collapsed) {
      return;
    }
    const id = Number(active.id);
    const toIds = current.items[to];
    let index = toIds.length;
    if (typeof over.id === "number") {
      const overIndex = toIds.indexOf(over.id);
      const dragged = active.rect.current.translated;
      const below = dragged != null && dragged.top > over.rect.top + over.rect.height;
      if (overIndex >= 0) index = overIndex + (below ? 1 : 0);
    }
    movedToNewCell.current = true;
    updateDrag({
      ...current,
      items: {
        ...current.items,
        [from]: current.items[from].filter((x) => x !== id),
        [to]: [...toIds.slice(0, index), id, ...toIds.slice(index)],
      },
    });
  };

  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    const current = dragRef.current;
    updateDrag(null);
    if (!current || !over || !board) return;
    const id = Number(active.id);
    const card = cardsById.get(id);
    if (!card) return;

    let layout = current.items;
    let target = containerOf(id, layout);
    let placement: Placement;
    const overCell = typeof over.id === "string" ? over.id : null;
    if (overCell && cells.get(overCell)?.collapsed && current.allowed.has(overCell)) {
      // Dropped on a collapsed column: into it, at the bottom.
      if (target) layout = { ...layout, [target]: layout[target].filter((x) => x !== id) };
      target = overCell;
      layout = { ...layout, [overCell]: [...(layout[overCell] ?? []), id] };
      placement = { position: "bottom" };
    } else {
      if (!target) return;
      if (typeof over.id === "number" && over.id !== id && containerOf(over.id, layout) === target) {
        const ids = layout[target];
        layout = { ...layout, [target]: arrayMove(ids, ids.indexOf(id), ids.indexOf(over.id)) };
      }
      placement = placementOf(layout[target], id);
    }

    const info = cells.get(target);
    if (!info) return;
    const changesStatus = fold(info.lane.status) !== fold(current.originLane);
    if (!changesStatus && sameOrder(layout[target], current.start[target])) return;
    if (!canMove(card, actor, { changesStatus })) {
      setNotice({
        tone: "warn",
        text: changesStatus
          ? `${cardLabel(card)} can’t move to “${info.lane.status}”.`
          : "Only planners reorder unassigned work — move the card into another column to pull it.",
      });
      return;
    }
    commitMove(card, changesStatus ? info.lane.status : undefined, placement, layout);
  };

  // Screen-reader narration of a drag, in the board's own words.
  const announcements: Announcements = useMemo(() => {
    const labelOf = (active: Active) => {
      const card = cardsById.get(Number(active.id));
      return card ? cardLabel(card) : "The card";
    };
    const where = (entry: Active | Over) => {
      if (hasSortableData(entry)) {
        const { containerId, index, items: ids } = entry.data.current.sortable;
        return `${cellName(cells.get(String(containerId)))}, position ${index + 1} of ${ids.length}`;
      }
      return cellName(cells.get(String(entry.id)));
    };
    return {
      onDragStart: ({ active }) => `Picked up ${labelOf(active)}. It is in ${where(active)}.`,
      onDragOver: ({ active, over }) =>
        over
          ? `${labelOf(active)} is over ${where(over)}.`
          : `${labelOf(active)} is not over a column it can move to.`,
      onDragEnd: ({ active, over }) =>
        over
          ? `${labelOf(active)} was dropped in ${where(over)}.`
          : `${labelOf(active)} was dropped back where it was.`,
      onDragCancel: ({ active }) => `Moving ${labelOf(active)} was cancelled. It is back where it was.`,
    };
  }, [cardsById, cells]);

  // --- render --------------------------------------------------------------------
  if (boardQuery.isError) {
    return (
      <QueryError
        error={boardQuery.error}
        onRetry={() => void boardQuery.refetch()}
        label="Couldn’t load the board"
      />
    );
  }
  if (!board) return <p className="text-sm text-slate-500">Loading board…</p>;

  const columns = board.lanes;
  const totalCount = cardsById.size;
  const shownCount = visibleLanes.reduce((n, l) => n + l.tasks.length, 0);
  const owners = boardOwners(board.lanes)
    .map((id) => [id, names.get(id) ?? `#${id}`] as [number, string])
    .sort((a, b) => a[1].localeCompare(b[1]));
  const today = localToday();
  const addTargets: QuickAddProject[] =
    projectId !== null
      ? [{ id: projectId, label: "This project" }]
      : projects
          .map((p) => ({ id: p.id, label: `${p.key} · ${p.name}` }))
          .sort((a, b) => a.label.localeCompare(b.label));
  const canAdd =
    actor !== null && actor.can_plan && actor.native_enabled && addTargets.length > 0;
  const activeCard = drag ? cardsById.get(drag.activeId) : undefined;
  const reducedMotion =
    typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const sprints = sprintList.data ?? [];
  const mayEditColumns = canEditColumns ?? viewer?.can_plan ?? false;

  const quickAddDefaults = (swimlane: Swimlane): QuickAddDefaults => {
    if (swimlane.groupId === null) return {};
    if (swimlaneMode === "owner") return { assignee_engineer_id: swimlane.groupId };
    if (swimlaneMode === "parent") return { parent_id: swimlane.groupId };
    return {};
  };
  const quickAddProject = (swimlane: Swimlane): number | undefined =>
    swimlaneMode === "project" && swimlane.groupId !== null
      ? swimlane.groupId
      : (filter.project ?? undefined);
  const afterCreate = (task: Task) => {
    void qc.invalidateQueries({ queryKey: boardQueryKey(source) });
    void qc.invalidateQueries({ queryKey: ["tasks", task.project_id] });
    void qc.invalidateQueries({ queryKey: ["gantt", task.project_id] });
    onTaskCreated?.();
  };
  const projectLabel = (card: Card): string | undefined =>
    source.kind === "team" && card.project_id !== null
      ? projectsById.get(card.project_id)?.key
      : undefined;

  return (
    <div className="space-y-3">
      <BoardToolbar
        board={board}
        viewer={viewer}
        filter={filter}
        onFilterChange={setFilter}
        swimlanes={swimlaneMode}
        onSwimlanesChange={setSwimlaneMode}
        swimlaneModes={
          source.kind === "project" ? ["none", "owner", "parent"] : ["none", "owner", "project"]
        }
        owners={owners}
        tags={boardTags(board.lanes)}
        projects={
          source.kind === "team"
            ? projects
                .map((p) => [p.id, `${p.key} · ${p.name}`] as [number, string])
                .sort((a, b) => a[1].localeCompare(b[1]))
            : []
        }
        pods={pods.map((p) => [p.id, p.name] as [number, string])}
        sprint={
          sprinting
            ? {
                selection,
                onChange: setSprintChoice,
                sprints,
                shown: shownSprint(selection, sprints, board.sprint_id),
                today,
              }
            : undefined
        }
        shownCount={shownCount}
        totalCount={totalCount}
        onEditColumns={mayEditColumns ? () => setEditingColumns(true) : undefined}
      />

      {notice && (
        <div
          role={notice.tone === "error" ? "alert" : "status"}
          className={`flex items-start justify-between gap-3 rounded border px-4 py-2 text-sm ${
            notice.tone === "error"
              ? "border-red-300 bg-red-50 text-red-700"
              : "border-amber-300 bg-amber-50 text-amber-800"
          }`}
        >
          <span>
            {notice.text}
            {notice.link && (
              <>
                {" "}
                <a
                  href={notice.link.href}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium underline"
                >
                  {notice.link.label} ↗
                </a>
              </>
            )}
          </span>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Dismiss"
            className="opacity-70 hover:opacity-100"
          >
            ✕
          </button>
        </div>
      )}

      {totalCount === 0 && !placeholder && (
        <p className="text-sm text-slate-500">
          {param && param !== "all"
            ? "No cards in this view."
            : `No cards yet. ${
                canAdd
                  ? "Add one at the foot of a column."
                  : "Status comes from board moves for tasks canopy tracks, and from tracker syncs for mirrored ones."
              }`}
        </p>
      )}

      {columns.length === 0 ? (
        <p className="text-sm text-slate-500">This board has no columns yet.</p>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={collisionDetection}
          measuring={{ droppable: { strategy: MeasuringStrategy.Always } }}
          accessibility={{ announcements, screenReaderInstructions: SCREEN_READER_INSTRUCTIONS }}
          onDragStart={handleDragStart}
          onDragOver={handleDragOver}
          onDragEnd={handleDragEnd}
          onDragCancel={() => updateDrag(null)}
        >
          <div
            aria-busy={placeholder}
            className={`overflow-x-auto pb-2 transition-opacity ${placeholder ? "opacity-60" : ""}`}
          >
            <div
              className="grid gap-x-3 gap-y-2"
              style={{
                gridTemplateColumns: columns
                  .map((lane) => (isCollapsed(lane) ? COLLAPSED_WIDTH : COLUMN_WIDTH))
                  .join(" "),
              }}
            >
              {columns.map((lane) => (
                <BoardColumnHeader
                  key={lane.status}
                  lane={lane}
                  collapsed={isCollapsed(lane)}
                  onToggle={() =>
                    setCollapsedOverrides((o) => ({ ...o, [lane.status]: !isCollapsed(lane) }))
                  }
                />
              ))}
              {swimlanes.map((swimlane) => (
                <Fragment key={swimlane.key}>
                  {swimlane.label && (
                    <div style={{ gridColumn: "1 / -1" }} className="pt-2">
                      <h3 className="sticky left-0 inline-flex items-center gap-2 text-sm font-semibold text-slate-700">
                        {swimlane.label}
                        <span className="text-xs font-normal text-slate-400">
                          {swimlane.count} card{swimlane.count === 1 ? "" : "s"}
                        </span>
                      </h3>
                    </div>
                  )}
                  {swimlane.lanes.map((lane) => {
                    const id = cellId(swimlane.key, lane.status);
                    const info = cells.get(id);
                    const collapsed = isCollapsed(lane);
                    const ids = (items[id] ?? []).filter((cardId) => cardsById.has(cardId));
                    const blocked = drag !== null && !drag.allowed.has(id);
                    return (
                      <BoardColumnCell
                        key={id}
                        id={id}
                        lane={lane}
                        label={cellName(info)}
                        collapsed={collapsed}
                        cardIds={ids}
                        droppableDisabled={blocked}
                        highlighted={drag !== null && ids.includes(drag.activeId)}
                        dimmed={blocked}
                        emptyText={isFiltering(filter) ? "No matching cards" : "No cards"}
                        compact={swimlaneMode !== "none"}
                        footer={
                          canAdd && lane.in_workflow && !drag ? (
                            <QuickAdd
                              projects={addTargets}
                              defaultProjectId={quickAddProject(swimlane)}
                              status={lane.status}
                              defaults={quickAddDefaults(swimlane)}
                              onCreated={afterCreate}
                            />
                          ) : undefined
                        }
                      >
                        {ids.map((cardId) => {
                          const card = cardsById.get(cardId) as Card;
                          const statusMovable = canMove(card, actor, { changesStatus: true });
                          return (
                            <SortableBoardCard
                              key={cardId}
                              card={card}
                              ownerName={
                                card.assignee_engineer_id !== null
                                  ? names.get(card.assignee_engineer_id)
                                  : undefined
                              }
                              projectLabel={projectLabel(card)}
                              statusNote={foldedStatus(card, lane)}
                              today={today}
                              draggable={canDrag(card, actor)}
                              droppableDisabled={blocked}
                              moveTargets={statusMovable ? moveTargets(columns, card) : []}
                              onMoveTo={(status) => moveTo(card, status)}
                              onOpen={
                                onTaskClick
                                  ? () => onTaskClick(cardId, card.project_id ?? board.project_id)
                                  : undefined
                              }
                            />
                          );
                        })}
                      </BoardColumnCell>
                    );
                  })}
                </Fragment>
              ))}
            </div>
          </div>
          <DragOverlay dropAnimation={reducedMotion ? null : undefined}>
            {activeCard ? (
              <BoardCardView
                card={activeCard}
                ownerName={
                  activeCard.assignee_engineer_id !== null
                    ? names.get(activeCard.assignee_engineer_id)
                    : undefined
                }
                projectLabel={projectLabel(activeCard)}
                today={today}
                overlay
              />
            ) : null}
          </DragOverlay>
        </DndContext>
      )}

      {editingColumns && <WorkflowEditor source={source} board={board} onClose={closeEditor} />}
    </div>
  );
}
