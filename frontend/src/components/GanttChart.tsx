import { useMemo, useState } from "react";

import type { GanttResponse, GanttTask } from "../api/types";

const ROW_H = 38;
const DEFAULT_DAY_W = 26;
const MIN_DAY_W = 8;
const MAX_DAY_W = 60;
const LABEL_W = 240;
const HEADER_H = 28;

function parseDay(s: string): number {
  // Whole-day index since epoch (UTC), robust to timezones.
  const [y, m, d] = s.split("-").map(Number);
  return Math.floor(Date.UTC(y, m - 1, d) / 86_400_000);
}

function formatTick(dayIndex: number): string {
  const date = new Date(dayIndex * 86_400_000);
  return `${date.getUTCMonth() + 1}/${date.getUTCDate()}`;
}

/** "Dana Lee" -> "DL" (owner chip in the label column). */
export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("");
}

/** The task ids visible under an owner filter: matching tasks plus their WBS ancestors, so
 *  the tree above a person's work stays readable. Exported for unit tests. */
export function visibleTaskIds(tasks: GanttTask[], ownerFilter: string): Set<number> {
  const keep = new Set<number>();
  if (!ownerFilter) {
    for (const t of tasks) keep.add(t.id);
    return keep;
  }
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const matches = (t: GanttTask) =>
    ownerFilter === "none"
      ? t.assignee_engineer_id === null && t.type !== "summary"
      : t.assignee_engineer_id === Number(ownerFilter);
  for (const t of tasks) {
    if (!matches(t)) continue;
    keep.add(t.id);
    let cur = t.parent ? byId.get(t.parent) : undefined;
    const seen = new Set<number>([t.id]);
    while (cur && !seen.has(cur.id)) {
      seen.add(cur.id);
      keep.add(cur.id);
      cur = cur.parent ? byId.get(cur.parent) : undefined;
    }
  }
  return keep;
}

interface Geom {
  task: GanttTask;
  row: number;
  depth: number;
  x: number | null;
  w: number;
  bx: number | null; // baseline x
  bw: number; // baseline width
  dx: number | null; // deadline x
  y: number;
}

export default function GanttChart({
  data,
  onTaskClick,
}: {
  data: GanttResponse;
  onTaskClick?: (taskId: number) => void;
}) {
  const [dayW, setDayW] = useState(DEFAULT_DAY_W);
  const [ownerFilter, setOwnerFilter] = useState("");
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const toggleCollapse = (id: number) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const owners = useMemo(() => {
    const seen = new Map<number, string>();
    for (const t of data.tasks) {
      if (t.assignee_engineer_id !== null && t.assignee_name) {
        seen.set(t.assignee_engineer_id, t.assignee_name);
      }
    }
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [data]);
  const { geoms, width, height, gridDays, minDay, spanDays, hasChildren } = useMemo(() => {
    const visible = visibleTaskIds(data.tasks, ownerFilter);
    const ownerTasks = data.tasks.filter((t) => visible.has(t.id));
    const ownerById = new Map(ownerTasks.map((t) => [t.id, t]));
    // Which summary tasks have children (get a collapse chevron); and hide descendants of any
    // collapsed summary so a large WBS is navigable.
    const hasChildren = new Set<number>();
    for (const t of ownerTasks) if (t.parent != null) hasChildren.add(t.parent);
    const hiddenByCollapse = (t: GanttTask): boolean => {
      let cur = t.parent != null ? ownerById.get(t.parent) : undefined;
      const seen = new Set<number>([t.id]);
      while (cur && !seen.has(cur.id)) {
        if (collapsed.has(cur.id)) return true;
        seen.add(cur.id);
        cur = cur.parent != null ? ownerById.get(cur.parent) : undefined;
      }
      return false;
    };
    const tasks = ownerTasks.filter((t) => !hiddenByCollapse(t));
    const byId = new Map(tasks.map((t) => [t.id, t]));
    const depthOf = (t: GanttTask): number => {
      let depth = 0;
      let cur: GanttTask | undefined = t;
      const seen = new Set<number>();
      while (cur && cur.parent && byId.has(cur.parent) && !seen.has(cur.id)) {
        seen.add(cur.id);
        depth += 1;
        cur = byId.get(cur.parent);
      }
      return depth;
    };

    const days = tasks
      .flatMap((t) => [t.start_date, t.end_date, t.deadline])
      .filter((d): d is string => Boolean(d))
      .map(parseDay);
    const min = days.length ? Math.min(...days) : 0;
    const max = days.length ? Math.max(...days) : 0;
    const span = Math.max(max - min + 1, 1);

    const geoms: Geom[] = tasks.map((task, row) => {
      const startDay = task.start_date ? parseDay(task.start_date) : null;
      const endDay = task.end_date ? parseDay(task.end_date) : null;
      const x = startDay !== null ? (startDay - min) * dayW : null;
      const w =
        startDay !== null && endDay !== null ? Math.max((endDay - startDay) * dayW, 4) : 0;
      const bStart = task.baseline_start ? parseDay(task.baseline_start) : null;
      const bEnd = task.baseline_end ? parseDay(task.baseline_end) : null;
      const bx = bStart !== null ? (bStart - min) * dayW : null;
      const bw = bStart !== null && bEnd !== null ? Math.max((bEnd - bStart) * dayW, 4) : 0;
      const dDay = task.deadline ? parseDay(task.deadline) : null;
      const dx = dDay !== null ? (dDay - min) * dayW : null;
      return { task, row, depth: depthOf(task), x, w, bx, bw, dx, y: HEADER_H + row * ROW_H };
    });

    return {
      geoms,
      minDay: min,
      spanDays: span,
      hasChildren,
      gridDays: Array.from({ length: span }, (_, i) => min + i).filter((_, i) => i % 7 === 0),
      width: LABEL_W + span * dayW + 20,
      height: HEADER_H + tasks.length * ROW_H + 10,
    };
  }, [data, dayW, ownerFilter, collapsed]);

  // "Today" marker — only drawn when it falls within the charted window.
  const todayIndex = Math.floor(Date.now() / 86_400_000);
  const todayX =
    todayIndex >= minDay && todayIndex < minDay + spanDays
      ? LABEL_W + (todayIndex - minDay) * dayW
      : null;

  const geomById = new Map(geoms.map((g) => [g.task.id, g]));

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex items-center justify-end gap-1 border-b border-slate-100 px-3 py-1.5">
        <label className="mr-auto flex items-center gap-1.5 text-xs text-slate-400">
          owner
          <select
            value={ownerFilter}
            onChange={(e) => setOwnerFilter(e.target.value)}
            className="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-600"
          >
            <option value="">Everyone</option>
            <option value="none">Unassigned</option>
            {owners.map(([id, name]) => (
              <option key={id} value={String(id)}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <span className="mr-1 text-xs text-slate-400">zoom</span>
        <button
          onClick={() => setDayW((w) => Math.max(MIN_DAY_W, w - 6))}
          className="rounded border border-slate-300 px-2 text-sm text-slate-600"
          aria-label="Zoom out"
        >
          −
        </button>
        <button
          onClick={() => setDayW((w) => Math.min(MAX_DAY_W, w + 6))}
          className="rounded border border-slate-300 px-2 text-sm text-slate-600"
          aria-label="Zoom in"
        >
          +
        </button>
      </div>
      <div className="overflow-auto">
      <svg width={width} height={height} className="select-none text-xs">
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" className="fill-slate-400" />
          </marker>
        </defs>

        {/* week gridlines */}
        {gridDays.map((day) => {
          const x = LABEL_W + (day - minDay) * dayW;
          return (
            <g key={day}>
              <line x1={x} y1={HEADER_H} x2={x} y2={height} className="stroke-slate-100" />
              <text x={x + 2} y={18} className="fill-slate-400">
                {formatTick(day)}
              </text>
            </g>
          );
        })}
        <line x1={LABEL_W} y1={0} x2={LABEL_W} y2={height} className="stroke-slate-200" />

        {/* "today" marker */}
        {todayX !== null && (
          <g>
            <line
              x1={todayX}
              y1={HEADER_H}
              x2={todayX}
              y2={height}
              className="stroke-sky-400"
              strokeWidth={1.5}
              strokeDasharray="4 3"
            />
            <text x={todayX + 3} y={HEADER_H - 4} className="fill-sky-500 text-[10px]">
              today
            </text>
          </g>
        )}

        {/* dependency links */}
        {data.links.map((link) => {
          const from = geomById.get(link.source);
          const to = geomById.get(link.target);
          if (!from || !to || from.x === null || to.x === null) return null;
          const x1 = LABEL_W + from.x + from.w;
          const y1 = from.y + ROW_H / 2;
          const x2 = LABEL_W + to.x;
          const y2 = to.y + ROW_H / 2;
          const midX = Math.max(x1 + 8, x2 - 8);
          return (
            <path
              key={link.id}
              d={`M${x1},${y1} H${midX} V${y2} H${x2}`}
              className="fill-none stroke-slate-400"
              strokeWidth={1}
              markerEnd="url(#arrow)"
            />
          );
        })}

        {/* rows */}
        {geoms.map((g) => {
          const isMilestone = g.task.type === "milestone";
          const isSummary = g.task.type === "summary";
          const maxLabel = g.task.assignee_name ? 26 : 30;
          const barFill = g.task.is_critical
            ? "fill-red-500"
            : isSummary
              ? "fill-slate-700"
              : "fill-canopy-500";
          const cy = g.y + ROW_H / 2;
          const missedDeadline =
            g.dx !== null &&
            g.task.end_date != null &&
            g.task.deadline != null &&
            g.task.end_date > g.task.deadline;
          // Schedule variance vs baseline in calendar days, shown as a chip past the bar when it moved.
          // Guard g.x !== null first so it narrows for the x position (a nested closure wouldn't).
          const variance =
            !isSummary && g.x !== null && g.task.baseline_end != null && g.task.end_date != null
              ? {
                  days: parseDay(g.task.end_date) - parseDay(g.task.baseline_end),
                  x: LABEL_W + g.x + g.w + 4,
                }
              : null;
          return (
            <g
              key={g.task.id}
              onClick={onTaskClick ? () => onTaskClick(g.task.id) : undefined}
              className={onTaskClick ? "cursor-pointer" : undefined}
            >
              {onTaskClick && (
                <rect
                  x={0}
                  y={g.y}
                  width={width}
                  height={ROW_H}
                  className="fill-transparent hover:fill-slate-50"
                />
              )}
              {g.dx !== null && (
                <line
                  x1={LABEL_W + g.dx}
                  y1={g.y + 4}
                  x2={LABEL_W + g.dx}
                  y2={g.y + ROW_H - 4}
                  className={missedDeadline ? "stroke-red-600" : "stroke-amber-400"}
                  strokeWidth={2}
                  strokeDasharray="3 2"
                >
                  <title>deadline: {g.task.deadline}</title>
                </line>
              )}
              {/* Collapse/expand chevron on summary rows that have children. */}
              {isSummary && hasChildren.has(g.task.id) && (
                <text
                  x={g.depth * 14 + 2}
                  y={cy + 4}
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleCollapse(g.task.id);
                  }}
                  className="cursor-pointer fill-slate-400 hover:fill-slate-700"
                >
                  {collapsed.has(g.task.id) ? "▸" : "▾"}
                </text>
              )}
              <text
                x={(isSummary && hasChildren.has(g.task.id) ? 20 : 8) + g.depth * 14}
                y={cy + 4}
                className={`fill-slate-700 ${isSummary ? "font-semibold" : ""}`}
              >
                {g.task.text.length > maxLabel ? g.task.text.slice(0, maxLabel - 1) + "…" : g.task.text}
                <title>{g.task.text}</title>
              </text>
              {g.task.assignee_name && (
                <g>
                  <circle cx={LABEL_W - 18} cy={cy} r={9} className="fill-slate-200" />
                  <text
                    x={LABEL_W - 18}
                    y={cy + 3}
                    textAnchor="middle"
                    className="fill-slate-600 text-[9px] font-semibold"
                  >
                    {initials(g.task.assignee_name)}
                  </text>
                  <title>owner: {g.task.assignee_name}</title>
                </g>
              )}

              {g.x === null ? (
                <text x={LABEL_W + 6} y={cy + 4} className="fill-slate-300 italic">
                  unscheduled
                </text>
              ) : isMilestone ? (
                <rect
                  x={LABEL_W + g.x - 7}
                  y={cy - 7}
                  width={14}
                  height={14}
                  transform={`rotate(45 ${LABEL_W + g.x} ${cy})`}
                  className={g.task.is_critical ? "fill-red-500" : "fill-canopy-700"}
                />
              ) : (
                <g>
                  {g.bx !== null && !isSummary && (
                    <rect
                      x={LABEL_W + g.bx}
                      y={g.y + ROW_H - 7}
                      width={g.bw}
                      height={3}
                      rx={1}
                      className="fill-slate-300"
                    >
                      <title>
                        baseline: {g.task.baseline_start} → {g.task.baseline_end}
                      </title>
                    </rect>
                  )}
                  <rect
                    x={LABEL_W + g.x}
                    y={g.y + (isSummary ? 14 : 9)}
                    width={g.w}
                    height={isSummary ? 8 : ROW_H - 18}
                    rx={3}
                    className={barFill}
                  >
                    <title>
                      {g.task.text} — {g.task.start_date} → {g.task.end_date}
                      {g.task.is_critical ? " (critical)" : ` (float ${g.task.total_float}d)`}
                      {g.task.assignee_name ? ` — ${g.task.assignee_name}` : ""}
                    </title>
                  </rect>
                  {g.task.progress > 0 && !isSummary && (
                    <rect
                      x={LABEL_W + g.x}
                      y={g.y + 9}
                      width={g.w * Math.min(g.task.progress, 1)}
                      height={ROW_H - 18}
                      rx={3}
                      className="fill-black/20"
                    />
                  )}
                  {/* Schedule variance vs baseline, shown only when the finish moved. */}
                  {variance && variance.days !== 0 && (
                    <text
                      x={variance.x}
                      y={cy + 4}
                      className={
                        variance.days > 0
                          ? "fill-red-500 text-[10px]"
                          : "fill-canopy-600 text-[10px]"
                      }
                    >
                      {variance.days > 0 ? `+${variance.days}d` : `${variance.days}d`}
                      <title>
                        {variance.days > 0
                          ? `${variance.days} day(s) later`
                          : `${-variance.days} day(s) earlier`}{" "}
                        than baseline ({g.task.baseline_end})
                      </title>
                    </text>
                  )}
                </g>
              )}
            </g>
          );
        })}
      </svg>
      </div>
      {/* Legend — decode the bar colors / markers so the chart reads without tribal knowledge. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-slate-100 px-3 py-2 text-[11px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 rounded-sm bg-red-500" /> Critical path
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 rounded-sm bg-canopy-500" /> Task
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-4 rounded-sm bg-slate-700" /> Phase / summary
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-1 w-4 rounded-sm bg-slate-300" /> Baseline
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-0 border-l-2 border-dashed border-amber-400" />{" "}
          Deadline
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-0 border-l-2 border-dashed border-sky-400" /> Today
        </span>
        <span className="flex items-center gap-1.5">
          <span className="font-medium text-red-500">+d</span>/
          <span className="font-medium text-canopy-600">−d</span> vs baseline
        </span>
      </div>
    </div>
  );
}
