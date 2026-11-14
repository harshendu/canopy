import type { BoardViewer, Sprint } from "../../api/types";
import {
  NO_FILTER,
  isFiltering,
  type Board,
  type CardFilter,
  type OwnerFilter,
  type SwimlaneMode,
} from "../../lib/board";
import {
  STATE_LABELS,
  formatSprintDates,
  parseSprintSelection,
  sprintParam,
  timeLeftLabel,
  type SprintSelection,
} from "../../lib/sprints";

const SWIMLANE_LABELS: Record<SwimlaneMode, string> = {
  none: "None",
  owner: "By owner",
  parent: "By phase",
  project: "By project",
};

const SELECT = "rounded border border-slate-300 bg-white px-2 py-1 text-sm";

function ownerValue(owner: OwnerFilter): string {
  return typeof owner === "number" ? String(owner) : owner;
}

function parseOwner(value: string): OwnerFilter {
  return value === "all" || value === "none" ? value : Number(value);
}

/** The board's sprint selector (teams that run sprints): what the board shows. */
export interface SprintControl {
  selection: SprintSelection;
  onChange: (selection: SprintSelection) => void;
  sprints: Sprint[];
  /** The one sprint the board shows, if any (named with its dates and goal). */
  shown: Sprint | null;
  today: string;
}

/** The board's controls: sprint, owner / tag / project / pod / blocked / aging filters,
 *  swimlanes, the flow signals (cycle-time P85, aging count) and — for those who may — "Edit
 *  columns". */
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
  projects = [],
  pods = [],
  sprint,
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
  /** Team board: its projects and pods, as [id, label]. */
  projects?: [number, string][];
  pods?: [number, string][];
  sprint?: SprintControl;
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
        {sprint && (
          <label className="flex items-center gap-1">
            Sprint
            <select
              value={sprintParam(sprint.selection)}
              onChange={(e) => sprint.onChange(parseSprintSelection(e.target.value))}
              className={`${SELECT} font-medium text-slate-700`}
            >
              <option value="active">Active sprint</option>
              <option value="backlog">Backlog</option>
              <option value="all">All work</option>
              {sprint.sprints.length > 0 && (
                <optgroup label="Sprints">
                  {sprint.sprints.map((s) => (
                    <option key={s.id} value={String(s.id)}>
                      {s.name} · {STATE_LABELS[s.state].toLowerCase()}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </label>
        )}
        <label className="flex items-center gap-1">
          Owner
          <select
            value={ownerValue(filter.owner)}
            onChange={(e) => onFilterChange({ ...filter, owner: parseOwner(e.target.value) })}
            className={SELECT}
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
        {projects.length > 1 && (
          <label className="flex items-center gap-1">
            Project
            <select
              value={filter.project ?? ""}
              onChange={(e) =>
                onFilterChange({ ...filter, project: e.target.value ? Number(e.target.value) : null })
              }
              className={SELECT}
            >
              <option value="">All projects</option>
              {projects.map(([id, label]) => (
                <option key={id} value={String(id)}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        )}
        {pods.length > 1 && (
          <label className="flex items-center gap-1">
            Pod
            <select
              value={filter.pod ?? ""}
              onChange={(e) =>
                onFilterChange({ ...filter, pod: e.target.value ? Number(e.target.value) : null })
              }
              className={SELECT}
            >
              <option value="">All pods</option>
              {pods.map(([id, label]) => (
                <option key={id} value={String(id)}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        )}
        {tags.length > 0 && (
          <label className="flex items-center gap-1">
            Tag
            <select
              value={filter.tag ?? ""}
              onChange={(e) => onFilterChange({ ...filter, tag: e.target.value || null })}
              className={SELECT}
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
            className={SELECT}
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

      {sprint && <SprintLine control={sprint} />}

      {(board.mode === "mirrored" || readOnlyReason) && (
        <p className="text-xs text-slate-400">
          {board.mode === "mirrored" &&
            "Mirrored work: a locked card’s status belongs to its tracker and changes there; canopy-only cards move here. "}
          {readOnlyReason}
        </p>
      )}
    </div>
  );
}

/** What the sprint selector shows, in a line: the sprint's name, dates, time left and goal. */
function SprintLine({ control }: { control: SprintControl }) {
  const { selection, shown, today } = control;
  if (shown) {
    const left = timeLeftLabel(shown, today);
    return (
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-canopy-500/30 bg-canopy-50 px-3 py-1.5 text-sm text-slate-700">
        <span className="font-semibold text-canopy-700">{shown.name}</span>
        <span className="text-xs text-slate-500">
          {STATE_LABELS[shown.state]} · {formatSprintDates(shown)}
          {left && <> · {left}</>}
          {shown.owner !== "canopy" && <> · mirrored from {shown.owner}</>}
        </span>
        {shown.goal && <span className="text-xs text-slate-600">Goal: {shown.goal}</span>}
      </p>
    );
  }
  const text =
    selection === "active"
      ? "No sprint is active — pick a sprint, or show the backlog or all work."
      : selection === "backlog"
        ? "Backlog: open work in no planned or active sprint."
        : null;
  return text ? <p className="text-xs text-slate-500">{text}</p> : null;
}
