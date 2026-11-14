import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  TouchSensor,
  defaultKeyboardCoordinateGetter,
  pointerWithin,
  rectIntersection,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type Announcements,
  type ClientRect,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
  type KeyboardCoordinateGetter,
} from "@dnd-kit/core";

import { api } from "../../api/client";
import type { Sprint, SprintCapacity, SprintDetail, SprintUpdate, Task } from "../../api/types";
import {
  CANOPY_OWNER,
  cardLabel,
  isClosedCategory,
  trackerName,
  trackingFailure,
  type Board,
} from "../../lib/board";
import { invalidateSprintData } from "../../lib/sprintCache";
import {
  STATE_LABELS,
  capacityView,
  carryOverTargets,
  formatEstimate,
  formatSprintDates,
  planLists,
  timeLeftLabel,
  type PlanSide,
} from "../../lib/sprints";
import { initials } from "../GanttChart";
import { Icon } from "../icons";
import { MOUSE_ACTIVATION, MouseAndPenSensor, TOUCH_ACTIVATION } from "../board/sensors";

/** One task in the planning lists, from a board card (backlog) or a sprint task. */
interface PlanItem {
  id: number;
  key: string | null;
  name: string;
  projectId: number | null;
  assignee: number | null;
  status: string | null;
  points: number | null;
  /** Duration in working days — sprint tasks only (board cards don't carry it). */
  days: number | null;
  closed: boolean;
}

function fromTask(t: Task): PlanItem {
  return {
    id: t.id,
    key: t.key,
    name: t.name,
    projectId: t.project_id,
    assignee: t.assignee_engineer_id,
    status: t.status,
    points: t.story_points,
    days: t.duration,
    closed: isClosedCategory(t.status_category),
  };
}

/** Left/right jump straight to the other list; up/down move as usual. */
const listKeyboardCoordinates: KeyboardCoordinateGetter = (event, args) => {
  const { context, currentCoordinates } = args;
  const rect = context.collisionRect;
  if ((event.code === "ArrowLeft" || event.code === "ArrowRight") && rect) {
    event.preventDefault();
    const right = event.code === "ArrowRight";
    let best: ClientRect | null = null;
    for (const container of context.droppableContainers.getEnabled()) {
      const r = context.droppableRects.get(container.id);
      if (!r) continue;
      const ahead = right ? r.left > rect.left + 1 : r.left < rect.left - 1;
      if (ahead && (!best || Math.abs(r.left - rect.left) < Math.abs(best.left - rect.left))) best = r;
    }
    if (!best) return currentCoordinates;
    return {
      x: currentCoordinates.x + (best.left + 12 - rect.left),
      y: currentCoordinates.y + (best.top + 48 - rect.top),
    };
  }
  return defaultKeyboardCoordinateGetter(event, args);
};

const collisions: CollisionDetection = (args) => {
  const hits = pointerWithin(args);
  return hits.length > 0 ? hits : rectIntersection(args);
};

/** Open estimate against capacity: person-days (unit days) or mean velocity (points/count).
 *  Over capacity warns, never blocks. Lists each engineer's person-days over the sprint. */
function CapacityBar({ capacity }: { capacity: SprintCapacity }) {
  const view = capacityView(capacity);
  return (
    <section aria-label="Capacity" className="space-y-2 rounded-md border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="font-medium text-slate-700">Capacity</span>
        <span className="text-slate-600">{view.summary}</span>
      </div>
      {view.limit != null && (
        <div
          role="meter"
          aria-label="Planned work against capacity"
          aria-valuemin={0}
          aria-valuemax={view.limit}
          aria-valuenow={view.committed}
          aria-valuetext={view.summary}
          className="h-2 overflow-hidden rounded-full bg-slate-100"
        >
          <div
            className={`h-full rounded-full ${view.over ? "bg-amber-500" : "bg-canopy-500"}`}
            style={{ width: `${view.fillPct}%` }}
          />
        </div>
      )}
      {view.over && (
        <p className="flex items-center gap-1.5 text-xs text-amber-800">
          <Icon name="alerts" size={13} />
          Planned beyond capacity — a warning, not a block.
        </p>
      )}
      {capacity.engineers.length > 0 ? (
        <div className="text-xs text-slate-500">
          <span className="mr-1">{capacity.person_days} person-days over the sprint:</span>
          <ul className="mt-1 inline-flex flex-wrap gap-1">
            {capacity.engineers.map((e) => (
              <li key={e.engineer_id} className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">
                {e.name} · {e.person_days}d
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-slate-400">
          No engineer is allocated to the team’s projects over these dates.
        </p>
      )}
    </section>
  );
}

function PlanRow({
  item,
  unit,
  names,
  projectKeys,
  side,
  canMove,
  onMove,
  sprintName,
  overlay = false,
}: {
  item: PlanItem;
  unit: string;
  names: ReadonlyMap<number, string>;
  projectKeys: ReadonlyMap<number, string>;
  side: PlanSide;
  canMove: boolean;
  onMove?: () => void;
  sprintName: string;
  overlay?: boolean;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, isDragging } = useDraggable({
    id: item.id,
    disabled: !canMove || overlay,
    attributes: { roleDescription: "draggable task" },
  });
  const owner = item.assignee !== null ? names.get(item.assignee) : undefined;
  const estimate =
    unit === "points"
      ? item.points != null
        ? formatEstimate(item.points, "points")
        : null
      : unit === "days" && item.days != null
        ? formatEstimate(item.days, "days")
        : null;
  const project = item.projectId !== null ? projectKeys.get(item.projectId) : undefined;
  const label = cardLabel(item);
  return (
    <li
      ref={overlay ? undefined : setNodeRef}
      {...(canMove && !overlay ? listeners : {})}
      className={`flex list-none items-start gap-1.5 rounded-md border bg-white px-2 py-1.5 text-sm ${
        overlay ? "shadow-lg ring-1 ring-canopy-500" : "border-slate-200"
      } ${isDragging ? "opacity-40" : ""} ${canMove ? "touch-manipulation select-none" : ""}`}
    >
      {canMove && !overlay && (
        <button
          type="button"
          ref={setActivatorNodeRef}
          {...attributes}
          aria-label={`Drag ${label}`}
          className="mt-0.5 flex h-5 w-4 shrink-0 cursor-grab items-center justify-center rounded text-slate-300 hover:bg-slate-100 hover:text-slate-500 focus-visible:outline-2 focus-visible:outline-canopy-500"
        >
          <Icon name="grip" size={14} />
        </button>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1 text-[11px] text-slate-500">
          {project && !(item.key ?? "").startsWith(`${project}-`) && (
            <span className="rounded bg-slate-100 px-1 font-mono">{project}</span>
          )}
          {item.key && <span className="font-mono">{item.key}</span>}
          {item.status && <span className="text-slate-400">· {item.status}</span>}
        </div>
        <div className={`truncate ${item.closed ? "text-slate-400 line-through" : "text-slate-800"}`}>
          {item.name}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5 pt-0.5">
        {estimate && (
          <span className="rounded bg-slate-100 px-1 text-[11px] tabular-nums text-slate-600">
            {estimate}
          </span>
        )}
        {owner && (
          <span
            title={owner}
            className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-200 text-[10px] font-semibold text-slate-600"
          >
            {initials(owner)}
          </span>
        )}
        {canMove && onMove && !overlay && (
          <button
            type="button"
            onClick={onMove}
            onPointerDown={(e) => e.stopPropagation()}
            aria-label={
              side === "backlog" ? `Add ${label} to ${sprintName}` : `Move ${label} back to the backlog`
            }
            className="flex items-center gap-0.5 rounded border border-slate-200 px-1.5 py-0.5 text-[11px] text-slate-600 hover:border-canopy-500 hover:text-canopy-700"
          >
            {side === "backlog" ? (
              <>
                Add <Icon name="arrow-right" size={11} />
              </>
            ) : (
              <>
                <Icon name="arrow-left" size={11} /> Remove
              </>
            )}
          </button>
        )}
      </div>
    </li>
  );
}

function PlanList({
  side,
  title,
  hint,
  droppable,
  highlight,
  children,
  count,
  toolbar,
}: {
  side: PlanSide;
  title: string;
  hint?: string;
  droppable: boolean;
  highlight: boolean;
  children: React.ReactNode;
  count: number;
  toolbar?: React.ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: side, disabled: !droppable });
  return (
    <section
      ref={setNodeRef}
      aria-label={title}
      className={`flex min-h-48 flex-col gap-2 rounded-lg border p-3 ${
        isOver && highlight ? "border-canopy-500 bg-canopy-50" : "border-slate-200 bg-slate-50"
      }`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-700">
          {title} <span className="font-normal text-slate-400">({count})</span>
        </h3>
        {hint && <span className="text-xs text-slate-400">{hint}</span>}
      </div>
      {toolbar}
      <ul className="flex max-h-[32rem] flex-col gap-1.5 overflow-y-auto">{children}</ul>
    </section>
  );
}

/** The planning view of one sprint (USER_FLOWS §C11.3): the team's backlog beside the sprint,
 *  tasks moved between them by drag (mouse, touch, keyboard) or their Add / Remove buttons,
 *  the capacity bar, and the sprint's lifecycle — edit, start, complete (asking where
 *  unfinished work goes), reopen, delete. A sprint mirrored from a tracker is read-only. */
export default function SprintPlanning({
  teamId,
  sprint,
  sprints,
  backlog,
  backlogError,
  maySprint,
  names,
  projectKeys,
  today,
  onDeleted,
  onReport,
}: {
  teamId: number;
  sprint: Sprint;
  sprints: Sprint[];
  backlog: Board | undefined;
  backlogError: unknown;
  maySprint: boolean;
  names: ReadonlyMap<number, string>;
  projectKeys: ReadonlyMap<number, string>;
  today: string;
  onDeleted: () => void;
  onReport: (sprintId: number) => void;
}) {
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: ["sprint", sprint.id],
    queryFn: () => api.get<SprintDetail>(`/sprints/${sprint.id}`),
  });
  const [pending, setPending] = useState<Record<number, PlanSide>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [panel, setPanel] = useState<"edit" | "complete" | null>(null);
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<number | null>(null);

  const owned = sprint.owner === CANOPY_OWNER;
  const membershipOpen = maySprint && sprint.state !== "completed";
  const unit = detail.data?.unit ?? sprint.unit;

  const backlogItems = useMemo<PlanItem[]>(
    () =>
      (backlog?.lanes ?? []).flatMap((lane) =>
        lane.tasks.map((c) => ({
          id: c.id,
          key: c.key,
          name: c.name,
          projectId: c.project_id,
          assignee: c.assignee_engineer_id,
          status: c.status,
          points: c.story_points,
          days: null,
          closed: isClosedCategory(c.status_category),
        })),
      ),
    [backlog],
  );
  const sprintItems = useMemo(() => (detail.data?.tasks ?? []).map(fromTask), [detail.data]);
  const lists = planLists(backlogItems, sprintItems, pending);
  const needle = query.trim().toLowerCase();
  const shownBacklog = needle
    ? lists.backlog.filter((i) => `${i.key ?? ""} ${i.name}`.toLowerCase().includes(needle))
    : lists.backlog;
  const byId = new Map([...backlogItems, ...sprintItems].map((i) => [i.id, i] as const));

  const membership = useMutation({
    mutationFn: async ({ id, to }: { id: number; to: PlanSide }): Promise<void> => {
      if (to === "sprint") await api.post<Sprint>(`/sprints/${sprint.id}/tasks`, { task_ids: [id] });
      else await api.del(`/sprints/${sprint.id}/tasks/${id}`);
    },
    onError: (err) => setMessage(trackingFailure(err).message),
    onSettled: async (_res, _err, { id }) => {
      await invalidateSprintData(qc, teamId);
      setPending((p) => {
        const next = { ...p };
        delete next[id];
        return next;
      });
    },
  });
  const move = (item: PlanItem, to: PlanSide) => {
    setMessage(null);
    setPending((p) => ({ ...p, [item.id]: to }));
    membership.mutate({ id: item.id, to });
  };

  const lifecycle = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSuccess: () => {
      setPanel(null);
      setMessage(null);
    },
    onError: (err) => setMessage(trackingFailure(err).message),
    onSettled: () => invalidateSprintData(qc, teamId),
  });

  const sensors = useSensors(
    useSensor(MouseAndPenSensor, { activationConstraint: MOUSE_ACTIVATION }),
    useSensor(TouchSensor, { activationConstraint: TOUCH_ACTIVATION }),
    useSensor(KeyboardSensor, { coordinateGetter: listKeyboardCoordinates }),
  );
  const sideOf = (id: number): PlanSide =>
    lists.sprint.some((i) => i.id === id) ? "sprint" : "backlog";
  const handleDragStart = ({ active }: DragStartEvent) => {
    setMessage(null);
    setActiveId(Number(active.id));
  };
  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    setActiveId(null);
    const item = byId.get(Number(active.id));
    if (!item || !over) return;
    const to = over.id as PlanSide;
    if (to !== sideOf(item.id)) move(item, to);
  };
  const listName = (side: PlanSide) => (side === "sprint" ? sprint.name : "the backlog");
  const announcements: Announcements = {
    onDragStart: ({ active }) => {
      const item = byId.get(Number(active.id));
      const side = sideOf(Number(active.id));
      return `Picked up ${item ? cardLabel(item) : "the task"} from ${listName(side)}. Use the left and right arrow keys to move it to the other list.`;
    },
    onDragOver: ({ over }) => (over ? `Over ${listName(over.id as PlanSide)}.` : "Not over a list."),
    onDragEnd: ({ active, over }) => {
      const item = byId.get(Number(active.id));
      return over
        ? `${item ? cardLabel(item) : "The task"} was dropped in ${listName(over.id as PlanSide)}.`
        : "Dropped outside the lists; nothing changed.";
    },
    onDragCancel: () => "Moving was cancelled; nothing changed.",
  };

  const open = sprintItems.filter((i) => !i.closed).length;
  const left = timeLeftLabel(sprint, today);
  const activeItem = activeId !== null ? byId.get(activeId) : undefined;

  return (
    <div className="space-y-4">
      <header className="space-y-2 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold text-slate-800">{sprint.name}</h2>
          <span
            className={`rounded px-1.5 py-0.5 text-xs font-medium ${
              sprint.state === "active"
                ? "bg-canopy-50 text-canopy-700"
                : sprint.state === "planned"
                  ? "bg-slate-100 text-slate-600"
                  : "bg-slate-100 text-slate-400"
            }`}
          >
            {STATE_LABELS[sprint.state]}
          </span>
          {!owned && (
            <span className="inline-flex items-center gap-1 rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700">
              <Icon name="lock" size={11} />
              Mirrored from {trackerName(sprint.owner)} — read-only
            </span>
          )}
          <span className="text-sm text-slate-500">
            {formatSprintDates(sprint)}
            {left && <> · {left}</>}
          </span>
          <span className="ml-auto flex flex-wrap items-center gap-2">
            {maySprint && owned && sprint.state !== "completed" && (
              <button
                type="button"
                onClick={() => setPanel(panel === "edit" ? null : "edit")}
                className="rounded border border-slate-300 px-3 py-1 text-sm text-slate-600 hover:bg-slate-50"
              >
                Edit
              </button>
            )}
            {maySprint && owned && sprint.state === "planned" && (
              <>
                <button
                  type="button"
                  disabled={lifecycle.isPending}
                  onClick={() => lifecycle.mutate(() => api.post(`/sprints/${sprint.id}/start`))}
                  className="rounded bg-canopy-700 px-3 py-1 text-sm font-medium text-white hover:bg-canopy-500 disabled:opacity-50"
                >
                  Start sprint
                </button>
                <button
                  type="button"
                  disabled={lifecycle.isPending}
                  onClick={() => {
                    if (window.confirm(`Delete ${sprint.name}? Its tasks go back to the backlog.`)) {
                      lifecycle.mutate(async () => {
                        await api.del(`/sprints/${sprint.id}`);
                        onDeleted();
                      });
                    }
                  }}
                  className="text-sm text-slate-400 hover:text-red-600"
                >
                  Delete
                </button>
              </>
            )}
            {maySprint && owned && sprint.state === "active" && (
              <button
                type="button"
                onClick={() => setPanel(panel === "complete" ? null : "complete")}
                className="rounded bg-canopy-700 px-3 py-1 text-sm font-medium text-white hover:bg-canopy-500"
              >
                Complete sprint
              </button>
            )}
            {maySprint && owned && sprint.state === "completed" && (
              <button
                type="button"
                disabled={lifecycle.isPending}
                onClick={() => lifecycle.mutate(() => api.post(`/sprints/${sprint.id}/reopen`))}
                className="rounded border border-slate-300 px-3 py-1 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
              >
                Reopen
              </button>
            )}
            {sprint.state !== "planned" && (
              <button
                type="button"
                onClick={() => onReport(sprint.id)}
                className="rounded border border-canopy-500 px-3 py-1 text-sm font-medium text-canopy-700 hover:bg-canopy-50"
              >
                Sprint report
              </button>
            )}
          </span>
        </div>
        {sprint.goal && <p className="text-sm text-slate-600">Goal: {sprint.goal}</p>}
        <p className="text-xs text-slate-400">
          {sprint.done_count}/{sprint.task_count} tasks done ·{" "}
          {formatEstimate(sprint.done, sprint.unit)} of {formatEstimate(sprint.scope, sprint.unit)}
          {sprint.committed != null && <> · committed {formatEstimate(sprint.committed, sprint.unit)}</>}
        </p>

        {panel === "edit" && (
          <EditSprintForm
            sprint={sprint}
            busy={lifecycle.isPending}
            onCancel={() => setPanel(null)}
            onSave={(body) => lifecycle.mutate(() => api.patch(`/sprints/${sprint.id}`, body))}
          />
        )}
        {panel === "complete" && (
          <CompleteSprintForm
            sprint={sprint}
            open={open}
            targets={carryOverTargets(sprints, sprint)}
            busy={lifecycle.isPending}
            onCancel={() => setPanel(null)}
            onComplete={(body) => lifecycle.mutate(() => api.post(`/sprints/${sprint.id}/complete`, body))}
          />
        )}
        {message && (
          <p role="alert" className="rounded border border-red-200 bg-red-50 px-3 py-1.5 text-sm text-red-700">
            {message}
          </p>
        )}
      </header>

      {detail.data?.capacity && sprint.state !== "completed" && (
        <CapacityBar capacity={detail.data.capacity} />
      )}

      <DndContext
        sensors={sensors}
        collisionDetection={collisions}
        accessibility={{
          announcements,
          screenReaderInstructions: {
            draggable:
              "Press space or enter on a task's drag handle to pick it up, the left or right arrow key to move it to the other list, and space or enter to drop it. Each task also has an Add or Remove button.",
          },
        }}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onDragCancel={() => setActiveId(null)}
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <PlanList
            side="backlog"
            title="Backlog"
            hint="Open work in no live sprint"
            droppable={membershipOpen}
            highlight={activeId !== null && sideOf(activeId) === "sprint"}
            count={lists.backlog.length}
            toolbar={
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter the backlog…"
                aria-label="Filter the backlog"
                className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm"
              />
            }
          >
            {backlogError ? (
              <li className="text-sm text-red-700">{trackingFailure(backlogError).message}</li>
            ) : !backlog ? (
              <li className="text-sm text-slate-400">Loading the backlog…</li>
            ) : shownBacklog.length === 0 ? (
              <li className="py-4 text-center text-sm text-slate-400">
                {needle ? "No matching tasks." : "The backlog is empty."}
              </li>
            ) : (
              shownBacklog.map((item) => (
                <PlanRow
                  key={item.id}
                  item={item}
                  unit={unit}
                  names={names}
                  projectKeys={projectKeys}
                  side="backlog"
                  canMove={membershipOpen}
                  onMove={() => move(item, "sprint")}
                  sprintName={sprint.name}
                />
              ))
            )}
          </PlanList>
          <PlanList
            side="sprint"
            title={sprint.name}
            hint={sprint.state === "completed" ? "Completed — read-only" : undefined}
            droppable={membershipOpen}
            highlight={activeId !== null && sideOf(activeId) === "backlog"}
            count={lists.sprint.length}
          >
            {!detail.data ? (
              <li className="text-sm text-slate-400">Loading the sprint…</li>
            ) : lists.sprint.length === 0 ? (
              <li className="py-4 text-center text-sm text-slate-400">
                {membershipOpen ? "Drag tasks here, or use Add on a backlog task." : "No tasks."}
              </li>
            ) : (
              lists.sprint.map((item) => (
                <PlanRow
                  key={item.id}
                  item={item}
                  unit={unit}
                  names={names}
                  projectKeys={projectKeys}
                  side="sprint"
                  canMove={membershipOpen}
                  onMove={() => move(item, "backlog")}
                  sprintName={sprint.name}
                />
              ))
            )}
          </PlanList>
        </div>
        <DragOverlay>
          {activeItem ? (
            <PlanRow
              item={activeItem}
              unit={unit}
              names={names}
              projectKeys={projectKeys}
              side={sideOf(activeItem.id)}
              canMove={false}
              sprintName={sprint.name}
              overlay
            />
          ) : null}
        </DragOverlay>
      </DndContext>
      {Object.keys(pending).length > 0 && (
        <p role="status" className="text-xs text-slate-400">
          Saving {Object.keys(pending).length} move{Object.keys(pending).length === 1 ? "" : "s"}…
        </p>
      )}
    </div>
  );
}

function EditSprintForm({
  sprint,
  busy,
  onCancel,
  onSave,
}: {
  sprint: Sprint;
  busy: boolean;
  onCancel: () => void;
  onSave: (body: SprintUpdate) => void;
}) {
  const [name, setName] = useState(sprint.name);
  const [goal, setGoal] = useState(sprint.goal ?? "");
  const [start, setStart] = useState(sprint.start_date ?? "");
  const [end, setEnd] = useState(sprint.end_date ?? "");
  const body: SprintUpdate = {};
  if (name.trim() && name.trim() !== sprint.name) body.name = name.trim();
  if ((goal.trim() || null) !== sprint.goal) body.goal = goal.trim() || null;
  if ((start || null) !== sprint.start_date) body.start_date = start || null;
  if ((end || null) !== sprint.end_date) body.end_date = end || null;
  const badDates = Boolean(start && end && end < start);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (Object.keys(body).length > 0 && !badDates) onSave(body);
      }}
      className="grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 sm:grid-cols-2"
    >
      <label className="text-xs text-slate-500">
        Name
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />
      </label>
      <label className="text-xs text-slate-500">
        Goal
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="What the sprint should achieve"
          className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />
      </label>
      <label className="text-xs text-slate-500">
        Starts
        <input
          type="date"
          value={start}
          onChange={(e) => setStart(e.target.value)}
          className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />
      </label>
      <label className="text-xs text-slate-500">
        Ends
        <input
          type="date"
          value={end}
          onChange={(e) => setEnd(e.target.value)}
          aria-invalid={badDates}
          className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />
      </label>
      {badDates && <p className="text-xs text-red-700 sm:col-span-2">The end is before the start.</p>}
      <div className="flex items-center gap-2 sm:col-span-2">
        <button
          type="submit"
          disabled={busy || badDates || Object.keys(body).length === 0}
          className="rounded bg-canopy-700 px-3 py-1 text-sm font-medium text-white disabled:opacity-50"
        >
          Save
        </button>
        <button type="button" onClick={onCancel} className="text-sm text-slate-500">
          Cancel
        </button>
      </div>
    </form>
  );
}

function CompleteSprintForm({
  sprint,
  open,
  targets,
  busy,
  onCancel,
  onComplete,
}: {
  sprint: Sprint;
  open: number;
  targets: Sprint[];
  busy: boolean;
  onCancel: () => void;
  onComplete: (body: { carry_over: "next" | "backlog"; next_sprint_id?: number }) => void;
}) {
  const [to, setTo] = useState<number | "backlog">(targets[0]?.id ?? "backlog");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onComplete(to === "backlog" ? { carry_over: "backlog" } : { carry_over: "next", next_sprint_id: to });
      }}
      className="space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm"
    >
      <p className="font-medium text-slate-700">
        Complete {sprint.name}?{" "}
        <span className="font-normal text-slate-500">
          {open === 0
            ? "Everything in it is finished."
            : `${open} unfinished task${open === 1 ? "" : "s"} — where should ${open === 1 ? "it" : "they"} go?`}
        </span>
      </p>
      {open > 0 && (
        <fieldset className="space-y-1">
          <legend className="sr-only">Where unfinished work goes</legend>
          {targets.map((s) => (
            <label key={s.id} className="flex items-center gap-2">
              <input type="radio" name="carry-over" checked={to === s.id} onChange={() => setTo(s.id)} />
              {s.name}
              <span className="text-xs text-slate-400">
                {STATE_LABELS[s.state].toLowerCase()} · {formatSprintDates(s)}
              </span>
            </label>
          ))}
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="carry-over"
              checked={to === "backlog"}
              onChange={() => setTo("backlog")}
            />
            Back to the backlog
          </label>
        </fieldset>
      )}
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-canopy-700 px-3 py-1 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "Completing…" : "Complete sprint"}
        </button>
        <button type="button" onClick={onCancel} className="text-sm text-slate-500">
          Cancel
        </button>
      </div>
    </form>
  );
}
