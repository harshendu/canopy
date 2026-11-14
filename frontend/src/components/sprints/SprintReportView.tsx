import type { ReactNode } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../../api/client";
import type { EstimateUnit, Sprint, SprintReport, Velocity } from "../../api/types";
import {
  STATE_LABELS,
  burndownSeries,
  defaultReportSprint,
  formatDay,
  formatEstimate,
  formatSprintDates,
  percent,
  velocitySeries,
} from "../../lib/sprints";
import { QueryError } from "../QueryError";

// Two series per chart: the first two slots of a categorical palette validated on the white
// card surface (CVD and normal-vision separation, 3:1 contrast). Guides (the ideal line, the
// mean) are neutral; grid and axes are solid hairlines; text stays in text colors.
const SERIES_1 = "#2a78d6";
const SERIES_2 = "#eb6834";
const GUIDE = "#94a3b8";
const GRID = "#e2e8f0";
const AXIS_TEXT = "#64748b";
const TEXT = "#334155";

const legendText = (value: string): ReactNode => <span style={{ color: TEXT }}>{value}</span>;
const tick = { fill: AXIS_TEXT, fontSize: 12 };

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2">
      <dt className="text-xs uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="text-lg font-semibold text-slate-800">{value}</dd>
      {hint && <dd className="text-[11px] text-slate-400">{hint}</dd>}
    </div>
  );
}

/** The numbers behind a chart, for reading without the chart (or a screen reader). */
function DataTable({ caption, head, rows }: { caption: string; head: string[]; rows: ReactNode[][] }) {
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">
        Show the numbers
      </summary>
      <table className="mt-2 w-full text-left text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead className="text-slate-400">
          <tr>
            {head.map((h) => (
              <th key={h} scope="col" className="py-1 pr-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="tabular-nums text-slate-600">
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-slate-100">
              {row.map((cell, j) => (
                <td key={j} className="py-1 pr-3">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

const valueIn = (unit: EstimateUnit | string) => (value: unknown) =>
  typeof value === "number" ? formatEstimate(value, unit) : String(value);

/** A sprint's report (burndown, commitment vs completed, scope change, carry-over) and the
 *  team's velocity with its sprints-to-done forecast (USER_FLOWS §C11.4). Team-level only. */
export default function SprintReportView({
  teamId,
  sprints,
  sprintId,
  onSprintChange,
}: {
  teamId: number;
  sprints: Sprint[];
  sprintId: number | null;
  onSprintChange: (sprintId: number) => void;
}) {
  const reportable = sprints.filter((s) => s.state !== "planned");
  const chosen = sprintId ?? defaultReportSprint(sprints)?.id ?? null;
  const report = useQuery({
    queryKey: ["sprint-report", chosen],
    queryFn: () => api.get<SprintReport>(`/sprints/${chosen}/report`),
    enabled: chosen !== null,
    // Switching sprints keeps the last report on screen, dimmed, until the next arrives.
    placeholderData: keepPreviousData,
  });
  const velocity = useQuery({
    queryKey: ["velocity", teamId],
    queryFn: () => api.get<Velocity>(`/teams/${teamId}/velocity`),
  });

  return (
    <div className="space-y-6">
      <section className="space-y-4 rounded-lg border border-slate-200 bg-white p-4" aria-label="Sprint report">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-semibold text-slate-800">Sprint report</h2>
          {reportable.length > 0 && (
            <select
              value={chosen ?? ""}
              onChange={(e) => onSprintChange(Number(e.target.value))}
              aria-label="Sprint"
              className="rounded border border-slate-300 px-2 py-1 text-sm"
            >
              {reportable.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} · {STATE_LABELS[s.state].toLowerCase()}
                </option>
              ))}
            </select>
          )}
          {report.data && (
            <span className="text-sm text-slate-500">
              {formatSprintDates(report.data.sprint)}
              {report.data.sprint.goal && <> · Goal: {report.data.sprint.goal}</>}
            </span>
          )}
        </div>

        {chosen === null ? (
          <p className="text-sm text-slate-500">
            No sprint has started yet — the report appears once one is active.
          </p>
        ) : report.isError ? (
          <QueryError error={report.error} onRetry={() => void report.refetch()} label="Couldn’t load the report" />
        ) : !report.data ? (
          <p className="text-sm text-slate-400">Loading the report…</p>
        ) : (
          <div className={`space-y-4 transition-opacity ${report.isPlaceholderData ? "opacity-60" : ""}`}>
            <SprintStats report={report.data} />
            <SprintBurndown report={report.data} />
          </div>
        )}
      </section>

      <section className="space-y-4 rounded-lg border border-slate-200 bg-white p-4" aria-label="Velocity">
        <div>
          <h2 className="font-semibold text-slate-800">Velocity</h2>
          <p className="text-xs text-slate-500">
            What the team completed per sprint against what it committed — a team measure, never
            per person.
          </p>
        </div>
        {velocity.isError ? (
          <QueryError error={velocity.error} onRetry={() => void velocity.refetch()} label="Couldn’t load velocity" />
        ) : !velocity.data ? (
          <p className="text-sm text-slate-400">Loading velocity…</p>
        ) : (
          <TeamVelocity velocity={velocity.data} />
        )}
      </section>
    </div>
  );
}

function SprintStats({ report }: { report: SprintReport }) {
  const v = valueIn(report.unit);
  // While the sprint runs, "completed" is so far and the unfinished work is still open.
  const running = report.sprint.state === "active";
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
      <Stat label="Committed" value={v(report.committed)} hint="at the start" />
      <Stat label="Completed" value={v(report.completed)} hint={running ? "so far" : undefined} />
      <Stat
        label="Reliability"
        value={percent(report.reliability)}
        hint={running ? "completed ÷ committed, so far" : "completed ÷ committed"}
      />
      <Stat label="Scope added" value={v(report.scope_added)} hint="after the start" />
      <Stat label="Scope removed" value={v(report.scope_removed)} />
      <Stat
        label={running ? "Not done yet" : "Carried over"}
        value={v(report.carried_over)}
        hint={running ? "would carry over if it ended now" : "unfinished at the end"}
      />
    </dl>
  );
}

function SprintBurndown({ report }: { report: SprintReport }) {
  const rows = burndownSeries(report);
  if (rows.length === 0) {
    return <p className="text-sm text-slate-500">Give the sprint dates to see its burndown.</p>;
  }
  const v = valueIn(report.unit);
  return (
    <figure className="space-y-2">
      <figcaption className="text-sm font-medium text-slate-700">
        Burndown{" "}
        <span className="font-normal text-slate-400">
          — remaining work against the ideal line; work added after the start shown on its own
        </span>
      </figcaption>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 0 }} accessibilityLayer>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis
              dataKey="label"
              tick={tick}
              tickLine={false}
              axisLine={{ stroke: GRID }}
              interval="preserveStartEnd"
              minTickGap={18}
            />
            <YAxis tick={tick} tickLine={false} axisLine={false} width={44} allowDecimals={false} />
            <Tooltip formatter={v} />
            <Legend formatter={legendText} />
            <Line
              type="linear"
              dataKey="ideal"
              name="Ideal"
              stroke={GUIDE}
              strokeWidth={2}
              strokeDasharray="6 4"
              dot={false}
              activeDot={false}
              isAnimationActive={false}
            />
            <Line
              type="linear"
              dataKey="remaining"
              name="Remaining"
              stroke={SERIES_1}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, stroke: "#ffffff", strokeWidth: 2 }}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              type="stepAfter"
              dataKey="scopeAdded"
              name="Scope added"
              stroke={SERIES_2}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, stroke: "#ffffff", strokeWidth: 2 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <DataTable
        caption="Sprint burndown by day"
        head={["Day", "Remaining", "Ideal", "Scope added"]}
        rows={rows
          .filter((r) => r.remaining !== null)
          .map((r) => [formatDay(r.day), v(r.remaining), v(r.ideal), v(r.scopeAdded ?? 0)])}
      />
    </figure>
  );
}

function TeamVelocity({ velocity }: { velocity: Velocity }) {
  const rows = velocitySeries(velocity);
  const v = valueIn(velocity.unit);
  const f = velocity.forecast;
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat
          label="Mean velocity"
          value={velocity.mean != null ? v(velocity.mean) : "—"}
          hint={
            velocity.low != null && velocity.high != null
              ? `range ${v(velocity.low)} – ${v(velocity.high)}, last six sprints`
              : undefined
          }
        />
        <Stat label="Reliability" value={percent(velocity.mean_reliability)} hint="mean completed ÷ committed" />
        <Stat
          label="Finish, likely (P50)"
          value={f.sufficient && f.p50_sprints != null ? `${f.p50_sprints} sprints` : "—"}
          hint={f.p50_date ? `by ${formatDay(f.p50_date)}` : undefined}
        />
        <Stat
          label="Finish, safe (P85)"
          value={f.sufficient && f.p85_sprints != null ? `${f.p85_sprints} sprints` : "—"}
          hint={f.p85_date ? `by ${formatDay(f.p85_date)}` : undefined}
        />
      </dl>
      <p className="text-xs text-slate-500">
        {f.sufficient
          ? `Forecast for the team’s ${v(f.remaining)} of open work, from ${f.history_sprints} completed sprints.`
          : (f.reason ?? velocity.reason ?? "Not enough sprint history to forecast yet.")}
        {!velocity.sufficient && velocity.reason && f.reason !== velocity.reason && <> {velocity.reason}</>}
      </p>

      {rows.length === 0 ? (
        <p className="text-sm text-slate-500">No sprint has been completed yet.</p>
      ) : (
        <figure className="space-y-2">
          <figcaption className="text-sm font-medium text-slate-700">Committed vs completed per sprint</figcaption>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              {/* A fixed bar size keeps each sprint's pair side by side, 2px apart (a capped
                  size would leave the pair spread across the band). */}
              <BarChart
                data={rows}
                margin={{ top: 8, right: 16, bottom: 4, left: 0 }}
                barGap={2}
                barSize={20}
                accessibilityLayer
              >
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={{ stroke: GRID }} />
                <YAxis tick={tick} tickLine={false} axisLine={false} width={44} allowDecimals={false} />
                <Tooltip formatter={v} cursor={{ fill: "#f1f5f9" }} />
                <Legend formatter={legendText} />
                {velocity.mean != null && (
                  <ReferenceLine
                    y={velocity.mean}
                    stroke={GUIDE}
                    strokeDasharray="6 4"
                    label={{ value: `mean ${v(velocity.mean)}`, position: "insideTopRight", fill: AXIS_TEXT, fontSize: 11 }}
                  />
                )}
                <Bar
                  dataKey="committed"
                  name="Committed"
                  fill={SERIES_1}
                  radius={[4, 4, 0, 0]}
                  isAnimationActive={false}
                />
                <Bar
                  dataKey="completed"
                  name="Completed"
                  fill={SERIES_2}
                  radius={[4, 4, 0, 0]}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <DataTable
            caption="Velocity per completed sprint"
            head={["Sprint", "Committed", "Completed", "Reliability"]}
            rows={rows.map((r) => [r.name, v(r.committed), v(r.completed), percent(r.reliability)])}
          />
        </figure>
      )}
    </div>
  );
}
