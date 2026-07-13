import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  DecisionQueueResponse,
  Engineer,
  Project,
  Reversibility,
} from "../api/types";
import { groupQueue } from "../lib/decisions";
import { PageHeader } from "../components/PageHeader";
import { PreviewLink } from "../components/PreviewLink";

const adrLabel = (n: number) => `ADR-${String(n).padStart(4, "0")}`;

export default function Decisions() {
  const qc = useQueryClient();

  const queue = useQuery({
    queryKey: ["decision-queue", "all"],
    queryFn: () => api.get<DecisionQueueResponse>("/decisions/queue"),
  });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<Project[]>("/projects"),
  });
  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });

  const projectKey = (id: number) =>
    (projects.data ?? []).find((p) => p.id === id)?.key ?? `#${id}`;
  const groups = groupQueue(queue.data?.items ?? []);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Decisions"
        subtitle="The team-wide decision queue — proposals awaiting triage, decisions stuck in discussion, and deferred decisions coming due, across every project."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          {groups.length === 0 ? (
            <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">
              Nothing needs a decision right now.
            </div>
          ) : (
            <div className="space-y-4">
              {groups.map((g) => (
                <div key={g.meta.key} className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-400">
                    {g.meta.label} · {g.meta.hint}
                  </div>
                  <ul className="space-y-1">
                    {g.items.map((it) => (
                      <li key={it.id}>
                        <PreviewLink
                          target={{ kind: "project", id: it.project_id, tab: "decisions" }}
                          className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-slate-50"
                        >
                          {it.overdue && (
                            <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-700">
                              overdue
                            </span>
                          )}
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">
                            {projectKey(it.project_id)}
                          </span>
                          <span className="font-mono text-xs text-slate-400">
                            {adrLabel(it.number)}
                          </span>
                          <span className="truncate">{it.title}</span>
                          <span className="ml-auto shrink-0 text-xs text-slate-400">
                            {it.reason}
                          </span>
                        </PreviewLink>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>

        <ProposeForm
          projects={projects.data ?? []}
          engineers={engineers.data ?? []}
          onProposed={() => qc.invalidateQueries({ queryKey: ["decision-queue", "all"] })}
        />
      </div>
    </div>
  );
}

function ProposeForm({
  projects,
  engineers,
  onProposed,
}: {
  projects: Project[];
  engineers: Engineer[];
  onProposed: () => void;
}) {
  const [projectId, setProjectId] = useState<number | "">("");
  const [title, setTitle] = useState("");
  const [context, setContext] = useState("");
  const [decision, setDecision] = useState("");
  const [proposedById, setProposedById] = useState<number | "">("");
  const [reversibility, setReversibility] = useState<Reversibility | "">("");

  const propose = useMutation({
    mutationFn: () =>
      api.post("/architecture/adrs", {
        project_id: projectId,
        title,
        context: context || null,
        decision: decision || null,
        proposed_by_id: proposedById || null,
        reversibility: reversibility || null,
        status: "proposed",
      }),
    onSuccess: () => {
      setTitle("");
      setContext("");
      setDecision("");
      setReversibility("");
      onProposed();
    },
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (projectId && title.trim()) propose.mutate();
      }}
      className="space-y-2 rounded-lg border border-slate-200 bg-white p-4"
    >
      <h2 className="font-semibold">Propose a decision</h2>
      <p className="text-xs text-slate-400">
        Raise a decision for the owner to triage. It lands in <em>proposed</em>.
      </p>
      <select
        value={projectId}
        onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : "")}
        className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
      >
        <option value="">Project…</option>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.key} — {p.name}
          </option>
        ))}
      </select>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Decision title"
        className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
      />
      <textarea
        value={context}
        onChange={(e) => setContext(e.target.value)}
        placeholder="Context / forces"
        rows={2}
        className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
      />
      <textarea
        value={decision}
        onChange={(e) => setDecision(e.target.value)}
        placeholder="Proposed decision"
        rows={2}
        className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
      />
      <div className="flex gap-2">
        <select
          value={proposedById}
          onChange={(e) => setProposedById(e.target.value ? Number(e.target.value) : "")}
          className="flex-1 rounded border border-slate-300 px-2 py-2 text-sm"
        >
          <option value="">Proposed by…</option>
          {engineers.map((eng) => (
            <option key={eng.id} value={eng.id}>
              {eng.name}
            </option>
          ))}
        </select>
        <select
          value={reversibility}
          onChange={(e) => setReversibility(e.target.value as Reversibility | "")}
          className="rounded border border-slate-300 px-2 py-2 text-sm"
        >
          <option value="">Reversibility…</option>
          <option value="one_way">one-way door</option>
          <option value="two_way">two-way door</option>
        </select>
      </div>
      <button
        disabled={propose.isPending}
        className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {propose.isPending ? "Proposing…" : "Propose"}
      </button>
    </form>
  );
}
