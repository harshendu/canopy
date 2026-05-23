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

interface Geom {
  task: GanttTask;
  row: number;
  depth: number;
  x: number | null;
  w: number;
  bx: number | null; // baseline x
  bw: number; // baseline width
  y: number;
}

export default function GanttChart({ data }: { data: GanttResponse }) {
  const [dayW, setDayW] = useState(DEFAULT_DAY_W);
  const { geoms, width, height, gridDays, minDay } = useMemo(() => {
    const tasks = data.tasks;
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
      .flatMap((t) => [t.start_date, t.end_date])
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
      return { task, row, depth: depthOf(task), x, w, bx, bw, y: HEADER_H + row * ROW_H };
    });

    return {
      geoms,
      minDay: min,
      gridDays: Array.from({ length: span }, (_, i) => min + i).filter((_, i) => i % 7 === 0),
      width: LABEL_W + span * dayW + 20,
      height: HEADER_H + tasks.length * ROW_H + 10,
    };
  }, [data, dayW]);

  const geomById = new Map(geoms.map((g) => [g.task.id, g]));

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex items-center justify-end gap-1 border-b border-slate-100 px-3 py-1.5">
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
          const barFill = g.task.is_critical
            ? "fill-red-500"
            : isSummary
              ? "fill-slate-700"
              : "fill-canopy-500";
          const cy = g.y + ROW_H / 2;
          return (
            <g key={g.task.id}>
              <text
                x={8 + g.depth * 14}
                y={cy + 4}
                className={`fill-slate-700 ${isSummary ? "font-semibold" : ""}`}
              >
                {g.task.text.length > 30 ? g.task.text.slice(0, 29) + "…" : g.task.text}
              </text>

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
                </g>
              )}
            </g>
          );
        })}
      </svg>
      </div>
    </div>
  );
}
