import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Task, TaskMoveResponse } from "../api/types";
import { applyOptimisticMove, toMoveRequest, type Board, type CardMove } from "./board";

/** Every card move shares this key, so the board refetches only once the last one settles. */
export const MOVE_CARD_KEY = ["move-card"] as const;

/** Called for every move — unlike callbacks passed to `mutate`, which TanStack Query runs only
 *  for the latest of several moves in flight. */
export interface MoveCardHandlers {
  onSuccess?: (res: TaskMoveResponse, move: CardMove) => void;
  /** Read the refusal with `trackingFailure`. The optimistic move is already rolled back. */
  onError?: (err: Error, move: CardMove) => void;
  onSettled?: (move: CardMove) => void;
}

interface MoveContext {
  board?: Board;
  task?: Task;
}

/**
 * Move a card (`POST /tasks/{id}/move`) — the one status write path, shared by drag and drop,
 * the card's "Move to…" menu and the task drawer's status select. The board cached at
 * `boardKey` (and the task, when cached) shows the move at once and rolls back if the server
 * refuses. The board refetches when the last in-flight move settles, so a refetch never
 * clobbers another pending move.
 */
export function useMoveCard(boardKey: QueryKey, handlers: MoveCardHandlers = {}) {
  const qc = useQueryClient();
  return useMutation<TaskMoveResponse, Error, CardMove, MoveContext>({
    mutationKey: MOVE_CARD_KEY,
    mutationFn: (move) =>
      api.post<TaskMoveResponse>(`/tasks/${move.taskId}/move`, toMoveRequest(move)),
    onMutate: async (move) => {
      const taskKey = ["task", move.taskId];
      await Promise.all([
        qc.cancelQueries({ queryKey: boardKey }),
        qc.cancelQueries({ queryKey: taskKey }),
      ]);
      const board = qc.getQueryData<Board>(boardKey);
      if (board) qc.setQueryData<Board>(boardKey, applyOptimisticMove(board, move));
      const task = qc.getQueryData<Task>(taskKey);
      const toStatus = move.to_status;
      if (task && toStatus !== undefined) {
        qc.setQueryData<Task>(taskKey, { ...task, status: toStatus });
      }
      return { board, task };
    },
    onSuccess: (res, move) => {
      qc.setQueryData<Task>(["task", res.task.id], res.task);
      handlers.onSuccess?.(res, move);
    },
    onError: (err, move, context) => {
      if (context?.board) qc.setQueryData(boardKey, context.board);
      if (context?.task) qc.setQueryData(["task", move.taskId], context.task);
      handlers.onError?.(err, move);
    },
    onSettled: (_res, err, move) => {
      if (qc.isMutating({ mutationKey: MOVE_CARD_KEY }) === 1) {
        void qc.invalidateQueries({ queryKey: boardKey });
      }
      // A refusal such as `stale` means our copy of the task is out of date.
      if (err) void qc.invalidateQueries({ queryKey: ["task", move.taskId] });
      // A move into or out of done changes progress — the Gantt and task list show it.
      if (move.projectId != null) {
        void qc.invalidateQueries({ queryKey: ["gantt", move.projectId] });
        void qc.invalidateQueries({ queryKey: ["tasks", move.projectId] });
      }
      handlers.onSettled?.(move);
    },
  });
}
