import type { PointerEvent, ReactNode, TouchEvent } from "react";
import { Link } from "react-router-dom";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { CANOPY_OWNER, cardLabel, isClosedCategory, trackerName, type Card } from "../../lib/board";
import {
  claimLooksStale,
  gateLabel,
  heartbeatPhrase,
  isParked,
  waitedPhrase,
} from "../../lib/execution";
import { initials } from "../GanttChart";
import { Icon } from "../icons";

/** Pressing a control inside a card must not start dragging the card. */
const keepOutOfDrag = {
  onPointerDown: (e: PointerEvent) => e.stopPropagation(),
  onTouchStart: (e: TouchEvent) => e.stopPropagation(),
};

function formatDay(iso: string): string {
  const day = new Date(`${iso}T00:00:00`);
  return Number.isNaN(day.getTime())
    ? iso
    : day.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export interface BoardCardProps {
  card: Card;
  ownerName?: string;
  /** Team board: the card's project (shown unless its key already names it). */
  projectLabel?: string;
  /** The card's own status when the board shows it in a column of another name. */
  statusNote?: string | null;
  /** Today as `YYYY-MM-DD`, to flag an overdue deadline. */
  today: string;
  /** The columns the "Move to…" menu offers (empty = no menu). */
  moveTargets?: string[];
  onMoveTo?: (status: string) => void;
  onOpen?: () => void;
}

/** A card's face: key, tracker lock, flags, name, tags, age, deadline, owner and the
 *  "Move to…" menu (the non-drag way to move it). Shared by the board and the drag overlay. */
export function BoardCardView({
  card,
  ownerName,
  projectLabel,
  statusNote,
  today,
  moveTargets = [],
  onMoveTo,
  onOpen,
  handle,
  overlay = false,
}: BoardCardProps & { handle?: ReactNode; overlay?: boolean }) {
  const mirrored = card.status_owner !== CANOPY_OWNER;
  const tracker = trackerName(card.status_owner);
  const overdue =
    card.deadline !== null && card.deadline < today && !isClosedCategory(card.status_category);
  const label = cardLabel(card);
  const showProject =
    projectLabel !== undefined && !(card.key ?? "").toUpperCase().startsWith(`${projectLabel.toUpperCase()}-`);

  return (
    <div
      className={`rounded-md border bg-white p-2 text-sm ${
        overlay ? "shadow-lg ring-1 ring-canopy-500" : "shadow-sm"
      } ${card.aging ? "border-amber-300" : "border-slate-200"} ${
        onOpen && !overlay ? "hover:border-canopy-500" : ""
      }`}
    >
      <div className="flex items-start gap-1">
        {handle}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1 text-[11px] leading-4">
            {showProject && (
              <span title="Project" className="rounded bg-slate-100 px-1 font-mono text-slate-500">
                {projectLabel}
              </span>
            )}
            {card.key && <span className="font-mono text-slate-500">{card.key}</span>}
            {mirrored &&
              (card.external_url ? (
                <a
                  href={card.external_url}
                  target="_blank"
                  rel="noreferrer"
                  {...keepOutOfDrag}
                  title={`Status owned by ${tracker} — open it there`}
                  aria-label={`Status owned by ${tracker} — open ${card.key ?? "the item"} in ${tracker}`}
                  className="inline-flex items-center gap-0.5 rounded bg-blue-50 px-1 font-medium text-blue-700 hover:underline"
                >
                  <Icon name="lock" size={10} />
                  {tracker}
                  <span aria-hidden>↗</span>
                </a>
              ) : (
                <span
                  title={`Status owned by ${tracker}`}
                  className="inline-flex items-center gap-0.5 rounded bg-blue-50 px-1 font-medium text-blue-700"
                >
                  <Icon name="lock" size={10} />
                  {tracker}
                </span>
              ))}
            {card.blocked && (
              <span className="rounded bg-red-100 px-1 font-medium text-red-700">blocked</span>
            )}
            {card.is_critical && (
              <span
                title="On the critical path"
                className="rounded border border-red-200 px-1 text-red-600"
              >
                critical
              </span>
            )}
            <AgentBadges card={card} overlay={overlay} />
          </div>

          {onOpen && !overlay ? (
            <button
              type="button"
              onClick={onOpen}
              className="mt-0.5 line-clamp-2 w-full text-left font-medium text-slate-800 hover:text-canopy-700"
            >
              {card.name}
            </button>
          ) : (
            <div className="mt-0.5 line-clamp-2 font-medium text-slate-800">{card.name}</div>
          )}

          {card.tags.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {card.tags.slice(0, 3).map((tag) => (
                <span key={tag} className="rounded bg-slate-100 px-1.5 text-[11px] text-slate-500">
                  {tag}
                </span>
              ))}
              {card.tags.length > 3 && (
                <span className="text-[11px] text-slate-400">+{card.tags.length - 3}</span>
              )}
            </div>
          )}

          {statusNote && (
            <div className="mt-1 text-[11px] text-slate-500">
              <span title="The card's own status — this column is the closest the board's columns have">
                status: {statusNote}
              </span>
            </div>
          )}

          <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-slate-400">
            <span title="Days in this status" className="tabular-nums">
              {card.age_days}d
            </span>
            {card.story_points != null && (
              <span
                title="Story points"
                className="rounded bg-slate-100 px-1 tabular-nums text-slate-600"
              >
                {card.story_points} pt{card.story_points === 1 ? "" : "s"}
              </span>
            )}
            {card.aging && (
              <span
                title="In this status longer than the team’s cycle-time P85"
                className="rounded bg-amber-100 px-1.5 text-amber-700"
              >
                aging
              </span>
            )}
            {card.deadline && (
              <span
                title={overdue ? "Past its deadline" : "Deadline"}
                className={overdue ? "font-medium text-red-600" : ""}
              >
                due {formatDay(card.deadline)}
              </span>
            )}
            <span className="ml-auto flex items-center gap-1.5">
              {!overlay && onMoveTo && moveTargets.length > 0 && (
                <select
                  value=""
                  onChange={(e) => {
                    if (e.target.value) onMoveTo(e.target.value);
                  }}
                  {...keepOutOfDrag}
                  aria-label={`Move ${label} to another column`}
                  className="max-w-[6.5rem] rounded border border-slate-200 bg-white px-1 py-0.5 text-[11px] text-slate-500 hover:border-canopy-500 focus:border-canopy-500 focus:outline-none"
                >
                  <option value="">Move to…</option>
                  {moveTargets.map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
              )}
              {ownerName && (
                <span
                  title={ownerName}
                  aria-label={`Owner: ${ownerName}`}
                  className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-200 text-[10px] font-semibold text-slate-600"
                >
                  {initials(ownerName)}
                </span>
              )}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Agent work on a card (docs/AGENT_EXECUTION.md §16): parked, a gate waiting on a person (a
 *  link to decide it), the session working it, or simply delegated. */
function AgentBadges({ card, overlay }: { card: Card; overlay: boolean }) {
  if (card.awaiting_move && !card.gate && !card.claim) {
    return (
      <span
        title={`canopy cleared this ticket to move to ${card.awaiting_move} — move it in ${trackerName(
          card.status_owner,
        )} (canopy never changes a tracker's status)`}
        className="rounded bg-sky-100 px-1 font-medium text-sky-800"
      >
        → {card.awaiting_move}
      </span>
    );
  }
  if (card.gate) {
    const parked = card.parked || isParked(card.gate);
    const text = `${parked ? "parked" : gateLabel(card.gate).toLowerCase()} · ${waitedPhrase(
      card.gate.age_hours,
    )}`;
    const tone = parked ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-800";
    const title = `${card.gate.title} — waiting on a person`;
    return overlay ? (
      <span className={`rounded px-1 font-medium ${tone}`}>{text}</span>
    ) : (
      <Link
        to={`/reviews/gates/${card.gate.id}`}
        {...keepOutOfDrag}
        title={title}
        className={`rounded px-1 font-medium hover:underline ${tone}`}
      >
        {text}
      </Link>
    );
  }
  if (card.claim) {
    const stale = claimLooksStale(card.claim.heartbeat_age_s);
    return (
      <span
        title={`${card.claim.label ?? "An agent session"} is working on it as ${
          card.claim.role
        } — last checked in ${heartbeatPhrase(card.claim.heartbeat_age_s)}`}
        className={`inline-flex items-center gap-0.5 rounded px-1 font-medium ${
          stale ? "bg-amber-50 text-amber-700" : "bg-violet-100 text-violet-700"
        }`}
      >
        <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${stale ? "bg-amber-500" : "bg-violet-500"}`} />
        {card.claim.role}
      </span>
    );
  }
  if (card.delegation === "agent") {
    return (
      <span
        title="Delegated to agents — offered to agent sessions while the project's intake is on"
        className="rounded border border-violet-200 px-1 text-violet-600"
      >
        agent
      </span>
    );
  }
  return null;
}

/** A card on the board: sortable within its column and draggable across columns. The whole
 *  card answers a mouse or a press-and-hold; the keyboard picks it up from its grip handle. */
export function SortableBoardCard({
  draggable,
  droppableDisabled,
  ...props
}: BoardCardProps & {
  /** The viewer may move this card at all (shows the handle). */
  draggable: boolean;
  /** Not a place the card being dragged may land. */
  droppableDisabled: boolean;
}) {
  const { card } = props;
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: card.id,
    disabled: { draggable: !draggable, droppable: droppableDisabled },
    attributes: { roleDescription: "draggable card" },
  });

  const handle = draggable ? (
    <button
      type="button"
      ref={setActivatorNodeRef}
      {...attributes}
      aria-label={`Drag ${cardLabel(card)}`}
      className="-ml-1 mt-px flex h-5 w-4 shrink-0 cursor-grab items-center justify-center rounded text-slate-300 hover:bg-slate-100 hover:text-slate-500 focus-visible:text-slate-600 focus-visible:outline-2 focus-visible:outline-canopy-500 active:cursor-grabbing"
    >
      <Icon name="grip" size={14} />
    </button>
  ) : null;

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      {...(draggable ? listeners : {})}
      className={`list-none ${draggable ? "touch-manipulation select-none" : ""} ${
        isDragging ? "opacity-40" : ""
      }`}
    >
      <BoardCardView {...props} handle={handle} />
    </li>
  );
}
