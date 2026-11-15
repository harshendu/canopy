import type { ReactNode } from "react";
import { useDroppable } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";

import {
  CATEGORY_LABELS,
  NO_STATUS,
  isClosedCategory,
  laneCount,
  limitWip,
  wipBeyondBoard,
  type Lane,
} from "../../lib/board";
import { Icon } from "../icons";

/** What kind of column this is, under its name. */
function columnHint(lane: Lane): string {
  if (lane.status === NO_STATUS) return "no status yet";
  const category = lane.category ? CATEGORY_LABELS[lane.category] : null;
  if (!lane.in_workflow) return category ? `${category} · not in workflow` : "not in workflow";
  // The limit counts cards this board doesn't show (other projects, sprints or pods).
  const shared = lane.wip_limit != null && wipBeyondBoard(lane) ? " · WIP counts the team" : "";
  return `${category ?? ""}${shared}`;
}

function countTitle(lane: Lane): string {
  if (isClosedCategory(lane.category) || (lane.category == null && lane.is_done)) {
    return `${lane.tasks.length} card${lane.tasks.length === 1 ? "" : "s"}`;
  }
  if (lane.wip_limit == null) return `${lane.wip} open, no WIP limit`;
  const scope = wipBeyondBoard(lane)
    ? ` across the team’s projects (${lane.wip} on this board)`
    : "";
  return `${limitWip(lane)} open${scope} of a WIP limit of ${lane.wip_limit}${
    lane.over_limit ? " — over the limit" : ""
  }`;
}

/** A column's header: name, category hint, WIP against its limit (red when over) or the card
 *  count of a done/cancelled column, and the collapse toggle. */
export function BoardColumnHeader({
  lane,
  collapsed,
  onToggle,
}: {
  lane: Lane;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const tone = lane.over_limit
    ? "border-red-400 bg-red-50 text-red-700"
    : "border-slate-200 bg-slate-50 text-slate-700";
  const count = laneCount(lane);

  if (collapsed) {
    return (
      <div className={`flex flex-col items-center gap-0.5 rounded-t-md border-b-2 py-2 ${tone}`}>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={false}
          aria-label={`Show the ${lane.status} column (${countTitle(lane)})`}
          title={`Show ${lane.status}`}
          className="rounded p-0.5 text-slate-400 hover:bg-white hover:text-slate-700"
        >
          <Icon name="chevron-right" size={14} />
        </button>
        <span className="text-xs font-semibold tabular-nums" aria-hidden>
          {count}
        </span>
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-1.5 rounded-t-md border-b-2 px-2 py-2 ${tone}`}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded
        aria-label={`Collapse the ${lane.status} column`}
        title="Collapse"
        className="shrink-0 rounded p-0.5 text-slate-400 hover:bg-white hover:text-slate-700"
      >
        <Icon name="chevron-down" size={14} />
      </button>
      <div className="min-w-0 flex-1">
        <h3 className="flex items-center gap-1 truncate text-sm font-medium" title={lane.status}>
          <span className="truncate">{lane.status}</span>
          {lane.worked_by && (
            <span
              title={
                lane.worked_by === "human"
                  ? "A decision column: a person decides what happens next"
                  : `Agent sessions work this column as ${lane.worked_by}`
              }
              className="shrink-0 rounded bg-violet-50 px-1 text-[10px] font-normal text-violet-700"
            >
              {lane.worked_by === "human" ? "decision" : lane.worked_by}
            </span>
          )}
        </h3>
        <div className={`truncate text-[11px] ${lane.over_limit ? "text-red-600" : "text-slate-400"}`}>
          {columnHint(lane)}
        </div>
      </div>
      <span title={countTitle(lane)} className="shrink-0 text-xs font-semibold tabular-nums">
        {count}
        <span className="sr-only"> — {countTitle(lane)}</span>
      </span>
    </div>
  );
}

/** One column in one swimlane: a drop zone holding its cards in order. A collapsed column is
 *  a narrow drop zone only (a card dropped on it goes to the bottom). */
export function BoardColumnCell({
  id,
  lane,
  label,
  collapsed,
  cardIds,
  droppableDisabled,
  highlighted,
  dimmed,
  emptyText,
  compact = false,
  children,
  footer,
}: {
  /** The drop container's id (see `cellId`). */
  id: string;
  lane: Lane;
  /** How screen readers name this list ("In Progress", or "In Progress — Ann"). */
  label: string;
  collapsed: boolean;
  cardIds: number[];
  droppableDisabled: boolean;
  /** The card being dragged is over this cell. */
  highlighted: boolean;
  /** A card is being dragged and can't land here. */
  dimmed: boolean;
  emptyText: string;
  /** A swimlane row: shorter, and an empty cell stays quiet (many rows × columns). */
  compact?: boolean;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id, disabled: droppableDisabled });
  // A collapsed column never takes the card into its list, so light it while hovered instead.
  const surface = highlighted || (collapsed && isOver)
    ? "bg-canopy-50 ring-2 ring-canopy-500"
    : dimmed
      ? "bg-slate-100/40 opacity-60"
      : "bg-slate-100/70";
  const height = compact ? "min-h-14" : "min-h-24";

  if (collapsed) {
    return (
      <div
        ref={setNodeRef}
        aria-label={`${label} (collapsed, ${cardIds.length} card${cardIds.length === 1 ? "" : "s"})`}
        className={`flex ${height} justify-center rounded-md pt-2 ${surface}`}
      >
        <span className="text-xs font-medium text-slate-400 [writing-mode:vertical-rl]" aria-hidden>
          {lane.status}
        </span>
      </div>
    );
  }

  return (
    <div ref={setNodeRef} className={`flex ${height} flex-col gap-2 rounded-md p-2 ${surface}`}>
      <SortableContext id={id} items={cardIds} strategy={verticalListSortingStrategy}>
        <ul aria-label={label} className="flex flex-col gap-2">
          {children}
        </ul>
      </SortableContext>
      {cardIds.length === 0 && !compact && (
        <p className="py-2 text-center text-xs text-slate-400">{emptyText}</p>
      )}
      {footer}
    </div>
  );
}
