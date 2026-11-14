import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  MeasuringStrategy,
  PointerSensor,
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
  type PointerSensorOptions,
  type UniqueIdentifier,
} from "@dnd-kit/core";
import { arrayMove, hasSortableData, sortableKeyboardCoordinates } from "@dnd-kit/sortable";

import { api } from "../../api/client";
import type { BoardResponse, Engineer, Task } from "../../api/types";
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
  groupIntoSwimlanes,
  isFiltering,
  moveTargets,
  normalizeBoard,
  placementOf,
  sameOrder,
  trackerName,
  trackingFailure,
  viewerForRole,
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
import { useCurrentUser } from "../../lib/useCurrentUser";
import { useMoveCard } from "../../lib/useMoveCard";
import { QueryError } from "../QueryError";
import { BoardCardView, SortableBoardCard } from "./BoardCard";
import { BoardColumnCell, BoardColumnHeader } from "./BoardColumn";
import BoardToolbar from "./BoardToolbar";
import QuickAdd, { type QuickAddDefaults } from "./QuickAdd";
import WorkflowEditor from "./WorkflowEditor";

/** The pointer sensor for mouse and pen. Touch is left to the TouchSensor's press-and-hold,
 *  so a swipe across the board still scrolls it (a pointer sensor would claim every touch). */
class MouseAndPenSensor extends PointerSensor {
  static activators = [
    {
      eventName: "onPointerDown" as const,
      handler: (
        { nativeEvent: event }: ReactPointerEvent,
        { onActivation }: PointerSensorOptions,
      ): boolean => {
        if (event.pointerType === "touch" || !event.isPrimary || event.button !== 0) return false;
        onActivation?.({ event });
        return true;
      },
    },
  ];
}

const SCREEN_READER_INSTRUCTIONS = {
  draggable:
    "To pick up a card, press space or enter on its drag handle. Use the up and down arrow keys " +
    "to move it within its column, and the left and right arrow keys to move it to another " +
    "column. Press space or enter again to drop it, or escape to cancel. Each card also has a " +
    "Move to menu.",
};

const COLUMN_WIDTH = "16rem";
const COLLAPSED_WIDTH = "2.75rem";

interface CellInfo {
  swimlane: Swimlane;
  lane: Lane;
  collapsed: boolean;
}

interface DragState {
  activeId: number;
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

/** Today in the viewer's time zone, as `YYYY-MM-DD` (deadlines are calendar days). */
function localToday(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function cellName(info: CellInfo | undefined): string {
  if (!info) return "a column";
  return info.swimlane.label ? `${info.lane.status} — ${info.swimlane.label}` : info.lane.status;
}

/**
 * The Kanban board (USER_FLOWS §C9): the workflow's columns in order with their WIP limits,
 * ranked cards, filters and swimlanes. Cards move by drag and drop (mouse, touch, keyboard), by
 * their "Move to…" menu, or from the task drawer — all through `POST /tasks/{id}/move`, shown
 * optimistically. A mirrored card's status belongs to its tracker: it can be reordered in its
 * column but not moved out of it. `source` says whose board this is, so a team board can reuse it.
 */
export default function KanbanBoard({
  source,
  onTaskClick,
  onTaskCreated,
}: {
  source: BoardSource;
  onTaskClick?: (taskId: number) => void;
  /** After a card is added (the project view re-plans so the new task gets dates). */
  onTaskCreated?: () => void;
}) {
  const qc = useQueryClient();
  const boardKey = boardQueryKey(source);
  const projectId = source.kind === "project" ? source.id : null;
  const boardQuery = useQuery({
    queryKey: boardKey,
    queryFn: async () => normalizeBoard(await api.get<BoardResponse>(boardPath(source))),
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
  const names = useMemo(
    () => new Map((engineers.data ?? []).map((e) => [e.id, e.name] as const)),
    [engineers.data],
  );
  const phaseNames = useMemo(
    () =>
      new Map(
        (phases.data ?? []).filter((t) => t.type === "summary").map((t) => [t.id, t.name] as const),
      ),
    [phases.data],
  );
  const cardsById = useMemo(
    () => new Map((board?.lanes ?? []).flatMap((l) => l.tasks.map((t) => [t.id, t] as const))),
    [board],
  );
  const visibleLanes = useMemo(() => (board ? filterCards(board.lanes, filter) : []), [board, filter]);
  const swimlanes = useMemo(
    () => groupIntoSwimlanes(visibleLanes, swimlaneMode, swimlaneMode === "owner" ? names : phaseNames),
    [visibleLanes, swimlaneMode, names, phaseNames],
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
  const move = useMoveCard(boardKey, {
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

  const commitMove = (card: Card, toStatus: string | undefined, placement: Placement) => {
    const pulling =
      toStatus !== undefined &&
      viewer !== null &&
      !viewer.can_plan &&
      card.assignee_engineer_id === null;
    const request: CardMove = {
      taskId: card.id,
      projectId: card.project_id,
      to_status: toStatus,
      expected_status: expectedStatusOf(card),
      assignTo: pulling ? viewer.engineer_id : null,
      ...placement,
    };
    setNotice(null);
    move.mutate(request);
  };

  const moveTo = (card: Card, status: string) => commitMove(card, status, { position: "bottom" });

  // --- drag and drop -----------------------------------------------------------
  const sensors = useSensors(
    useSensor(MouseAndPenSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 220, tolerance: 6 } }),
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
    if (canMove(card, viewer, { changesStatus: true })) {
      for (const [cell, info] of cells) {
        if (
          info.swimlane.key === originInfo.swimlane.key &&
          info.lane.in_workflow &&
          fold(info.lane.status) !== fold(card.status)
        ) {
          allowed.add(cell);
        }
      }
    }
    lastOverId.current = null;
    setNotice(null);
    updateDrag({ activeId: id, start: items, items, allowed });
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
    const changesStatus = fold(info.lane.status) !== fold(card.status);
    if (!changesStatus && sameOrder(layout[target], current.start[target])) return;
    if (!canMove(card, viewer, { changesStatus })) {
      setNotice({
        tone: "warn",
        text: changesStatus
          ? `${cardLabel(card)} can’t move to “${info.lane.status}”.`
          : "Only planners reorder unassigned work — move the card into another column to pull it.",
      });
      return;
    }
    setHeld({ taskId: id, items: layout, base: board });
    commitMove(card, changesStatus ? info.lane.status : undefined, placement);
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
  const canAdd = projectId !== null && viewer !== null && viewer.can_plan && viewer.native_enabled;
  const activeCard = drag ? cardsById.get(drag.activeId) : undefined;
  const reducedMotion =
    typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  const quickAddDefaults = (swimlane: Swimlane): QuickAddDefaults => {
    if (swimlane.groupId === null) return {};
    if (swimlaneMode === "owner") return { assignee_engineer_id: swimlane.groupId };
    if (swimlaneMode === "parent") return { parent_id: swimlane.groupId };
    return {};
  };
  const afterCreate = () => {
    void qc.invalidateQueries({ queryKey: boardKey });
    if (projectId !== null) {
      void qc.invalidateQueries({ queryKey: ["tasks", projectId] });
      void qc.invalidateQueries({ queryKey: ["gantt", projectId] });
    }
    onTaskCreated?.();
  };

  return (
    <div className="space-y-3">
      <BoardToolbar
        board={board}
        viewer={viewer}
        filter={filter}
        onFilterChange={setFilter}
        swimlanes={swimlaneMode}
        onSwimlanesChange={setSwimlaneMode}
        swimlaneModes={projectId !== null ? ["none", "owner", "parent"] : ["none", "owner"]}
        owners={owners}
        tags={boardTags(board.lanes)}
        shownCount={shownCount}
        totalCount={totalCount}
        onEditColumns={viewer?.can_plan ? () => setEditingColumns(true) : undefined}
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

      {totalCount === 0 && (
        <p className="text-sm text-slate-500">
          No cards yet.{" "}
          {canAdd
            ? "Add one at the foot of a column."
            : "Status comes from board moves for tasks canopy tracks, and from tracker syncs for mirrored ones."}
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
          <div className="overflow-x-auto pb-2">
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
                          canAdd && projectId !== null && lane.in_workflow && !drag ? (
                            <QuickAdd
                              projectId={projectId}
                              status={lane.status}
                              defaults={quickAddDefaults(swimlane)}
                              onCreated={afterCreate}
                            />
                          ) : undefined
                        }
                      >
                        {ids.map((cardId) => {
                          const card = cardsById.get(cardId) as Card;
                          const statusMovable = canMove(card, viewer, { changesStatus: true });
                          return (
                            <SortableBoardCard
                              key={cardId}
                              card={card}
                              ownerName={
                                card.assignee_engineer_id !== null
                                  ? names.get(card.assignee_engineer_id)
                                  : undefined
                              }
                              today={today}
                              draggable={canDrag(card, viewer)}
                              droppableDisabled={blocked}
                              moveTargets={statusMovable ? moveTargets(columns, card) : []}
                              onMoveTo={(status) => moveTo(card, status)}
                              onOpen={onTaskClick ? () => onTaskClick(cardId) : undefined}
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
