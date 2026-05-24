import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  ADR,
  ADRCommentKind,
  ADRDetail,
  Component,
  Connection,
  DecisionQueueResponse,
  Engineer,
  ImpactResponse,
  Reversibility,
} from "../api/types";
import { STATUS_LABELS, groupQueue, legalNextStatuses } from "../lib/decisions";
import { useCurrentUser } from "../lib/useCurrentUser";
import { canContribute, isPlanner } from "../lib/permissions";

const STATUS_BADGE: Record<string, string> = {
  proposed: "bg-slate-100 text-slate-600",
  under_discussion: "bg-blue-100 text-blue-700",
  accepted: "bg-emerald-100 text-emerald-700",
  rejected: "bg-red-100 text-red-700",
  superseded: "bg-amber-100 text-amber-700",
  deprecated: "bg-slate-200 text-slate-500",
  deferred: "bg-purple-100 text-purple-700",
};

const COMMENT_KINDS: { value: ADRCommentKind; label: string }[] = [
  { value: "comment", label: "Comment" },
  { value: "approve", label: "Approve" },
  { value: "request_changes", label: "Request changes" },
  { value: "reject", label: "Reject" },
];

const adrLabel = (n: number) => `ADR-${String(n).padStart(4, "0")}`;

export default function DecisionsView({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const { data: me } = useCurrentUser();
  const mayContribute = canContribute(me?.role);
  const mayImport = isPlanner(me?.role);

  const adrs = useQuery({
    queryKey: ["adrs", projectId],
    queryFn: () => api.get<ADR[]>(`/architecture/adrs?project_id=${projectId}`),
  });
  const components = useQuery({
    queryKey: ["components", projectId],
    queryFn: () => api.get<Component[]>(`/architecture/components?project_id=${projectId}`),
  });
  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });
  const queue = useQuery({
    queryKey: ["decision-queue", projectId],
    queryFn: () =>
      api.get<DecisionQueueResponse>(`/decisions/queue?project_id=${projectId}`),
  });

  const adrList = adrs.data ?? [];
  const comps = components.data ?? [];
  const engs = engineers.data ?? [];
  const engineerName = (id: number | null) =>
    id == null ? null : engs.find((e) => e.id === id)?.name ?? `#${id}`;
  const componentName = (id: number) => comps.find((c) => c.id === id)?.name ?? `#${id}`;

  const groups = groupQueue(queue.data?.items ?? []);

  return (
    <div className="space-y-5">
      <DecisionQueuePanel
        groups={groups}
        onPick={(id) => setSelectedId(id)}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <h2 className="font-semibold">Decisions</h2>
          {adrList.length === 0 && (
            <p className="text-sm text-slate-400">No decisions recorded yet.</p>
          )}
          <ul className="space-y-2">
            {adrList.map((a) => (
              <li key={a.id}>
                <button
                  onClick={() => setSelectedId(selectedId === a.id ? null : a.id)}
                  className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${
                    selectedId === a.id
                      ? "border-canopy-500 bg-canopy-50"
                      : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate">
                      <span className="font-mono text-xs text-slate-400">
                        {adrLabel(a.number)}
                      </span>{" "}
                      {a.title}
                    </span>
                    <span
                      className={`shrink-0 rounded px-2 py-0.5 text-xs ${
                        STATUS_BADGE[a.status] ?? "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {STATUS_LABELS[a.status]}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                    {a.reversibility && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5">
                        {a.reversibility === "one_way" ? "one-way door" : "two-way door"}
                      </span>
                    )}
                    {engineerName(a.decision_owner_id) && (
                      <span>owner: {engineerName(a.decision_owner_id)}</span>
                    )}
                    {a.decide_by && <span>decide by {a.decide_by}</span>}
                    {a.stakeholder_ids.length > 0 && (
                      <span>{a.stakeholder_ids.length} reviewer(s)</span>
                    )}
                  </div>
                </button>
                {selectedId === a.id && (
                  <AdrDetailPanel
                    adrId={a.id}
                    projectId={projectId}
                    engineers={engs}
                    componentName={componentName}
                    engineerName={engineerName}
                  />
                )}
              </li>
            ))}
          </ul>
        </div>

        {mayContribute && (
          <NewAdrForm
            projectId={projectId}
            adrs={adrList}
            components={comps}
            engineers={engs}
            onCreated={() => {
              qc.invalidateQueries({ queryKey: ["adrs", projectId] });
              qc.invalidateQueries({ queryKey: ["decision-queue", projectId] });
            }}
          />
        )}
      </div>

      {mayImport && (
        <ImportAdrForm
          projectId={projectId}
          onImported={() => qc.invalidateQueries({ queryKey: ["adrs", projectId] })}
        />
      )}
    </div>
  );
}

function ImportAdrForm({
  projectId,
  onImported,
}: {
  projectId: number;
  onImported: () => void;
}) {
  const [connId, setConnId] = useState<number | "">("");
  const [ref, setRef] = useState("");

  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<Connection[]>("/connectors/connections"),
  });
  const docConnections = (connections.data ?? []).filter(
    (c) => c.provider === "github" || c.provider === "gdrive",
  );

  const importAdr = useMutation({
    mutationFn: () => {
      const conn = docConnections.find((c) => c.id === connId);
      return api.post("/architecture/adrs/import", {
        project_id: projectId,
        provider: conn?.provider,
        connection_id: connId,
        ref,
      });
    },
    onSuccess: () => {
      setRef("");
      onImported();
    },
  });

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="mb-1 font-semibold">Import an ADR from a doc</h2>
      <p className="mb-2 text-xs text-slate-400">
        Parse a markdown ADR from a GitHub repo path or a Google Drive file into a decision.
      </p>
      <div className="flex flex-wrap gap-2">
        <select
          value={connId}
          onChange={(e) => setConnId(e.target.value ? Number(e.target.value) : "")}
          className="rounded border border-slate-300 px-2 py-2 text-sm"
        >
          <option value="">Source…</option>
          {docConnections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.provider}: {c.name}
            </option>
          ))}
        </select>
        <input
          value={ref}
          onChange={(e) => setRef(e.target.value)}
          placeholder="path/to/adr.md or Drive file id"
          className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={() => connId && ref && importAdr.mutate()}
          disabled={importAdr.isPending}
          className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-600 disabled:opacity-50"
        >
          Import
        </button>
      </div>
    </div>
  );
}

// --- Decision queue ----------------------------------------------------------

function DecisionQueuePanel({
  groups,
  onPick,
}: {
  groups: ReturnType<typeof groupQueue>;
  onPick: (id: number) => void;
}) {
  if (groups.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">
        Decision queue is clear — nothing needs triage.
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="mb-2 font-semibold">Decision queue</h2>
      <div className="space-y-3">
        {groups.map((g) => (
          <div key={g.meta.key}>
            <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
              {g.meta.label} · {g.meta.hint}
            </div>
            <ul className="mt-1 space-y-1">
              {g.items.map((it) => (
                <li key={it.id}>
                  <button
                    onClick={() => onPick(it.id)}
                    className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-sm hover:bg-slate-50"
                  >
                    {it.overdue && (
                      <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-700">
                        overdue
                      </span>
                    )}
                    <span className="font-mono text-xs text-slate-400">
                      {adrLabel(it.number)}
                    </span>
                    <span className="truncate">{it.title}</span>
                    <span className="ml-auto shrink-0 text-xs text-slate-400">
                      {it.reason}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- ADR detail (thread, lifecycle, blast radius) ----------------------------

function AdrDetailPanel({
  adrId,
  projectId,
  engineers,
  componentName,
  engineerName,
}: {
  adrId: number;
  projectId: number;
  engineers: Engineer[];
  componentName: (id: number) => string;
  engineerName: (id: number | null) => string | null;
}) {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const mayPlan = isPlanner(me?.role);
  const mayContribute = canContribute(me?.role);
  const [pendingStatus, setPendingStatus] = useState<ADR["status"] | "">("");
  const [decideBy, setDecideBy] = useState("");
  const [commentBody, setCommentBody] = useState("");
  const [commentKind, setCommentKind] = useState<ADRCommentKind>("comment");
  const [commentAuthor, setCommentAuthor] = useState<number | "">("");

  const detail = useQuery({
    queryKey: ["adr", adrId],
    queryFn: () => api.get<ADRDetail>(`/architecture/adrs/${adrId}`),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["adr", adrId] });
    qc.invalidateQueries({ queryKey: ["adrs", projectId] });
    qc.invalidateQueries({ queryKey: ["decision-queue", projectId] });
  };

  const transition = useMutation({
    mutationFn: (vars: { status: string; decide_by?: string }) =>
      api.patch(`/architecture/adrs/${adrId}`, vars),
    onSuccess: () => {
      setPendingStatus("");
      setDecideBy("");
      invalidate();
    },
  });

  const addComment = useMutation({
    mutationFn: () =>
      api.post(`/architecture/adrs/${adrId}/comments`, {
        body: commentBody,
        kind: commentKind,
        engineer_id: commentAuthor || null,
      }),
    onSuccess: () => {
      setCommentBody("");
      setCommentKind("comment");
      qc.invalidateQueries({ queryKey: ["adr", adrId] });
    },
  });

  const impact = useMutation({
    mutationFn: () => api.get<ImpactResponse>(`/architecture/adrs/${adrId}/impact`),
  });

  const components = useQuery({
    queryKey: ["components", projectId],
    queryFn: () => api.get<Component[]>(`/architecture/components?project_id=${projectId}`),
  });
  const [ffKind, setFfKind] = useState<"forbid" | "require">("forbid");
  const [ffSource, setFfSource] = useState<number | "">("");
  const [ffTarget, setFfTarget] = useState<number | "">("");
  const addFitness = useMutation({
    mutationFn: () =>
      api.post(`/architecture/adrs/${adrId}/fitness`, {
        kind: ffKind,
        source_component_id: ffSource,
        target_component_id: ffTarget,
      }),
    onSuccess: () => {
      setFfSource("");
      setFfTarget("");
      qc.invalidateQueries({ queryKey: ["adr", adrId] });
    },
  });
  const deleteFitness = useMutation({
    mutationFn: (id: number) => api.del(`/architecture/fitness/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["adr", adrId] }),
  });

  if (!detail.data) {
    return <div className="mt-1 px-3 py-2 text-xs text-slate-400">Loading decision…</div>;
  }
  const adr = detail.data;
  const status = (pendingStatus || adr.status) as ADR["status"];
  const canApply =
    pendingStatus !== "" &&
    pendingStatus !== adr.status &&
    (pendingStatus !== "deferred" || decideBy !== "");

  return (
    <div className="mt-1 space-y-3 rounded-lg border border-canopy-200 bg-white p-3 text-sm">
      {adr.context && <Section label="Context" body={adr.context} />}
      {adr.decision && <Section label="Decision" body={adr.decision} />}
      {adr.consequences && <Section label="Consequences" body={adr.consequences} />}
      {adr.alternatives.length > 0 && (
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Alternatives considered
          </div>
          <ul className="ml-4 list-disc text-slate-600">
            {adr.alternatives.map((alt, i) => (
              <li key={i}>{alt}</li>
            ))}
          </ul>
        </div>
      )}
      {adr.rfc_url && (
        <div className="text-xs">
          <span className="text-slate-400">RFC: </span>
          <a href={adr.rfc_url} className="text-canopy-700 underline" target="_blank" rel="noreferrer">
            {adr.rfc_url}
          </a>
        </div>
      )}

      {/* Lifecycle control — planners only */}
      {mayPlan && (
      <div className="flex flex-wrap items-center gap-2 rounded bg-slate-50 px-2 py-2">
        <span className="text-xs text-slate-400">Move to</span>
        <select
          value={pendingStatus || adr.status}
          onChange={(e) => setPendingStatus(e.target.value as ADR["status"])}
          className="rounded border border-slate-300 px-2 py-1 text-xs"
        >
          {legalNextStatuses(adr.status).map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
        {status === "deferred" && (
          <input
            type="date"
            value={decideBy}
            onChange={(e) => setDecideBy(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-xs"
          />
        )}
        <button
          disabled={!canApply || transition.isPending}
          onClick={() =>
            transition.mutate({
              status,
              decide_by: status === "deferred" ? decideBy : undefined,
            })
          }
          className="rounded bg-canopy-500 px-3 py-1 text-xs font-medium text-white disabled:opacity-40"
        >
          Apply
        </button>
        {transition.isError && (
          <span className="text-xs text-red-600">
            {(transition.error as Error).message}
          </span>
        )}
      </div>
      )}

      {/* Review summary */}
      <div className="flex flex-wrap gap-3 text-xs text-slate-600">
        <span>{adr.review.required} reviewer(s)</span>
        <span className="text-emerald-700">{adr.review.approved} approved</span>
        <span className="text-amber-700">{adr.review.changes_requested} changes</span>
        <span className="text-red-700">{adr.review.rejected} rejected</span>
        <span className="text-slate-400">{adr.review.pending} pending</span>
        <span
          className={`rounded px-2 py-0.5 ${
            adr.review.can_accept
              ? "bg-emerald-100 text-emerald-700"
              : "bg-slate-100 text-slate-500"
          }`}
        >
          {adr.review.can_accept ? "ready to accept" : "rule not yet met"}
        </span>
      </div>

      {/* Blast radius */}
      <div>
        <button
          onClick={() => impact.mutate()}
          disabled={impact.isPending}
          className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 disabled:opacity-50"
        >
          {impact.isPending ? "Computing…" : "Blast radius"}
        </button>
        {impact.data && (
          <div className="mt-1 space-y-1 text-xs text-slate-600">
            <div>
              Directly affects:{" "}
              {impact.data.direct_component_ids.map(componentName).join(", ") || "none"}
            </div>
            <div>
              Transitive dependents:{" "}
              {impact.data.downstream_component_ids.map(componentName).join(", ") || "none"}
            </div>
          </div>
        )}
      </div>

      {/* Fitness functions — machine-checkable rules the drift scan enforces */}
      <div className="space-y-1 border-t border-slate-100 pt-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Fitness functions
        </div>
        {adr.fitness_functions.length === 0 ? (
          <p className="text-xs text-slate-400">
            None. Add a dependency rule the Drift scan will enforce against the code.
          </p>
        ) : (
          <ul className="space-y-1 text-xs">
            {adr.fitness_functions.map((f) => (
              <li key={f.id} className="flex items-center gap-2">
                <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-600">
                  {componentName(f.source_component_id)}{" "}
                  {f.kind === "forbid" ? "-x->" : "-->"} {componentName(f.target_component_id)}
                </span>
                <span className="text-slate-400">
                  {f.kind === "forbid" ? "must not depend on" : "must depend on"}
                </span>
                {mayContribute && (
                  <button
                    onClick={() => deleteFitness.mutate(f.id)}
                    className="ml-auto text-slate-400 hover:text-red-600"
                  >
                    remove
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {mayContribute && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (ffSource && ffTarget && ffSource !== ffTarget) addFitness.mutate();
            }}
            className="flex flex-wrap items-center gap-1 pt-1 text-xs"
          >
            <select
              value={ffKind}
              onChange={(e) => setFfKind(e.target.value as "forbid" | "require")}
              className="rounded border border-slate-300 px-1 py-1"
            >
              <option value="forbid">forbid</option>
              <option value="require">require</option>
            </select>
            <select
              value={ffSource}
              onChange={(e) => setFfSource(e.target.value ? Number(e.target.value) : "")}
              className="rounded border border-slate-300 px-1 py-1"
            >
              <option value="">source…</option>
              {(components.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <select
              value={ffTarget}
              onChange={(e) => setFfTarget(e.target.value ? Number(e.target.value) : "")}
              className="rounded border border-slate-300 px-1 py-1"
            >
              <option value="">target…</option>
              {(components.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <button className="rounded bg-canopy-500 px-2 py-1 font-medium text-white">Add</button>
          </form>
        )}
      </div>

      {/* Comment thread */}
      <div className="space-y-2 border-t border-slate-100 pt-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Discussion
        </div>
        {adr.comments.length === 0 && (
          <p className="text-xs text-slate-400">No comments yet.</p>
        )}
        {adr.comments.map((c) => (
          <div key={c.id} className="rounded bg-slate-50 px-2 py-1">
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <span className="font-medium text-slate-600">
                {engineerName(c.engineer_id) ?? c.author_name ?? "someone"}
              </span>
              {c.kind !== "comment" && (
                <span
                  className={`rounded px-1.5 py-0.5 ${
                    c.kind === "approve"
                      ? "bg-emerald-100 text-emerald-700"
                      : c.kind === "reject"
                        ? "bg-red-100 text-red-700"
                        : "bg-amber-100 text-amber-700"
                  }`}
                >
                  {c.kind.replace("_", " ")}
                </span>
              )}
              <span>{new Date(c.created_at).toLocaleDateString()}</span>
            </div>
            <div className="text-slate-700">{c.body}</div>
          </div>
        ))}

        {mayContribute && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (commentBody.trim()) addComment.mutate();
          }}
          className="space-y-1"
        >
          <textarea
            value={commentBody}
            onChange={(e) => setCommentBody(e.target.value)}
            placeholder="Add to the discussion…"
            rows={2}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={commentKind}
              onChange={(e) => setCommentKind(e.target.value as ADRCommentKind)}
              className="rounded border border-slate-300 px-2 py-1 text-xs"
            >
              {COMMENT_KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
            <select
              value={commentAuthor}
              onChange={(e) => setCommentAuthor(e.target.value ? Number(e.target.value) : "")}
              className="rounded border border-slate-300 px-2 py-1 text-xs"
            >
              <option value="">As… (optional)</option>
              {engineers.map((eng) => (
                <option key={eng.id} value={eng.id}>
                  {eng.name}
                </option>
              ))}
            </select>
            <button className="ml-auto rounded bg-canopy-500 px-3 py-1 text-xs font-medium text-white">
              Post
            </button>
          </div>
        </form>
        )}
      </div>
    </div>
  );
}

function Section({ label, body }: { label: string; body: string }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</div>
      <div className="whitespace-pre-wrap text-slate-700">{body}</div>
    </div>
  );
}

// --- Propose / record a decision ---------------------------------------------

function NewAdrForm({
  projectId,
  adrs,
  components,
  engineers,
  onCreated,
}: {
  projectId: number;
  adrs: ADR[];
  components: Component[];
  engineers: Engineer[];
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const [context, setContext] = useState("");
  const [decision, setDecision] = useState("");
  const [consequences, setConsequences] = useState("");
  const [alternatives, setAlternatives] = useState("");
  const [reversibility, setReversibility] = useState<Reversibility | "">("");
  const [ownerId, setOwnerId] = useState<number | "">("");
  const [proposedById, setProposedById] = useState<number | "">("");
  const [stakeholderIds, setStakeholderIds] = useState<number[]>([]);
  const [supersedesId, setSupersedesId] = useState<number | "">("");
  const [componentIds, setComponentIds] = useState<number[]>([]);

  const create = useMutation({
    mutationFn: () =>
      api.post("/architecture/adrs", {
        project_id: projectId,
        title,
        context: context || null,
        decision: decision || null,
        consequences: consequences || null,
        alternatives: alternatives
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
        reversibility: reversibility || null,
        decision_owner_id: ownerId || null,
        proposed_by_id: proposedById || null,
        stakeholder_ids: stakeholderIds,
        supersedes_id: supersedesId || null,
        component_ids: componentIds,
      }),
    onSuccess: () => {
      setTitle("");
      setContext("");
      setDecision("");
      setConsequences("");
      setAlternatives("");
      setReversibility("");
      setOwnerId("");
      setProposedById("");
      setStakeholderIds([]);
      setSupersedesId("");
      setComponentIds([]);
      onCreated();
    },
  });

  const toggle = (list: number[], set: (v: number[]) => void, id: number) =>
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (title.trim()) create.mutate();
      }}
      className="space-y-2 rounded-lg border border-slate-200 bg-white p-4"
    >
      <h2 className="font-semibold">Propose / record a decision</h2>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Decision title (states the decision, not the topic)"
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
        placeholder="Decision"
        rows={2}
        className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
      />
      <textarea
        value={consequences}
        onChange={(e) => setConsequences(e.target.value)}
        placeholder="Consequences"
        rows={2}
        className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
      />
      <textarea
        value={alternatives}
        onChange={(e) => setAlternatives(e.target.value)}
        placeholder="Alternatives considered (one per line)"
        rows={2}
        className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
      />
      <div className="flex flex-wrap gap-2">
        <select
          value={reversibility}
          onChange={(e) => setReversibility(e.target.value as Reversibility | "")}
          className="rounded border border-slate-300 px-2 py-2 text-sm"
        >
          <option value="">Reversibility…</option>
          <option value="one_way">one-way door</option>
          <option value="two_way">two-way door</option>
        </select>
        <select
          value={ownerId}
          onChange={(e) => setOwnerId(e.target.value ? Number(e.target.value) : "")}
          className="rounded border border-slate-300 px-2 py-2 text-sm"
        >
          <option value="">Decision owner…</option>
          {engineers.map((eng) => (
            <option key={eng.id} value={eng.id}>
              {eng.name}
            </option>
          ))}
        </select>
        <select
          value={proposedById}
          onChange={(e) => setProposedById(e.target.value ? Number(e.target.value) : "")}
          className="rounded border border-slate-300 px-2 py-2 text-sm"
        >
          <option value="">Proposed by…</option>
          {engineers.map((eng) => (
            <option key={eng.id} value={eng.id}>
              {eng.name}
            </option>
          ))}
        </select>
        <select
          value={supersedesId}
          onChange={(e) => setSupersedesId(e.target.value ? Number(e.target.value) : "")}
          className="flex-1 rounded border border-slate-300 px-2 py-2 text-sm"
        >
          <option value="">Supersedes… (none)</option>
          {adrs.map((a) => (
            <option key={a.id} value={a.id}>
              {adrLabel(a.number)} {a.title}
            </option>
          ))}
        </select>
      </div>

      {engineers.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs text-slate-600">
          <span className="text-slate-400">Stakeholders (must review):</span>
          {engineers.map((eng) => (
            <label key={eng.id} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={stakeholderIds.includes(eng.id)}
                onChange={() => toggle(stakeholderIds, setStakeholderIds, eng.id)}
              />
              {eng.name}
            </label>
          ))}
        </div>
      )}

      {components.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs text-slate-600">
          <span className="text-slate-400">Affects:</span>
          {components.map((c) => (
            <label key={c.id} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={componentIds.includes(c.id)}
                onChange={() => toggle(componentIds, setComponentIds, c.id)}
              />
              {c.name}
            </label>
          ))}
        </div>
      )}

      <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
        Save decision
      </button>
    </form>
  );
}
