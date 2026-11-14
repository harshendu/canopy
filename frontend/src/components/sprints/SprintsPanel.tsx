import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { BoardResponse, Engineer, Pod, Sprint, SprintCreate } from "../../api/types";
import {
  CANOPY_OWNER,
  boardPath,
  boardQueryKey,
  normalizeBoard,
  trackerName,
  trackingFailure,
} from "../../lib/board";
import { invalidateSprintData } from "../../lib/sprintCache";
import {
  STATE_LABELS,
  defaultPlanningSprint,
  formatEstimate,
  formatSprintDates,
  localToday,
  timeLeftLabel,
} from "../../lib/sprints";
import { Icon } from "../icons";
import { QueryError } from "../QueryError";
import SprintPlanning from "./SprintPlanning";

const STATE_TONE: Record<Sprint["state"], string> = {
  active: "bg-canopy-50 text-canopy-700",
  planned: "bg-slate-100 text-slate-600",
  completed: "bg-slate-100 text-slate-400",
};

/** The Sprints tab of a team (USER_FLOWS §C11.3): its sprints — active, planned, then
 *  completed — a form for a new one, and the planning view of the selected sprint. */
export default function SprintsPanel({
  teamId,
  pods,
  projectKeys,
  onReport,
}: {
  teamId: number;
  pods: Pod[];
  /** Project id → key, to label the team's tasks. */
  projectKeys: ReadonlyMap<number, string>;
  onReport: (sprintId: number) => void;
}) {
  const sprints = useQuery({
    queryKey: ["sprints", teamId],
    queryFn: () => api.get<Sprint[]>(`/teams/${teamId}/sprints`),
  });
  // The backlog, and — through its viewer — whether the caller may plan the team's sprints.
  const source = { kind: "team", id: teamId } as const;
  const backlog = useQuery({
    queryKey: boardQueryKey(source, "backlog"),
    queryFn: async () => normalizeBoard(await api.get<BoardResponse>(boardPath(source, "backlog"))),
  });
  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });
  const names = useMemo(
    () => new Map((engineers.data ?? []).map((e) => [e.id, e.name] as const)),
    [engineers.data],
  );
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const maySprint = backlog.data?.viewer?.can_plan ?? false;
  const today = localToday();

  if (sprints.isError) {
    return (
      <QueryError error={sprints.error} onRetry={() => void sprints.refetch()} label="Couldn’t load the sprints" />
    );
  }
  if (!sprints.data) return <p className="text-sm text-slate-500">Loading sprints…</p>;

  const list = sprints.data;
  const selected = list.find((s) => s.id === selectedId) ?? defaultPlanningSprint(list);

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <aside className="space-y-3" aria-label="Sprints">
        {maySprint && (
          <CreateSprint teamId={teamId} pods={pods} onCreated={(s) => setSelectedId(s.id)} />
        )}
        {list.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500">
            No sprints yet.{" "}
            {maySprint ? "Create the first one above." : "The team’s planners create them."}
          </p>
        ) : (
          <ul className="space-y-1.5">
            {list.map((s) => {
              const isSelected = selected?.id === s.id;
              const left = timeLeftLabel(s, today);
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(s.id)}
                    aria-current={isSelected ? "true" : undefined}
                    className={`w-full rounded-md border px-3 py-2 text-left ${
                      isSelected
                        ? "border-canopy-500 bg-canopy-50"
                        : "border-slate-200 bg-white hover:border-slate-300"
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${STATE_TONE[s.state]}`}>
                        {STATE_LABELS[s.state]}
                      </span>
                      <span className="truncate text-sm font-medium text-slate-800">{s.name}</span>
                      {s.owner !== CANOPY_OWNER && (
                        <span
                          title={`Mirrored from ${trackerName(s.owner)}`}
                          className="ml-auto text-blue-700"
                        >
                          <Icon name="lock" size={12} />
                        </span>
                      )}
                    </span>
                    <span className="mt-0.5 block text-xs text-slate-500">
                      {formatSprintDates(s)}
                      {left && <> · {left}</>}
                    </span>
                    <span className="mt-0.5 block text-xs text-slate-400">
                      {s.done_count}/{s.task_count} tasks done · {formatEstimate(s.done, s.unit)} of{" "}
                      {formatEstimate(s.scope, s.unit)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </aside>

      <div className="min-w-0">
        {selected ? (
          <SprintPlanning
            key={selected.id}
            teamId={teamId}
            sprint={selected}
            sprints={list}
            backlog={backlog.data}
            backlogError={backlog.error}
            maySprint={maySprint}
            names={names}
            projectKeys={projectKeys}
            today={today}
            onDeleted={() => setSelectedId(null)}
            onReport={onReport}
          />
        ) : (
          <p className="text-sm text-slate-500">Pick a sprint to plan it.</p>
        )}
      </div>
    </div>
  );
}

/** "New sprint": everything optional — the server names it "Sprint n" and dates it after the
 *  team's last sprint, for the team's sprint length. */
function CreateSprint({
  teamId,
  pods,
  onCreated,
}: {
  teamId: number;
  pods: Pod[];
  onCreated: (sprint: Sprint) => void;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [pod, setPod] = useState("");
  const create = useMutation({
    mutationFn: (body: SprintCreate) => api.post<Sprint>(`/teams/${teamId}/sprints`, body),
    onSuccess: (sprint) => {
      setOpen(false);
      setName("");
      setGoal("");
      setStart("");
      setEnd("");
      setPod("");
      void invalidateSprintData(qc, teamId);
      onCreated(sprint);
    },
  });
  const badDates = Boolean(start && end && end < start);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-full items-center justify-center gap-1 rounded-md border border-canopy-500 px-3 py-2 text-sm font-medium text-canopy-700 hover:bg-canopy-50"
      >
        <Icon name="plus" size={14} />
        New sprint
      </button>
    );
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (badDates) return;
        create.mutate({
          name: name.trim() || null,
          goal: goal.trim() || null,
          start_date: start || null,
          end_date: end || null,
          pod_id: pod ? Number(pod) : null,
        });
      }}
      className="space-y-2 rounded-md border border-slate-200 bg-white p-3 text-sm"
    >
      <h3 className="font-semibold text-slate-700">New sprint</h3>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Name (default “Sprint n”)"
        aria-label="Sprint name"
        className="w-full rounded border border-slate-300 px-2 py-1"
      />
      <input
        value={goal}
        onChange={(e) => setGoal(e.target.value)}
        placeholder="Goal (optional)"
        aria-label="Sprint goal"
        className="w-full rounded border border-slate-300 px-2 py-1"
      />
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-slate-500">
          Starts
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="mt-0.5 w-full rounded border border-slate-300 px-1 py-1 text-sm"
          />
        </label>
        <label className="text-xs text-slate-500">
          Ends
          <input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            aria-invalid={badDates}
            className="mt-0.5 w-full rounded border border-slate-300 px-1 py-1 text-sm"
          />
        </label>
      </div>
      <p className="text-xs text-slate-400">
        Leave the dates empty to start the day after the last sprint, for the team’s sprint length.
      </p>
      {pods.length > 1 && (
        <label className="block text-xs text-slate-500">
          Plans for
          <select
            value={pod}
            onChange={(e) => setPod(e.target.value)}
            className="mt-0.5 w-full rounded border border-slate-300 px-1 py-1 text-sm"
          >
            <option value="">The whole team</option>
            {pods.map((p) => (
              <option key={p.id} value={String(p.id)}>
                {p.name} pod
              </option>
            ))}
          </select>
        </label>
      )}
      {badDates && <p className="text-xs text-red-700">The end is before the start.</p>}
      {create.isError && (
        <p role="alert" className="text-xs text-red-700">
          {trackingFailure(create.error).message}
        </p>
      )}
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={create.isPending || badDates}
          className="rounded bg-canopy-700 px-3 py-1 text-sm font-medium text-white disabled:opacity-50"
        >
          {create.isPending ? "Creating…" : "Create"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="text-sm text-slate-500">
          Cancel
        </button>
      </div>
    </form>
  );
}
