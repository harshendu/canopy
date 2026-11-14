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

/** "+ Add card" at the foot of a column (planners): `POST /tasks` straight into this column's
 *  status. Stays open after each add so a backlog can be typed in quickly; Escape closes it. */
export default function QuickAdd({
  projectId,
  status,
  defaults,
  onCreated,
}: {
  projectId: number;
  status: string;
  defaults?: QuickAddDefaults;
  onCreated?: (task: Task) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const inputId = useId();

  const create = useMutation({
    mutationFn: (taskName: string) =>
      api.post<Task>("/tasks", { project_id: projectId, name: taskName, status, ...defaults }),
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
        if (taskName && !create.isPending) create.mutate(taskName);
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
      {create.isError && (
        <p role="alert" className="text-xs text-red-700">
          {trackingFailure(create.error).message}
        </p>
      )}
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={create.isPending || !name.trim()}
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
