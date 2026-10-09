import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  ADR,
  InitiativeRollup,
  LeadershipNote,
  LeadershipNoteKind,
  LeadershipScope,
  LeadershipTargetKind,
  Outcome,
  RiskItem,
} from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";

/**
 * Leadership notes on one view (USER_FLOWS §BR): the executive layer leaves something to watch,
 * a priority call, or feedback — optionally pinned to a decision / risk / outcome inside the
 * scope — and the lead team acknowledges / resolves it with a response. Reads are open to all.
 */
export default function LeadershipNotesPanel({
  scope,
  scopeId,
  canRespond,
  compact = false,
}: {
  scope: LeadershipScope;
  scopeId: number;
  /** The current user leads this scope (may acknowledge / resolve). */
  canRespond: boolean;
  compact?: boolean;
}) {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const mayWrite = me?.role === "admin" || me?.function === "leadership";

  const notes = useQuery({
    queryKey: ["leadership-notes", scope, scopeId],
    queryFn: () =>
      api.get<LeadershipNote[]>(`/leadership/notes?scope_level=${scope}&scope_id=${scopeId}`),
  });
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["leadership-notes", scope, scopeId] });
    qc.invalidateQueries({ queryKey: ["business-review"] });
  };

  const [adding, setAdding] = useState(false);
  const [kind, setKind] = useState<LeadershipNoteKind>("feedback");
  const [priority, setPriority] = useState<number>(2);
  const [body, setBody] = useState("");
  const [target, setTarget] = useState<string>("");

  // Finer targets the note can point at: the scope's decisions, risks and outcomes. For an
  // initiative, decisions are the ADRs of its sub-projects (rollup → project ids).
  const rollup = useQuery({
    queryKey: ["initiative-rollup", scopeId],
    queryFn: () => api.get<InitiativeRollup>(`/initiatives/${scopeId}/rollup`),
    enabled: adding && scope === "initiative",
  });
  const projectIds =
    scope === "project" ? [scopeId] : (rollup.data?.projects ?? []).map((p) => p.id);
  const decisions = useQuery({
    queryKey: ["leadership-targets", "decisions", scope, scopeId, projectIds],
    queryFn: async () => {
      const lists = await Promise.all(
        projectIds.map((pid) => api.get<ADR[]>(`/architecture/adrs?project_id=${pid}`)),
      );
      return lists.flat();
    },
    enabled: adding && projectIds.length > 0,
  });
  const risks = useQuery({
    queryKey: ["leadership-targets", "risks", scope, scopeId],
    queryFn: () => api.get<RiskItem[]>(`/risks?scope_level=${scope}&scope_id=${scopeId}`),
    enabled: adding,
  });
  const outcomes = useQuery({
    queryKey: ["leadership-targets", "outcomes", scope, scopeId],
    queryFn: () => api.get<Outcome[]>(`/outcomes?scope_level=${scope}&scope_id=${scopeId}`),
    enabled: adding,
  });

  const create = useMutation({
    mutationFn: () => {
      const [tk, tid] = target ? target.split(":") : [null, null];
      return api.post<LeadershipNote>("/leadership/notes", {
        scope_level: scope,
        scope_id: scopeId,
        kind,
        priority: kind === "priority" ? priority : null,
        body,
        target_kind: (tk as LeadershipTargetKind | null) ?? null,
        target_id: tid ? Number(tid) : null,
      });
    },
    onSuccess: () => {
      setBody("");
      setTarget("");
      setAdding(false);
      invalidate();
    },
  });
  const respond = useMutation({
    mutationFn: (vars: { id: number; status: "acknowledged" | "resolved"; response: string }) =>
      api.patch<LeadershipNote>(`/leadership/notes/${vars.id}`, {
        status: vars.status,
        response: vars.response || undefined,
      }),
    onSuccess: invalidate,
  });

  const list = notes.data ?? [];
  const open = list.filter((n) => n.status !== "resolved");
  const resolved = list.filter((n) => n.status === "resolved");

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-semibold">
          Leadership notes{" "}
          <span className="ml-1 text-xs font-normal text-slate-400">
            watch · priority · feedback from leadership
          </span>
        </h2>
        {mayWrite && !adding && (
          <button
            onClick={() => setAdding(true)}
            className="rounded border border-canopy-500 px-3 py-1 text-xs font-medium text-canopy-700"
          >
            Leave a note
          </button>
        )}
      </div>

      {adding && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (body.trim()) create.mutate();
          }}
          className="mb-3 space-y-2 rounded border border-slate-200 bg-slate-50 p-3"
        >
          <div className="flex flex-wrap gap-2">
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as LeadershipNoteKind)}
              className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
            >
              <option value="watch">Watch</option>
              <option value="priority">Priority</option>
              <option value="feedback">Feedback</option>
            </select>
            {kind === "priority" && (
              <select
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
                className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
              >
                <option value={1}>P1</option>
                <option value={2}>P2</option>
                <option value={3}>P3</option>
              </select>
            )}
            <select
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="min-w-64 flex-1 rounded border border-slate-300 bg-white px-2 py-1 text-sm"
            >
              <option value="">Regarding: this {scope} overall</option>
              {(decisions.data ?? []).map((d) => (
                <option key={`d${d.id}`} value={`decision:${d.id}`}>
                  Decision — {d.title}
                </option>
              ))}
              {(risks.data ?? []).map((r) => (
                <option key={`r${r.id}`} value={`risk:${r.id}`}>
                  Risk — {r.title}
                </option>
              ))}
              {(outcomes.data ?? []).map((o) => (
                <option key={`o${o.id}`} value={`outcome:${o.id}`}>
                  Outcome — {o.statement}
                </option>
              ))}
            </select>
          </div>
          <textarea
            autoFocus
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="What should the lead team know or do?"
            rows={2}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={create.isPending || !body.trim()}
              className="rounded bg-canopy-500 px-3 py-1 text-sm font-medium text-white disabled:opacity-50"
            >
              {create.isPending ? "Saving…" : "Post note"}
            </button>
            <button
              type="button"
              onClick={() => setAdding(false)}
              className="px-2 py-1 text-sm text-slate-500"
            >
              Cancel
            </button>
            {create.isError && (
              <span className="self-center text-xs text-red-600">
                {(create.error as Error).message}
              </span>
            )}
          </div>
        </form>
      )}

      {notes.isLoading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : list.length === 0 ? (
        <p className="text-sm text-slate-400">
          No leadership notes yet{mayWrite ? " — leave the first one." : "."}
        </p>
      ) : (
        <ul className="space-y-2">
          {[...open, ...(compact ? [] : resolved)].map((n) => (
            <NoteRow
              key={n.id}
              note={n}
              canRespond={canRespond}
              onRespond={(status, response) => respond.mutate({ id: n.id, status, response })}
            />
          ))}
          {compact && resolved.length > 0 && (
            <li className="text-xs text-slate-400">{resolved.length} resolved</li>
          )}
        </ul>
      )}
    </section>
  );
}

const KIND_STYLE: Record<LeadershipNoteKind, string> = {
  watch: "bg-sky-100 text-sky-700",
  priority: "bg-red-100 text-red-700",
  feedback: "bg-violet-100 text-violet-700",
};

export function NoteBadge({ note }: { note: LeadershipNote }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${KIND_STYLE[note.kind]}`}>
      {note.kind === "priority" && note.priority ? `P${note.priority} priority` : note.kind}
    </span>
  );
}

function NoteRow({
  note,
  canRespond,
  onRespond,
}: {
  note: LeadershipNote;
  canRespond: boolean;
  onRespond: (status: "acknowledged" | "resolved", response: string) => void;
}) {
  const [replying, setReplying] = useState(false);
  const [response, setResponse] = useState(note.response ?? "");
  const resolved = note.status === "resolved";
  return (
    <li
      className={`rounded border px-3 py-2 ${
        resolved ? "border-slate-100 bg-slate-50 text-slate-500" : "border-slate-200 bg-white"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <NoteBadge note={note} />
        {note.target_label && (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">
            re: {note.target_label}
          </span>
        )}
        <span>
          {note.author_name ?? "leadership"} · {note.created_at.slice(0, 10)}
        </span>
        <span
          className={`ml-auto rounded px-1.5 py-0.5 ${
            note.status === "open"
              ? "bg-amber-100 text-amber-700"
              : note.status === "acknowledged"
                ? "bg-canopy-100 text-canopy-700"
                : "bg-slate-200 text-slate-600"
          }`}
        >
          {note.status}
        </span>
      </div>
      <p className="mt-1 text-sm">{note.body}</p>
      {note.response && (
        <p className="mt-1 border-l-2 border-canopy-300 pl-2 text-sm text-slate-600">
          <span className="text-xs text-slate-400">
            {note.responded_by_name ?? "lead team"} replied:
          </span>{" "}
          {note.response}
        </p>
      )}
      {canRespond && !resolved && (
        <div className="mt-2">
          {replying ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                onRespond("acknowledged", response);
                setReplying(false);
              }}
              className="flex flex-wrap gap-2"
            >
              <input
                autoFocus
                value={response}
                onChange={(e) => setResponse(e.target.value)}
                placeholder="Your response to leadership"
                className="min-w-64 flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
              />
              <button
                type="submit"
                className="rounded bg-canopy-500 px-3 py-1 text-xs font-medium text-white"
              >
                Acknowledge
              </button>
              <button
                type="button"
                onClick={() => {
                  onRespond("resolved", response);
                  setReplying(false);
                }}
                className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700"
              >
                Resolve
              </button>
              <button
                type="button"
                onClick={() => setReplying(false)}
                className="px-2 py-1 text-xs text-slate-500"
              >
                Cancel
              </button>
            </form>
          ) : (
            <button
              onClick={() => setReplying(true)}
              className="text-xs font-medium text-canopy-700 hover:underline"
            >
              {note.status === "open" ? "Respond" : "Update response"}
            </button>
          )}
        </div>
      )}
    </li>
  );
}
