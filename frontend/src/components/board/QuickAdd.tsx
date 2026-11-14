import { useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { Task } from "../../api/types";
import { trackingFailure } from "../../lib/board";
import { Icon } from "../icons";

/** Fields a new card inherits from where it was added (its swimlane's owner or phase). */
export interface QuickAddDefaults {
  assignee_engineer_id?: number;
  parent_id?: number;
}

/** A project a card can be added to. */
export interface QuickAddProject {
  id: number;
  label: string;
}

/** "+ Add card" at the foot of a column (planners): `POST /tasks` straight into this column's
 *  status. On a team board it asks which project the card belongs to. Stays open after each
 *  add so a backlog can be typed in quickly; Escape closes it. */
export default function QuickAdd({
  projects,
  defaultProjectId,
  status,
  defaults,
  onCreated,
}: {
  /** Where the card can go — one project means no picker. */
  projects: QuickAddProject[];
  defaultProjectId?: number;
  status: string;
  defaults?: QuickAddDefaults;
  onCreated?: (task: Task) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<number | null>(null);
  const inputId = useId();
  const projectId = picked ?? defaultProjectId ?? projects[0]?.id ?? null;

  const create = useMutation({
    mutationFn: (vars: { name: string; projectId: number }) =>
      api.post<Task>("/tasks", { project_id: vars.projectId, name: vars.name, status, ...defaults }),
    onSuccess: (task) => {
      setName("");
      onCreated?.(task);
    },
  });

  const close = () => {
    setOpen(false);
    setName("");
    create.reset();
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-full items-center gap-1 rounded px-1.5 py-1 text-xs text-slate-400 hover:bg-white hover:text-canopy-700"
      >
        <Icon name="plus" size={13} />
        Add card
      </button>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const taskName = name.trim();
        if (taskName && projectId !== null && !create.isPending) {
          create.mutate({ name: taskName, projectId });
        }
      }}
      className="space-y-1.5"
    >
      <label htmlFor={inputId} className="sr-only">
        New card in {status}
      </label>
      <input
        id={inputId}
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") close();
        }}
        placeholder="Card name"
        className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm focus:border-canopy-500 focus:outline-none"
      />
      {projects.length > 1 && (
        <select
          value={projectId ?? ""}
          onChange={(e) => setPicked(Number(e.target.value))}
          aria-label={`Project for the new card in ${status}`}
          className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs"
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
      )}
      {create.isError && (
        <p role="alert" className="text-xs text-red-700">
          {trackingFailure(create.error).message}
        </p>
      )}
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={create.isPending || !name.trim() || projectId === null}
          className="rounded bg-canopy-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-canopy-700 disabled:opacity-50"
        >
          {create.isPending ? "Adding…" : "Add"}
        </button>
        <button type="button" onClick={close} className="text-xs text-slate-500 hover:text-slate-700">
          Cancel
        </button>
      </div>
    </form>
  );
}
