import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { BoardResponse, Engineer } from "../api/types";
import { initials } from "./GanttChart";

export default function FlowBoard({
  projectId,
  onTaskClick,
}: {
  projectId: number;
  onTaskClick?: (taskId: number) => void;
}) {
  const [wipLimit, setWipLimit] = useState(5);
  const [ownerFilter, setOwnerFilter] = useState("");
  const { data } = useQuery({
    queryKey: ["board", projectId],
    queryFn: () => api.get<BoardResponse>(`/projects/${projectId}/board`),
  });
  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });
  const names = useMemo(
    () => new Map((engineers.data ?? []).map((e) => [e.id, e.name])),
    [engineers.data],
  );
  const owners = useMemo(() => {
    const present = new Set(
      (data?.lanes ?? []).flatMap((lane) =>
        lane.tasks
          .map((t) => t.assignee_engineer_id)
          .filter((id): id is number => id !== null),
      ),
    );
    return [...present]
      .map((id) => [id, names.get(id) ?? `#${id}`] as const)
      .sort((a, b) => a[1].localeCompare(b[1]));
  }, [data, names]);

  if (!data) {
    return <p className="text-sm text-slate-500">Loading board…</p>;
  }
  if (data.lanes.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No tasks to show. Tasks group into lanes by their (Jira-mirrored) status.
      </p>
    );
  }

  const matchesOwner = (assignee: number | null) =>
    !ownerFilter ||
    (ownerFilter === "none" ? assignee === null : assignee === Number(ownerFilter));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-sm text-slate-500">
        <label className="flex items-center gap-1">
          WIP limit per lane
          <input
            type="number"
            min={1}
            value={wipLimit}
            onChange={(e) => setWipLimit(Math.max(1, Number(e.target.value)))}
            className="w-16 rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </label>
        <label className="flex items-center gap-1">
          owner
          <select
            value={ownerFilter}
            onChange={(e) => setOwnerFilter(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
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
        <span>
          cycle-time P85:{" "}
          {data.cycle_time_p85_days != null ? `${data.cycle_time_p85_days}d` : "—"}
        </span>
        {data.aging_count > 0 && (
          <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
            {data.aging_count} aging
          </span>
        )}
      </div>

      <div className="flex gap-3 overflow-x-auto pb-2">
        {data.lanes.map((lane) => {
          const overWip = !lane.is_done && lane.wip > wipLimit;
          const tasks = lane.tasks.filter((t) => matchesOwner(t.assignee_engineer_id));
          return (
            <div key={lane.status} className="w-64 shrink-0">
              <div
                className={`flex items-center justify-between rounded-t border-b-2 px-3 py-2 text-sm font-medium ${
                  overWip ? "border-red-400 bg-red-50 text-red-700" : "border-slate-200 bg-slate-50"
                }`}
              >
                <span className="truncate">{lane.status}</span>
                <span className="shrink-0 tabular-nums">
                  {lane.is_done ? lane.tasks.length : `${lane.wip}/${wipLimit}`}
                </span>
              </div>
              <ul className="space-y-2 rounded-b bg-slate-100/50 p-2">
                {tasks.map((t) => {
                  const owner =
                    t.assignee_engineer_id !== null
                      ? names.get(t.assignee_engineer_id)
                      : undefined;
                  return (
                    <li
                      key={t.id}
                      onClick={onTaskClick ? () => onTaskClick(t.id) : undefined}
                      className={`rounded border bg-white p-2 text-sm ${
                        t.aging ? "border-amber-300" : "border-slate-200"
                      } ${onTaskClick ? "cursor-pointer hover:border-canopy-400" : ""}`}
                    >
                      <div className="truncate">{t.name}</div>
                      <div className="mt-1 flex items-center gap-2 text-xs text-slate-400">
                        <span>{t.age_days}d in status</span>
                        {t.aging && (
                          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-700">
                            aging
                          </span>
                        )}
                        {owner && (
                          <span
                            title={owner}
                            className="ml-auto flex h-5 w-5 items-center justify-center rounded-full bg-slate-200 text-[10px] font-semibold text-slate-600"
                          >
                            {initials(owner)}
                          </span>
                        )}
                      </div>
                    </li>
                  );
                })}
                {tasks.length === 0 && (
                  <li className="px-1 py-2 text-center text-xs text-slate-400">empty</li>
                )}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}
