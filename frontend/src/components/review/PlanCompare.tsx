import { useMemo, useState } from "react";

import type {
  PreviewTaskChange,
  PreviewTaskKind,
  ProjectPlanPreview,
  ProposalPreview,
} from "../../api/types";
import {
  formatDay,
  formatDayShort,
  formatDelta,
  ganttForMode,
  planDomain,
  planHighlights,
  scheduleUntouched,
  type PlanMode,
} from "../../lib/proposals";
import { deltaTone, formatDayDelta } from "../../lib/scenarioDiff";
import GanttChart from "../GanttChart";

const KIND_CHIP: Record<PreviewTaskKind, { label: string; className: string }> = {
  added: { label: "New", className: "bg-emerald-100 text-emerald-800" },
  edited: { label: "Edited", className: "bg-sky-100 text-sky-800" },
  shifted: { label: "Moves", className: "bg-amber-100 text-amber-800" },
};

/**
 * The plan as a whole, **current ⇄ proposed**: one chart, one time axis, and a toggle. The
 * reviewer flips it to watch the bars move, sees which rows the proposal adds / edits /
 * pushes, and clicks any of them to jump to the change behind it.
 */
export function PlanCompare({
  preview,
  onOpenChanges,
}: {
  preview: ProposalPreview;
  /** Jump to the fine-grained list, focused on these proposal items. */
  onOpenChanges: (itemIds: number[]) => void;
}) {
  const [mode, setMode] = useState<PlanMode>("proposed");
  const [projectId, setProjectId] = useState<number | null>(null);
  const plan = preview.projects.find((p) => p.project_id === projectId) ?? preview.projects[0];

  if (!plan) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
        This proposal doesn&apos;t touch any schedule — see the changes list for what it adds
        to the registers.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {preview.projects.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {preview.projects.map((p) => (
            <button
              key={p.project_id}
              onClick={() => setProjectId(p.project_id)}
              className={`rounded-full px-3 py-1 text-sm ${
                p.project_id === plan.project_id
                  ? "bg-slate-800 text-white"
                  : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              <span className="font-mono text-xs opacity-70">{p.key}</span> {p.name}
              {p.end_delta_days ? (
                <span className="ml-1.5 text-xs opacity-80">{formatDelta(p.end_delta_days)}</span>
              ) : null}
            </button>
          ))}
        </div>
      )}
      <ProjectPlan
        key={plan.project_id}
        plan={plan}
        mode={mode}
        onMode={setMode}
        untouched={scheduleUntouched(preview.counts)}
        onOpenChanges={onOpenChanges}
      />
    </div>
  );
}

function ProjectPlan({
  plan,
  mode,
  onMode,
  untouched,
  onOpenChanges,
}: {
  plan: ProjectPlanPreview;
  mode: PlanMode;
  onMode: (mode: PlanMode) => void;
  untouched: boolean;
  onOpenChanges: (itemIds: number[]) => void;
}) {
  // With a dependency cycle there is no future state to draw — only "current" is available.
  const effectiveMode: PlanMode = plan.proposed ? mode : "current";
  const data = useMemo(() => ganttForMode(plan, effectiveMode), [plan, effectiveMode]);
  const highlights = useMemo(() => planHighlights(plan, effectiveMode), [plan, effectiveMode]);
  const domain = useMemo(() => planDomain(plan), [plan]);
  const changeById = useMemo(
    () => new Map(plan.task_changes.map((c) => [c.task_id, c])),
    [plan]
  );
  const movedMilestones = plan.milestones.filter((m) => m.kind !== "unchanged");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div
          role="tablist"
          aria-label="Plan state"
          className="inline-flex rounded-lg bg-slate-100 p-1 text-sm"
        >
          {(["current", "proposed"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={effectiveMode === m}
              disabled={m === "proposed" && !plan.proposed}
              onClick={() => onMode(m)}
              className={`rounded-md px-4 py-1.5 font-medium transition-colors disabled:opacity-40 ${
                effectiveMode === m
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {m === "current" ? "Current plan" : "With this proposal"}
            </button>
          ))}
        </div>
        <p className="text-sm text-slate-500">
          {effectiveMode === "current"
            ? "The plan as it stands today. Tinted rows are the ones this proposal will touch."
            : "The plan after applying. Thin grey bars show where a task sits today."}
        </p>
      </div>

      {plan.cycle && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          These changes would create a dependency loop in {plan.key}, so there is no schedule
          to preview. Exclude or fix one of the new dependencies in the changes list.
        </p>
      )}
      {plan.live_schedule_stale && (
        <p className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-500">
          This project had edits that weren&apos;t replanned yet, so &ldquo;Current plan&rdquo;
          is shown recalculated — every difference you see here comes from this proposal.
        </p>
      )}
      {untouched && !plan.cycle && (
        <p className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-500">
          Nothing in this proposal moves the schedule — the chart is the same on both sides.
        </p>
      )}

      {data.tasks.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-400">
          No tasks {effectiveMode === "current" ? "in the plan yet" : "after applying"}.
        </div>
      ) : (
        <GanttChart
          data={data}
          highlights={highlights}
          domain={domain}
          ghostLabel="Current plan"
          fit
          onTaskClick={(taskId) => {
            const change = changeById.get(taskId);
            if (change && change.item_ids.length > 0) onOpenChanges(change.item_ids);
          }}
        />
      )}

      {plan.new_deadline_misses.length > 0 && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <p className="font-medium">
            {plan.new_deadline_misses.length === 1
              ? "One task would now miss its deadline:"
              : `${plan.new_deadline_misses.length} tasks would now miss their deadlines:`}
          </p>
          <ul className="mt-1 list-inside list-disc">
            {plan.new_deadline_misses.map((m) => (
              <li key={m.task_id}>
                {m.name} — finishes {formatDay(m.end)}, due {formatDay(m.deadline)}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-white lg:col-span-2">
          <h3 className="border-b border-slate-100 px-4 py-2.5 text-sm font-semibold">
            What moves{" "}
            <span className="font-normal text-slate-400">
              ({plan.task_changes.length} {plan.task_changes.length === 1 ? "task" : "tasks"})
            </span>
          </h3>
          {plan.task_changes.length === 0 ? (
            <p className="px-4 py-4 text-sm text-slate-400">No task changes position.</p>
          ) : (
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-white text-left text-xs text-slate-400">
                  <tr>
                    <th className="w-full px-4 py-2 font-medium">Task</th>
                    <th className="px-2 py-2 font-medium">Start</th>
                    <th className="px-2 py-2 font-medium">Finish</th>
                    <th className="px-4 py-2 text-right font-medium">Finish moves</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.task_changes.map((c) => (
                    <MoveRow key={c.task_id} change={c} onOpenChanges={onOpenChanges} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="rounded-lg border border-slate-200 bg-white">
          <h3 className="border-b border-slate-100 px-4 py-2.5 text-sm font-semibold">
            Milestones
          </h3>
          {plan.milestones.length === 0 ? (
            <p className="px-4 py-4 text-sm text-slate-400">No milestones on this project.</p>
          ) : (
            <ul className="max-h-80 divide-y divide-slate-100 overflow-auto text-sm">
              {plan.milestones.map((m) => (
                <li
                  key={m.milestone_id}
                  className={`flex items-start gap-2 px-4 py-2 ${
                    m.kind === "unchanged" ? "text-slate-500" : ""
                  }`}
                >
                  <span className={m.kind === "unchanged" ? "text-slate-300" : "text-canopy-700"}>
                    ◆
                  </span>
                  <button
                    disabled={m.item_ids.length === 0}
                    onClick={() => onOpenChanges(m.item_ids)}
                    className="min-w-0 flex-1 text-left enabled:hover:underline"
                  >
                    <span className="block truncate font-medium">{m.name}</span>
                    <span className="block text-xs text-slate-500">
                      {m.kind === "edited" && m.target_before !== m.target_after ? (
                        <>
                          <span className="line-through decoration-slate-300">
                            {formatDay(m.target_before)}
                          </span>{" "}
                          → {formatDay(m.target_after)}
                        </>
                      ) : (
                        formatDay(m.target_after)
                      )}
                      {m.kind === "edited" && m.status_before !== m.status_after && (
                        <> · {m.status_before} → {m.status_after}</>
                      )}
                    </span>
                  </button>
                  {m.kind !== "unchanged" && (
                    <span
                      className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-medium ${
                        m.kind === "added"
                          ? "bg-emerald-100 text-emerald-800"
                          : "bg-sky-100 text-sky-800"
                      }`}
                    >
                      {m.kind === "added" ? "New" : "Changed"}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {movedMilestones.length === 0 && plan.milestones.length > 0 && (
            <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-400">
              No milestone changes in this proposal.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function MoveRow({
  change,
  onOpenChanges,
}: {
  change: PreviewTaskChange;
  onOpenChanges: (itemIds: number[]) => void;
}) {
  const chip = KIND_CHIP[change.kind];
  const linked = change.item_ids.length > 0;
  const span = (before: string | null, after: string | null) => (
    <span title={before && before !== after ? `${formatDay(before)} → ${formatDay(after)}` : formatDay(after)}>
      {before && before !== after ? (
        <>
          <span className="text-slate-400 line-through decoration-slate-300">
            {formatDayShort(before)}
          </span>{" "}
          → {formatDayShort(after)}
        </>
      ) : (
        formatDayShort(after)
      )}
    </span>
  );
  return (
    <tr
      onClick={linked ? () => onOpenChanges(change.item_ids) : undefined}
      className={`border-t border-slate-100 ${linked ? "cursor-pointer hover:bg-slate-50" : ""}`}
      title={linked ? "Show the change behind this" : "Moves because of another change"}
    >
      <td className="px-4 py-2">
        <span className={`mr-2 rounded px-1.5 py-0.5 text-xs font-medium ${chip.className}`}>
          {chip.label}
        </span>
        <span className={change.is_summary ? "font-semibold" : ""}>{change.name}</span>
        {change.critical_after && !change.critical_before && (
          <span className="ml-2 text-xs text-red-600">now critical</span>
        )}
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-slate-600">
        {span(change.start_before, change.start_after)}
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-slate-600">
        {span(change.end_before, change.end_after)}
      </td>
      <td
        className={`whitespace-nowrap px-4 py-2 text-right ${deltaTone(change.end_delta_days)}`}
      >
        {change.kind === "added" ? "—" : formatDayDelta(change.end_delta_days)}
      </td>
    </tr>
  );
}
