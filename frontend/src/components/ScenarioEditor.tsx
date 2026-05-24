import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Engineer, GanttResponse, Project, TaskType } from "../api/types";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-700">{title}</h3>
      {children}
    </section>
  );
}

const input = "rounded border border-slate-300 px-2 py-1.5 text-sm";
const btn = "rounded bg-canopy-500 px-3 py-1.5 text-sm font-medium text-white";

export default function ScenarioEditor({
  scenarioId,
  projects,
  projectId,
  onProjectChange,
}: {
  scenarioId: number;
  projects: Project[];
  projectId: number;
  onProjectChange: (id: number) => void;
}) {
  const qc = useQueryClient();
  const refresh = () =>
    qc.invalidateQueries({
      predicate: (q) => String(q.queryKey[0]).startsWith("scenario"),
    });

  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });
  const gantt = useQuery({
    queryKey: ["scenario-gantt", scenarioId, projectId],
    queryFn: () =>
      api.get<GanttResponse>(`/scenarios/${scenarioId}/gantt?project_id=${projectId}`),
  });
  const tasks = gantt.data?.tasks ?? [];

  // Local form state.
  const [taskName, setTaskName] = useState("");
  const [taskDuration, setTaskDuration] = useState(1);
  const [taskType, setTaskType] = useState<TaskType>("task");
  const [predId, setPredId] = useState<number | "">("");
  const [succId, setSuccId] = useState<number | "">("");
  const [engId, setEngId] = useState<number | "">("");
  const [pct, setPct] = useState(100);
  const [aStart, setAStart] = useState("");
  const [aEnd, setAEnd] = useState("");
  const [avEngId, setAvEngId] = useState<number | "">("");
  const [avStart, setAvStart] = useState("");
  const [avEnd, setAvEnd] = useState("");
  const [avFactor, setAvFactor] = useState(0);
  const [mName, setMName] = useState("");
  const [mDate, setMDate] = useState("");
  const [kStart, setKStart] = useState("");
  const [kTarget, setKTarget] = useState("");

  const addTask = useMutation({
    mutationFn: () =>
      api.post(`/scenarios/${scenarioId}/tasks`, {
        project_id: projectId,
        name: taskName,
        type: taskType,
        duration: taskDuration,
      }),
    onSuccess: () => {
      setTaskName("");
      setTaskDuration(1);
      refresh();
    },
  });
  const removeTask = useMutation({
    mutationFn: (id: number) => api.del(`/scenario-tasks/${id}`),
    onSuccess: refresh,
  });
  const addDep = useMutation({
    mutationFn: () =>
      api.post(`/scenarios/${scenarioId}/dependencies`, {
        predecessor_id: predId,
        successor_id: succId,
        type: "FS",
      }),
    onSuccess: () => {
      setPredId("");
      setSuccId("");
      refresh();
    },
  });
  const addAlloc = useMutation({
    mutationFn: () =>
      api.post(`/scenarios/${scenarioId}/allocations`, {
        engineer_id: engId,
        project_id: projectId,
        percent_allocation: pct,
        start_date: aStart || null,
        end_date: aEnd || null,
      }),
    onSuccess: () => {
      setEngId("");
      refresh();
    },
  });
  const addAvail = useMutation({
    mutationFn: () =>
      api.post(`/scenarios/${scenarioId}/availability`, {
        engineer_id: avEngId,
        start_date: avStart,
        end_date: avEnd,
        capacity_factor: avFactor,
      }),
    onSuccess: () => {
      setAvEngId("");
      refresh();
    },
  });
  const addMilestone = useMutation({
    mutationFn: () =>
      api.post(`/scenarios/${scenarioId}/milestones`, {
        project_id: projectId,
        name: mName,
        target_date: mDate || null,
      }),
    onSuccess: () => {
      setMName("");
      setMDate("");
      refresh();
    },
  });
  const saveKnobs = useMutation({
    mutationFn: () => {
      const body: Record<string, string> = {};
      if (kStart) body.start_date = kStart;
      if (kTarget) body.target_date = kTarget;
      return api.patch(`/scenarios/${scenarioId}/projects/${projectId}`, body);
    },
    onSuccess: refresh,
  });

  const engineerOptions = (engineers.data ?? []).map((e) => (
    <option key={e.id} value={e.id}>
      {e.name}
    </option>
  ));

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-sm text-slate-500">Editing scope for project:</span>
        <select
          value={projectId}
          onChange={(e) => onProjectChange(Number(e.target.value))}
          className={input}
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.key} · {p.name}
            </option>
          ))}
        </select>
      </div>

      <Section title="Scope — tasks">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (taskName) addTask.mutate();
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <input
            placeholder="Task name"
            value={taskName}
            onChange={(e) => setTaskName(e.target.value)}
            className={`${input} grow`}
          />
          <select
            value={taskType}
            onChange={(e) => setTaskType(e.target.value as TaskType)}
            className={input}
          >
            <option value="task">task</option>
            <option value="summary">summary</option>
            <option value="milestone">milestone</option>
          </select>
          <label className="flex items-center gap-1 text-sm text-slate-500">
            <input
              type="number"
              min={0}
              value={taskDuration}
              onChange={(e) => setTaskDuration(Number(e.target.value))}
              className={`${input} w-20`}
            />
            days
          </label>
          <button className={btn}>Add task</button>
        </form>
        <ul className="mt-3 divide-y divide-slate-100 text-sm">
          {tasks.map((t) => (
            <li key={t.id} className="flex items-center justify-between py-1.5">
              <span>
                {t.text}{" "}
                <span className="text-xs text-slate-400">
                  · {t.duration}d · {t.type}
                </span>
              </span>
              <button
                onClick={() => removeTask.mutate(t.id)}
                className="text-xs text-slate-400 hover:text-red-600"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Scope — dependency (within this project)">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (predId && succId && predId !== succId) addDep.mutate();
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <select
            value={predId}
            onChange={(e) => setPredId(e.target.value ? Number(e.target.value) : "")}
            className={input}
          >
            <option value="">Predecessor…</option>
            {tasks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.text}
              </option>
            ))}
          </select>
          <span className="text-slate-400">→</span>
          <select
            value={succId}
            onChange={(e) => setSuccId(e.target.value ? Number(e.target.value) : "")}
            className={input}
          >
            <option value="">Successor…</option>
            {tasks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.text}
              </option>
            ))}
          </select>
          <button className={btn}>Link</button>
        </form>
      </Section>

      <Section title="Team — allocation">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (engId) addAlloc.mutate();
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <select
            value={engId}
            onChange={(e) => setEngId(e.target.value ? Number(e.target.value) : "")}
            className={input}
          >
            <option value="">Engineer…</option>
            {engineerOptions}
          </select>
          <label className="flex items-center gap-1 text-sm text-slate-500">
            <input
              type="number"
              min={0}
              max={200}
              value={pct}
              onChange={(e) => setPct(Number(e.target.value))}
              className={`${input} w-20`}
            />
            %
          </label>
          <input type="date" value={aStart} onChange={(e) => setAStart(e.target.value)} className={input} />
          <span className="text-slate-400">→</span>
          <input type="date" value={aEnd} onChange={(e) => setAEnd(e.target.value)} className={input} />
          <button className={btn}>Allocate</button>
        </form>
      </Section>

      <Section title="Team — availability (PTO / ramp-up)">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (avEngId && avStart && avEnd) addAvail.mutate();
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <select
            value={avEngId}
            onChange={(e) => setAvEngId(e.target.value ? Number(e.target.value) : "")}
            className={input}
          >
            <option value="">Engineer…</option>
            {engineerOptions}
          </select>
          <input type="date" value={avStart} onChange={(e) => setAvStart(e.target.value)} className={input} />
          <span className="text-slate-400">→</span>
          <input type="date" value={avEnd} onChange={(e) => setAvEnd(e.target.value)} className={input} />
          <label className="flex items-center gap-1 text-sm text-slate-500">
            capacity
            <input
              type="number"
              min={0}
              max={1}
              step={0.25}
              value={avFactor}
              onChange={(e) => setAvFactor(Number(e.target.value))}
              className={`${input} w-20`}
            />
          </label>
          <button className={btn}>Add</button>
        </form>
      </Section>

      <Section title="Milestone & deadlines">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (mName) addMilestone.mutate();
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <input
            placeholder="Milestone name"
            value={mName}
            onChange={(e) => setMName(e.target.value)}
            className={`${input} grow`}
          />
          <input type="date" value={mDate} onChange={(e) => setMDate(e.target.value)} className={input} />
          <button className={btn}>Add milestone</button>
        </form>
      </Section>

      <Section title="Project schedule knobs">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            saveKnobs.mutate();
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <label className="flex items-center gap-1 text-sm text-slate-500">
            start
            <input type="date" value={kStart} onChange={(e) => setKStart(e.target.value)} className={input} />
          </label>
          <label className="flex items-center gap-1 text-sm text-slate-500">
            target
            <input type="date" value={kTarget} onChange={(e) => setKTarget(e.target.value)} className={input} />
          </label>
          <button className={btn}>Save knobs</button>
        </form>
      </Section>
    </div>
  );
}
