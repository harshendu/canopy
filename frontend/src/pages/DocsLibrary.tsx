import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  ArtifactSyncStatus,
  DesignDoc,
  DocProvider,
  DocReviewStatus,
  DocStage,
  Initiative,
  Project,
  Team,
} from "../api/types";
import { DocRow } from "../components/DocsView";
import DocDetailPanel from "../components/DocDetailPanel";
import { PageHeader } from "../components/PageHeader";
import {
  ATTENTION_FLAGS,
  PROVIDER_LABEL,
  STAGES,
  STATUS_LABEL,
  docErrorMessage,
  docTitle,
  sortDocs,
  stageLabel,
  syncSummary,
} from "../lib/docs";
import { isPlanner } from "../lib/permissions";
import { useCurrentUser } from "../lib/useCurrentUser";

const STATUSES: (DocReviewStatus | "untracked")[] = [
  "approved",
  "in_review",
  "draft",
  "untracked",
  "superseded",
  "archived",
];

/** Every shared design doc across the workspace (USER_FLOWS §V11): filter by team, review
 *  status, where it lives and lifecycle stage, or show only the docs that need a person. Each
 *  row opens the doc's detail; writes stay where the doc is filed (its project's Docs tab).
 *  Personal docs live in My work. */
export default function DocsLibrary() {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const [teamId, setTeamId] = useState<number | "">("");
  const [status, setStatus] = useState<DocReviewStatus | "untracked" | "">("");
  const [provider, setProvider] = useState<DocProvider | "">("");
  const [stage, setStage] = useState<DocStage | "">("");
  const [attention, setAttention] = useState(false);
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);

  const query = new URLSearchParams({ personal: "false" });
  if (teamId !== "") query.set("team_id", String(teamId));
  if (status) query.set("review_status", status);
  if (provider) query.set("provider", provider);
  if (stage) query.set("stage", stage);
  const docs = useQuery({
    queryKey: ["docs", "library", teamId, status, provider, stage],
    queryFn: () => api.get<DesignDoc[]>(`/docs?${query.toString()}`),
  });
  const teams = useQuery({ queryKey: ["teams"], queryFn: () => api.get<Team[]>("/teams") });
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
  const initiatives = useQuery({
    queryKey: ["initiatives"],
    queryFn: () => api.get<Initiative[]>("/initiatives"),
    retry: false, // portfolio.initiatives may be gated off
  });
  const sync = useQuery({
    queryKey: ["artifact-sync"],
    queryFn: () => api.get<ArtifactSyncStatus>("/docs/artifact-sync"),
  });

  const runSync = useMutation({
    mutationFn: (connectionId: number) => api.post(`/connectors/connections/${connectionId}/sync`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["docs"] });
      void qc.invalidateQueries({ queryKey: ["artifact-sync"] });
    },
  });

  const homes = useMemo(() => {
    const out = new Map<string, string>();
    for (const p of projects.data ?? []) out.set(`project:${p.id}`, p.key);
    for (const i of initiatives.data ?? []) out.set(`initiative:${i.id}`, i.key);
    return out;
  }, [projects.data, initiatives.data]);
  const homeOf = (d: DesignDoc): string | undefined =>
    d.scope_level && d.scope_id !== null ? homes.get(`${d.scope_level}:${d.scope_id}`) : undefined;

  const needle = search.trim().toLowerCase();
  const rows = sortDocs(docs.data ?? []).filter(
    (d) =>
      (!attention || (d.health ?? []).some((f) => ATTENTION_FLAGS.has(f.flag))) &&
      (!needle || docTitle(d).toLowerCase().includes(needle) || d.kind.includes(needle)),
  );
  const kindCount = new Set(rows.map((d) => d.kind)).size;
  const syncStatus = sync.data;
  const report = syncStatus?.last_sync ?? null;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Design docs"
        subtitle="Every shared design doc across the workspace — Claude docs and artifacts, Drive, Figma, repo files. canopy links them, it never stores them."
      />

      {syncStatus?.available && (
        <div className="flex flex-wrap items-center gap-2 rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <span className="font-medium">Claude organization sync</span>
          <span>{report ? syncSummary(report) : "has not run yet."}</span>
          {isPlanner(me?.role) && syncStatus.connection_id != null && (
            <button
              onClick={() => runSync.mutate(syncStatus.connection_id as number)}
              disabled={runSync.isPending}
              className="ml-auto rounded border border-slate-300 bg-white px-2 py-0.5 disabled:opacity-50"
            >
              {runSync.isPending ? "Syncing…" : "Sync now"}
            </button>
          )}
          {runSync.isError && <span className="w-full text-red-600">{docErrorMessage(runSync.error)}</span>}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <select
          value={teamId}
          onChange={(e) => setTeamId(e.target.value ? Number(e.target.value) : "")}
          className="rounded border border-slate-300 px-2 py-1"
          aria-label="Filter by team"
        >
          <option value="">Every team</option>
          {(teams.data ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as DocReviewStatus | "untracked" | "")}
          className="rounded border border-slate-300 px-2 py-1"
          aria-label="Filter by review status"
        >
          <option value="">Any status</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s === "untracked" ? "Plain links" : STATUS_LABEL[s]}
            </option>
          ))}
        </select>
        <select
          value={provider}
          onChange={(e) => setProvider(e.target.value as DocProvider | "")}
          className="rounded border border-slate-300 px-2 py-1"
          aria-label="Filter by where the doc lives"
        >
          <option value="">Anywhere</option>
          {(Object.keys(PROVIDER_LABEL) as DocProvider[]).map((p) => (
            <option key={p} value={p}>
              {PROVIDER_LABEL[p]}
            </option>
          ))}
        </select>
        <select
          value={stage}
          onChange={(e) => setStage(e.target.value as DocStage | "")}
          className="rounded border border-slate-300 px-2 py-1"
          aria-label="Filter by lifecycle stage"
        >
          <option value="">Any stage</option>
          {STAGES.map((s) => (
            <option key={s} value={s}>
              {stageLabel(s)}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1 text-slate-600">
          <input type="checkbox" checked={attention} onChange={(e) => setAttention(e.target.checked)} />
          Needs attention
        </label>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search titles"
          className="ml-auto w-48 rounded border border-slate-300 px-2 py-1"
          aria-label="Search titles"
        />
      </div>

      {docs.isLoading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : docs.isError ? (
        <p className="text-sm text-red-600">{docErrorMessage(docs.error)}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-500">No docs match.</p>
      ) : (
        <>
          <p className="text-xs text-slate-400">
            {rows.length} {rows.length === 1 ? "doc" : "docs"} across {kindCount}{" "}
            {kindCount === 1 ? "kind" : "kinds"}
          </p>
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white text-sm">
            {rows.map((d) => (
              <DocRow
                key={d.id}
                doc={d}
                home={homeOf(d)}
                open={open === d.id}
                onToggle={() => setOpen(open === d.id ? null : d.id)}
                onDetail={() => setDetailId(d.id)}
              />
            ))}
          </ul>
        </>
      )}
      {detailId !== null && (
        <DocDetailPanel docId={detailId} mayWrite={isPlanner(me?.role)} onClose={() => setDetailId(null)} />
      )}
    </div>
  );
}
