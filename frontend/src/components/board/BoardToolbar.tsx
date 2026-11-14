import type { BoardViewer } from "../../api/types";
import {
  NO_FILTER,
  isFiltering,
  type Board,
  type CardFilter,
  type OwnerFilter,
  type SwimlaneMode,
} from "../../lib/board";

const SWIMLANE_LABELS: Record<SwimlaneMode, string> = {
  none: "None",
  owner: "By owner",
  parent: "By phase",
};

function ownerValue(owner: OwnerFilter): string {
  return typeof owner === "number" ? String(owner) : owner;
}

function parseOwner(value: string): OwnerFilter {
  return value === "all" || value === "none" ? value : Number(value);
}

/** The board's controls: owner / tag / blocked / aging filters, swimlanes, the flow signals
 *  (cycle-time P85, aging count) and — for planners — "Edit columns". */
export default function BoardToolbar({
  board,
  viewer,
  filter,
  onFilterChange,
  swimlanes,
  onSwimlanesChange,
  swimlaneModes,
  owners,
  tags,
  shownCount,
  totalCount,
  onEditColumns,
}: {
  board: Board;
  viewer: BoardViewer | null;
  filter: CardFilter;
  onFilterChange: (filter: CardFilter) => void;
  swimlanes: SwimlaneMode;
  onSwimlanesChange: (mode: SwimlaneMode) => void;
  swimlaneModes: SwimlaneMode[];
  /** Owners present on the board, as [engineer id, name], sorted by name. */
  owners: [number, string][];
  tags: string[];
  shownCount: number;
  totalCount: number;
  onEditColumns?: () => void;
}) {
  const filtering = isFiltering(filter);
  const readOnlyReason =
    viewer && !viewer.native_enabled
      ? "canopy-owned status is turned off in this workspace, so the board is read-only — statuses come from connected trackers."
      : viewer && !viewer.can_plan && viewer.engineer_id == null
        ? "You can view this board but not move its cards."
        : null;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-slate-500">
        <label className="flex items-center gap-1">
          Owner
          <select
            value={ownerValue(filter.owner)}
            onChange={(e) => onFilterChange({ ...filter, owner: parseOwner(e.target.value) })}
            className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
          >
            <option value="all">Everyone</option>
            <option value="none">Unassigned</option>
            {owners.map(([id, name]) => (
              <option key={id} value={String(id)}>
                {name}
              </option>
            ))}
          </select>
        </label>
        {tags.length > 0 && (
          <label className="flex items-center gap-1">
            Tag
            <select
              value={filter.tag ?? ""}
              onChange={(e) => onFilterChange({ ...filter, tag: e.target.value || null })}
              className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
            >
              <option value="">Any tag</option>
              {tags.map((tag) => (
                <option key={tag} value={tag}>
                  {tag}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={filter.blocked}
            onChange={(e) => onFilterChange({ ...filter, blocked: e.target.checked })}
          />
          Blocked
        </label>
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={filter.aging}
            onChange={(e) => onFilterChange({ ...filter, aging: e.target.checked })}
          />
          Aging
        </label>
        <label className="flex items-center gap-1">
          Swimlanes
          <select
            value={swimlanes}
            onChange={(e) => onSwimlanesChange(e.target.value as SwimlaneMode)}
            className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
          >
            {swimlaneModes.map((mode) => (
              <option key={mode} value={mode}>
                {SWIMLANE_LABELS[mode]}
              </option>
            ))}
          </select>
        </label>
        {filtering && (
          <span className="flex items-center gap-2 text-xs">
            <span role="status">
              {shownCount} of {totalCount} cards
            </span>
            <button
              type="button"
              onClick={() => onFilterChange(NO_FILTER)}
              className="font-medium text-canopy-700 hover:underline"
            >
              Clear filters
            </button>
          </span>
        )}

        <span className="ml-auto flex items-center gap-3">
          <span title="85% of recent work finished within this many days of starting">
            cycle-time P85:{" "}
            {board.cycle_time_p85_days != null ? `${board.cycle_time_p85_days}d` : "—"}
          </span>
          {board.aging_count > 0 && (
            <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
              {board.aging_count} aging
            </span>
          )}
          {onEditColumns && (
            <button
              type="button"
              onClick={onEditColumns}
              className="rounded border border-canopy-500 px-3 py-1 text-sm font-medium text-canopy-700 hover:bg-canopy-50"
            >
              Edit columns
            </button>
          )}
        </span>
      </div>

      {(board.mode === "mirrored" || readOnlyReason) && (
        <p className="text-xs text-slate-400">
          {board.mode === "mirrored" &&
            "Mirrored project: a locked card’s status belongs to its tracker and changes there; canopy-only cards move here. "}
          {readOnlyReason}
        </p>
      )}
    </div>
  );
}
