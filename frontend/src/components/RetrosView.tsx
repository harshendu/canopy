import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Retrospective, RetrospectiveDetail } from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";
import { canContribute, isPlanner } from "../lib/permissions";

export default function RetrosView({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const mayManage = isPlanner(me?.role);
  const mayComment = canContribute(me?.role);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const retros = useQuery({
    queryKey: ["retros", projectId],
    queryFn: () => api.get<Retrospective[]>(`/projects/${projectId}/retrospectives`),
  });

  const create = useMutation({
    mutationFn: (kind: string) =>
      api.post<Retrospective>(`/projects/${projectId}/retrospectives`, { kind }),
    onSuccess: (r) => {
      setSelectedId(r.id);
      qc.invalidateQueries({ queryKey: ["retros", projectId] });
    },
  });

  const list = retros.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Retrospectives & postmortems</h2>
        {mayManage && (
          <div className="flex gap-2">
            <button
              onClick={() => create.mutate("project_retro")}
              disabled={create.isPending}
              className="rounded bg-canopy-500 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              New retrospective
            </button>
            <button
              onClick={() => create.mutate("incident_postmortem")}
              disabled={create.isPending}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-600 disabled:opacity-50"
            >
              New postmortem
            </button>
          </div>
        )}
      </div>

      {list.length === 0 ? (
        <p className="text-sm text-slate-400">
          None yet. A retrospective auto-seeds from this project's milestones, schedule variance,
          drift, and ADR churn.
        </p>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
          {list.map((r) => (
            <li key={r.id}>
              <button
                onClick={() => setSelectedId(selectedId === r.id ? null : r.id)}
                className={`flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-slate-50 ${
                  selectedId === r.id ? "bg-canopy-50" : ""
                }`}
              >
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                  {r.kind === "incident_postmortem" ? "postmortem" : "retro"}
                </span>
                <span className="truncate">{r.title}</span>
                {r.status === "closed" && (
                  <span className="ml-auto text-xs text-slate-400">closed</span>
                )}
              </button>
              {selectedId === r.id && (
                <RetroDetail
                  projectId={projectId}
                  retroId={r.id}
                  mayManage={mayManage}
                  mayComment={mayComment}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RetroDetail({
  projectId,
  retroId,
  mayManage,
  mayComment,
}: {
  projectId: number;
  retroId: number;
  mayManage: boolean;
  mayComment: boolean;
}) {
  const qc = useQueryClient();
  const base = `/projects/${projectId}/retrospectives/${retroId}`;
  const [comment, setComment] = useState("");
  const [followTitle, setFollowTitle] = useState("");

  const detail = useQuery({
    queryKey: ["retro", retroId],
    queryFn: () => api.get<RetrospectiveDetail>(base),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["retro", retroId] });
    qc.invalidateQueries({ queryKey: ["retros", projectId] });
  };

  const addComment = useMutation({
    mutationFn: () => api.post(`${base}/comments`, { body: comment }),
    onSuccess: () => {
      setComment("");
      qc.invalidateQueries({ queryKey: ["retro", retroId] });
    },
  });
  const followUp = useMutation({
    mutationFn: (action: string) => api.post(`${base}/follow-up`, { action, title: followTitle }),
    onSuccess: () => {
      setFollowTitle("");
      qc.invalidateQueries({ queryKey: ["tasks", projectId] });
      qc.invalidateQueries({ queryKey: ["adrs", projectId] });
    },
  });
  const close = useMutation({
    mutationFn: () => api.patch(base, { status: "closed" }),
    onSuccess: invalidate,
  });

  if (!detail.data) {
    return <div className="px-4 py-2 text-xs text-slate-400">Loading…</div>;
  }
  const r = detail.data;

  return (
    <div className="space-y-3 border-t border-slate-100 bg-white px-4 py-3 text-sm">
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-3 text-xs text-slate-700">
        {r.body}
      </pre>

      {mayManage && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={followTitle}
            onChange={(e) => setFollowTitle(e.target.value)}
            placeholder="Follow-up title…"
            className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
          />
          <button
            onClick={() => followTitle.trim() && followUp.mutate("task")}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:border-canopy-500"
          >
            Mint task
          </button>
          <button
            onClick={() => followTitle.trim() && followUp.mutate("adr")}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:border-canopy-500"
          >
            Propose ADR
          </button>
          {r.status !== "closed" && (
            <button
              onClick={() => close.mutate()}
              className="ml-auto rounded border border-slate-300 px-2 py-1 text-xs text-slate-600"
            >
              Close
            </button>
          )}
        </div>
      )}

      <div className="space-y-1">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Discussion
        </div>
        {r.comments.length === 0 && <p className="text-xs text-slate-400">No comments yet.</p>}
        {r.comments.map((c) => (
          <div key={c.id} className="rounded bg-slate-50 px-2 py-1 text-xs">
            <span className="font-medium text-slate-600">
              {c.author_name ?? (c.engineer_id ? `engineer #${c.engineer_id}` : "someone")}
            </span>
            <span className="ml-2 text-slate-400">{new Date(c.created_at).toLocaleDateString()}</span>
            <div className="text-slate-700">{c.body}</div>
          </div>
        ))}
        {mayComment && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (comment.trim()) addComment.mutate();
            }}
            className="flex gap-2"
          >
            <input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Add a comment…"
              className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
            />
            <button className="rounded bg-canopy-500 px-3 py-1 text-xs font-medium text-white">
              Post
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
