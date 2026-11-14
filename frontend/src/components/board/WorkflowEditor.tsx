import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { WipEnforcement, WorkflowRead, WorkflowUpdate } from "../../api/types";
import {
  CATEGORY_LABELS,
  boardQueryKey,
  fold,
  isClosedCategory,
  trackingFailure,
  workflowPath,
  workflowQueryKey,
  type Board,
  type BoardSource,
  type TrackingFailure,
} from "../../lib/board";
import {
  CATEGORY_ORDER,
  ENFORCEMENT_LABELS,
  MAX_COLUMN_NAME,
  buildWorkflowUpdate,
  draftFromWorkflow,
  moveColumn,
  newColumnDraft,
  occupiedColumns,
  removedColumns,
  validateDraft,
  workflowSourceLabel,
  type ColumnDraft,
  type WorkflowDraft,
} from "../../lib/workflow";
import { Icon } from "../icons";
import { QueryError } from "../QueryError";

const INPUT =
  "rounded border border-slate-300 bg-white px-2 py-1 text-sm focus:border-canopy-500 focus:outline-none disabled:bg-slate-50 disabled:text-slate-400";

/** The planners' editor for a board's columns (USER_FLOWS §C9.1): names, categories, WIP limits
 *  and order, WIP enforcement, and where a removed column's cards go. Saving gives the project
 *  its own columns; "Use team/workspace columns" drops that override. */
export default function WorkflowEditor({
  source,
  board,
  onClose,
}: {
  source: BoardSource;
  board: Board;
  onClose: () => void;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const workflow = useQuery({
    queryKey: workflowQueryKey(source),
    queryFn: () => api.get<WorkflowRead>(workflowPath(source)),
  });

  // Focus the dialog while it is open, and hand focus back to what opened it.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialogRef.current?.focus();
    return () => opener?.focus();
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="animate-fade-in fixed inset-0 z-40 bg-black/20" onClick={onClose} aria-hidden />
      <aside
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="animate-slide-in-right fixed right-0 top-0 z-50 flex h-full w-[600px] max-w-full flex-col border-l border-slate-200 bg-white shadow-xl focus:outline-none"
      >
        <header className="flex items-start justify-between gap-2 border-b border-slate-100 p-4">
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-400">Board</div>
            <h2 id={titleId} className="text-lg font-semibold">
              Edit columns
            </h2>
            {workflow.data && (
              <p className="mt-1 text-sm text-slate-500">{workflowSourceLabel(workflow.data)}</p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <Icon name="close" size={16} />
          </button>
        </header>
        {workflow.isError ? (
          <div className="p-4">
            <QueryError
              error={workflow.error}
              onRetry={() => void workflow.refetch()}
              label="Couldn’t load the columns"
            />
          </div>
        ) : !workflow.data ? (
          <p className="p-4 text-sm text-slate-400">Loading columns…</p>
        ) : (
          <WorkflowForm source={source} workflow={workflow.data} board={board} onDone={onClose} />
        )}
      </aside>
    </>
  );
}

function WorkflowForm({
  source,
  workflow,
  board,
  onDone,
}: {
  source: BoardSource;
  workflow: WorkflowRead;
  board: Board;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<WorkflowDraft>(() => draftFromWorkflow(workflow));
  // Removed column → the uid of the draft column its cards move to.
  const [moveTo, setMoveTo] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<TrackingFailure | null>(null);
  // Columns the server says still hold cards (it counts every project sharing the columns).
  const [inUse, setInUse] = useState<string[]>([]);
  const nextUid = useRef(0);

  const occupied = useMemo(() => {
    const counts = occupiedColumns(board.lanes);
    for (const name of inUse) counts[fold(name)] = Math.max(counts[fold(name)] ?? 0, 1);
    return counts;
  }, [board.lanes, inUse]);
  const removed = removedColumns(workflow.columns, draft);
  const problems = validateDraft(draft, removed, occupied, moveTo);
  const canReset = source.kind === "project" && workflow.scope === "project";

  const afterChange = () => {
    void qc.invalidateQueries({ queryKey: workflowQueryKey(source) });
    void qc.invalidateQueries({ queryKey: boardQueryKey(source) });
    onDone();
  };
  const fail = (err: Error) => {
    const failure = trackingFailure(err);
    setServerError(failure);
    if (failure.code === "column_in_use") setInUse(failure.columns);
  };
  const save = useMutation({
    mutationFn: (body: WorkflowUpdate) => api.put<WorkflowRead>(workflowPath(source), body),
    onSuccess: (saved) => {
      qc.setQueryData(workflowQueryKey(source), saved);
      afterChange();
    },
    onError: fail,
  });
  const reset = useMutation({
    mutationFn: () => api.del(workflowPath(source)),
    onSuccess: afterChange,
    onError: fail,
  });

  const setColumns = (update: (columns: ColumnDraft[]) => ColumnDraft[]) => {
    setServerError(null);
    setDraft((d) => ({ ...d, columns: update(d.columns) }));
  };
  const patch = (uid: string, change: Partial<ColumnDraft>) =>
    setColumns((columns) => columns.map((c) => (c.uid === uid ? { ...c, ...change } : c)));
  const addColumn = () => {
    nextUid.current += 1;
    setColumns((columns) => {
      // New work-in-progress columns go before the first done/cancelled column.
      const firstClosed = columns.findIndex((c) => isClosedCategory(c.category));
      const at = firstClosed < 0 ? columns.length : firstClosed;
      return [...columns.slice(0, at), newColumnDraft(`new-${nextUid.current}`), ...columns.slice(at)];
    });
  };
  const busy = save.isPending || reset.isPending;

  return (
    <>
      <div className="flex-1 space-y-5 overflow-y-auto p-4">
        {workflow.inherited && (
          <p className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
            Saving gives this project its own columns; the shared ones stay as they are for
            everyone else.
          </p>
        )}

        <section aria-label="Columns">
          <div className="mb-2 grid grid-cols-[2rem_1fr_8.5rem_5.5rem_1.75rem] gap-1.5 px-2 text-xs font-medium text-slate-400">
            <span />
            <span>Column</span>
            <span>Category</span>
            <span>WIP limit</span>
            <span />
          </div>
          <ol className="space-y-1.5">
            {draft.columns.map((column, i) => {
              const display = column.name.trim() || `column ${i + 1}`;
              const closed = isClosedCategory(column.category);
              const renamedFrom =
                column.originalName &&
                column.name.trim() &&
                fold(column.originalName) !== fold(column.name)
                  ? column.originalName
                  : null;
              return (
                <li key={column.uid} className="rounded-md border border-slate-200 bg-white p-2">
                  <div className="grid grid-cols-[2rem_1fr_8.5rem_5.5rem_1.75rem] items-center gap-1.5">
                    <div className="flex flex-col items-center">
                      <button
                        type="button"
                        onClick={() => setColumns((cols) => moveColumn(cols, i, -1))}
                        disabled={i === 0}
                        aria-label={`Move ${display} earlier`}
                        className="rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                      >
                        <Icon name="chevron-up" size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => setColumns((cols) => moveColumn(cols, i, 1))}
                        disabled={i === draft.columns.length - 1}
                        aria-label={`Move ${display} later`}
                        className="rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                      >
                        <Icon name="chevron-down" size={14} />
                      </button>
                    </div>
                    <input
                      value={column.name}
                      maxLength={MAX_COLUMN_NAME}
                      onChange={(e) => patch(column.uid, { name: e.target.value })}
                      placeholder="Column name"
                      aria-label={`Name of column ${i + 1}`}
                      className={`${INPUT} min-w-0`}
                    />
                    <select
                      value={column.category}
                      onChange={(e) =>
                        patch(column.uid, { category: e.target.value as ColumnDraft["category"] })
                      }
                      aria-label={`Category of ${display}`}
                      className={INPUT}
                    >
                      {CATEGORY_ORDER.map((category) => (
                        <option key={category} value={category}>
                          {CATEGORY_LABELS[category]}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      min={1}
                      step={1}
                      inputMode="numeric"
                      value={closed ? "" : column.wipLimit}
                      disabled={closed}
                      onChange={(e) => patch(column.uid, { wipLimit: e.target.value })}
                      placeholder={closed ? "n/a" : "none"}
                      title={closed ? "Done and cancelled work doesn’t count toward WIP" : undefined}
                      aria-label={`WIP limit of ${display}`}
                      className={`${INPUT} w-full`}
                    />
                    <button
                      type="button"
                      onClick={() => setColumns((cols) => cols.filter((c) => c.uid !== column.uid))}
                      aria-label={`Remove ${display}`}
                      className="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-red-50 hover:text-red-600"
                    >
                      <Icon name="close" size={14} />
                    </button>
                  </div>
                  {renamedFrom && (
                    <p className="mt-1 pl-10 text-[11px] text-slate-400">
                      Renamed from “{renamedFrom}” — its cards follow.
                    </p>
                  )}
                </li>
              );
            })}
          </ol>
          <button
            type="button"
            onClick={addColumn}
            className="mt-2 flex items-center gap-1 rounded px-2 py-1 text-sm font-medium text-canopy-700 hover:bg-canopy-50"
          >
            <Icon name="plus" size={14} />
            Add column
          </button>
        </section>

        {removed.length > 0 && (
          <section
            aria-label="Removed columns"
            className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
          >
            <h3 className="font-medium">Removed columns</h3>
            <ul className="mt-1 space-y-1.5">
              {removed.map((name) => {
                const cards = occupied[fold(name)] ?? 0;
                return (
                  <li key={name} className="flex flex-wrap items-center gap-2">
                    {cards > 0 ? (
                      <>
                        <span>
                          “{name}” holds{" "}
                          {inUse.includes(name) && !occupiedColumns(board.lanes)[fold(name)]
                            ? "cards"
                            : `${cards} card${cards === 1 ? "" : "s"}`}
                          . Move them to
                        </span>
                        <select
                          value={moveTo[name] ?? ""}
                          onChange={(e) => setMoveTo((m) => ({ ...m, [name]: e.target.value }))}
                          aria-label={`Column for the cards in ${name}`}
                          className={INPUT}
                        >
                          <option value="">Choose a column…</option>
                          {draft.columns
                            .filter((c) => c.name.trim())
                            .map((c) => (
                              <option key={c.uid} value={c.uid}>
                                {c.name.trim()}
                              </option>
                            ))}
                        </select>
                      </>
                    ) : (
                      <span>“{name}” is empty and will be removed.</span>
                    )}
                  </li>
                );
              })}
            </ul>
            <p className="mt-2 text-xs text-amber-800">
              Mirrored cards keep their tracker’s status; a status the columns no longer name
              shows as an extra column.
            </p>
          </section>
        )}

        <label className="block text-sm">
          <span className="font-medium text-slate-700">WIP limits</span>
          <select
            value={draft.wipEnforcement}
            onChange={(e) =>
              setDraft((d) => ({ ...d, wipEnforcement: e.target.value as WipEnforcement }))
            }
            className={`${INPUT} mt-1 block w-full`}
          >
            {(Object.keys(ENFORCEMENT_LABELS) as WipEnforcement[]).map((value) => (
              <option key={value} value={value}>
                {ENFORCEMENT_LABELS[value]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <footer className="space-y-2 border-t border-slate-100 p-4">
        {problems.length > 0 && (
          <ul className="space-y-0.5 text-xs text-amber-800" aria-live="polite">
            {problems.map((problem) => (
              <li key={problem}>• {problem}</li>
            ))}
          </ul>
        )}
        {serverError && (
          <p role="alert" className="text-sm text-red-700">
            {serverError.message}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {canReset && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm(
                    "Drop this project’s own columns and use its team’s (or the workspace’s)? Cards keep their statuses — any the shared columns don’t have show as extra columns until moved.",
                  )
                ) {
                  reset.mutate();
                }
              }}
              className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            >
              {reset.isPending ? "Resetting…" : "Use team/workspace columns"}
            </button>
          )}
          <span className="ml-auto" />
          <button
            type="button"
            onClick={onDone}
            className="px-3 py-2 text-sm text-slate-500 hover:text-slate-700"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={busy || problems.length > 0}
            onClick={() => save.mutate(buildWorkflowUpdate(draft, removed, moveTo))}
            className="rounded bg-canopy-700 px-4 py-2 text-sm font-medium text-white hover:bg-canopy-500 disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : "Save columns"}
          </button>
        </div>
      </footer>
    </>
  );
}
