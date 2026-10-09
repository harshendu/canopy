import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  ForecastResponse,
  InitiativeCriticalPath,
  InitiativeDigest,
  InitiativeRollup,
} from "../api/types";
import { riskTone } from "../lib/risk";
import ExportMenu from "../components/ExportMenu";
import DeliveryView from "../components/DeliveryView";
import DocsView from "../components/DocsView";
import OutcomesPanel from "../components/OutcomesPanel";
import DeliveryMetaBar from "../components/DeliveryMetaBar";
import RiskRegister from "../components/RiskRegister";
import LeadershipNotesPanel from "../components/LeadershipNotesPanel";
import { leadTeamLabel } from "../lib/initiativeAccess";
import JiraLinksPanel from "../components/JiraLinksPanel";
import { PageHeader } from "../components/PageHeader";
import { PreviewLink } from "../components/PreviewLink";
import { QueryError } from "../components/QueryError";
import { Icon } from "../components/icons";
import { useCurrentUser } from "../lib/useCurrentUser";
import { canWriteProjects, isPlanner } from "../lib/permissions";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-bold tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-400">{hint}</div>}
    </div>
  );
}

export default function InitiativeView() {
  const { initiativeId } = useParams();
  const id = Number(initiativeId);
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();

  const rollup = useQuery({
    queryKey: ["initiative-rollup", id],
    queryFn: () => api.get<InitiativeRollup>(`/initiatives/${id}/rollup`),
  });
  const criticalPath = useQuery({
    queryKey: ["initiative-critical-path", id],
    queryFn: () => api.get<InitiativeCriticalPath>(`/initiatives/${id}/critical-path`),
  });
  const forecast = useQuery({
    queryKey: ["initiative-forecast", id],
    queryFn: () => api.get<ForecastResponse>(`/initiatives/${id}/forecast`),
  });
  const digest = useQuery({
    queryKey: ["initiative-digest", id],
    queryFn: () => api.get<InitiativeDigest>(`/initiatives/${id}/digest`),
  });
  const [copied, setCopied] = useState(false);
  const copyDigest = async () => {
    if (!digest.data) return;
    try {
      await navigator.clipboard.writeText(digest.data.markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false); // clipboard unavailable/denied — don't lie about success (see BUG-13)
    }
  };

  if (rollup.isError) {
    return (
      <div className="space-y-4">
        <Link to="/initiatives" className="text-sm text-emerald-700 hover:underline">
          ← Back to initiatives
        </Link>
        <QueryError
          error={rollup.error}
          onRetry={() => void rollup.refetch()}
          label="Couldn’t load this initiative"
        />
      </div>
    );
  }
  if (!rollup.data) {
    return <p className="text-sm text-slate-500">Loading initiative…</p>;
  }
  const r = rollup.data;
  // Ownership (§R6): planning controls only for this initiative's lead team (or admin).
  const canEdit = r.can_edit;
  const mayWriteInitiative = canWriteProjects(me?.role) && canEdit;
  const mayPlan = isPlanner(me?.role) && canEdit;
  const leadTeam = leadTeamLabel(r.leads);
  const cp = criticalPath.data;
  const fc = forecast.data;
  const risk = riskTone(r.risk_level);
  const drift = riskTone(r.drift_level);

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[
          { label: "Initiatives", to: "/initiatives" },
          { label: r.initiative.name },
        ]}
        title={r.initiative.name}
        titleAdornment={
          <>
            <span className="font-mono text-xs text-slate-400">{r.initiative.key}</span>
            {r.on_track != null && (
              <span
                className={`rounded px-2 py-0.5 text-xs font-medium ${
                  r.on_track ? "bg-canopy-100 text-canopy-700" : "bg-red-100 text-red-700"
                }`}
              >
                {r.on_track ? "on track" : "behind target"}
              </span>
            )}
          </>
        }
        subtitle={r.initiative.outcome_statement || undefined}
        actions={
          <>
            <Link
              to={`/initiatives/${id}/scenarios`}
              className="inline-flex items-center gap-1.5 rounded border border-slate-300 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
            >
              <Icon name="scenarios" size={15} />
              Scenarios
            </Link>
            <ExportMenu scope="initiative" id={id} />
          </>
        }
      />

      {!canEdit && isPlanner(me?.role) && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-600">
          <span className="rounded bg-slate-200 px-1.5 py-0.5 text-xs font-medium text-slate-700">
            read-only
          </span>
          You have full visibility of this initiative; planning changes are made by its owners
          {leadTeam ? <> — {leadTeam}.</> : "."}
        </div>
      )}
      {(r.team_name || r.pods.length > 0 || leadTeam) && (
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
          {r.team_name && <span className="text-slate-700">{r.team_name} team</span>}
          {r.pods.map((p) => (
            <span key={p} className="rounded bg-canopy-50 px-1.5 py-0.5 text-canopy-700">
              {p} pod
            </span>
          ))}
          {r.pods.length > 1 && <span>spans pods</span>}
          {leadTeam && (
            <span>
              · Owners: <span className="text-slate-700">{leadTeam}</span>
            </span>
          )}
        </p>
      )}

      <DeliveryMetaBar
        scope="initiative"
        id={id}
        health={r.initiative.health}
        statusNote={r.initiative.status_note}
        tags={r.initiative.tags}
        mayWrite={mayWriteInitiative}
        onSaved={() => qc.invalidateQueries({ queryKey: ["initiative-rollup", id] })}
      />

      {/* Manage-by-exception digest (§R5) — leads with what needs attention, reusing the same
          rollup + forecast the stat grid below shows in full. Was MCP/API-only; now in the UI. */}
      {digest.data && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2">
              <Icon name="alerts" size={16} />
              <h2 className="font-semibold">{digest.data.headline}</h2>
            </div>
            <button
              onClick={() => void copyDigest()}
              className="shrink-0 rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              {copied ? "Copied ✓" : "Copy digest"}
            </button>
          </div>
          {digest.data.attention.length > 0 ? (
            <ul className="mt-2 space-y-1">
              {digest.data.attention.map((a, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-slate-700">
                  <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-amber-500" />
                  {a}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 flex items-center gap-1.5 text-sm text-slate-500">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              Nothing needs attention this week.
            </p>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Stat
          label="Progress"
          value={`${r.avg_percent_complete}%`}
          hint={`${r.completed_tasks}/${r.total_tasks} tasks`}
        />
        <div className={`rounded-lg border p-4 ${risk.badge}`}>
          <div className="text-xs uppercase tracking-wide opacity-70">Risk (worst)</div>
          <div className="mt-1 text-2xl font-bold tabular-nums">{r.risk_score}</div>
          <div className="mt-0.5 text-xs capitalize opacity-80">{r.risk_level}</div>
        </div>
        <div className={`rounded-lg border p-4 ${drift.badge}`}>
          <div className="text-xs uppercase tracking-wide opacity-70">Drift (worst)</div>
          <div className="mt-1 text-2xl font-bold tabular-nums">{r.drift_score}</div>
          <div className="mt-0.5 text-xs capitalize opacity-80">{r.drift_level}</div>
        </div>
        <Stat label="Open decisions" value={String(r.open_decisions)} hint="proposed / in discussion" />
        <Stat
          label="Latest end (CPM)"
          value={r.project_end ?? "—"}
          hint={r.initiative.target_date ? `target ${r.initiative.target_date}` : "no target"}
        />
        <Stat
          label="Forecast (P85)"
          value={fc?.sufficient ? fc.p85_date ?? "—" : "—"}
          hint={
            fc?.sufficient
              ? `P50 ${fc.p50_date}`
              : "needs throughput history"
          }
        />
      </div>

      {cp && cp.tasks.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center gap-2">
            <h2 className="font-semibold">Cross-project critical path</h2>
            <span className="text-xs text-slate-400">{cp.total_working_days} working days</span>
            {cp.spans_projects && (
              <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                {cp.handoffs.length} cross-project hand-off
                {cp.handoffs.length === 1 ? "" : "s"}
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            The longest chain of dependent work across the initiative. Hand-offs between projects
            (amber) are where it most often slips.
          </p>
          <ol className="mt-3 flex flex-wrap items-center gap-1">
            {cp.tasks.map((t, idx) => {
              const handoff = idx > 0 && cp.tasks[idx - 1].project_key !== t.project_key;
              return (
                <li key={t.task_id} className="flex items-center gap-1">
                  {idx > 0 && (
                    <span className={handoff ? "text-amber-500" : "text-slate-300"}>→</span>
                  )}
                  <span
                    className={`rounded border px-2 py-1 text-xs ${
                      handoff
                        ? "border-amber-300 bg-amber-50"
                        : "border-slate-200 bg-slate-50"
                    }`}
                    title={`${t.duration} working day(s)`}
                  >
                    <span className="font-mono text-[10px] text-slate-400">{t.project_key}</span>{" "}
                    {t.name}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      )}

      <LeadershipNotesPanel scope="initiative" scopeId={id} canRespond={canEdit} />

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <OutcomesPanel scope="initiative" scopeId={id} mayWrite={mayPlan} />
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <DeliveryView scope="initiative" id={id} />
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <RiskRegister scope="initiative" scopeId={id} mayWrite={mayPlan} />
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <DocsView scope="initiative" scopeId={id} mayWrite={mayPlan} />
      </div>

      <div>
        <h2 className="mb-2 font-semibold">Sub-projects</h2>
        {r.projects.length === 0 ? (
          <p className="text-sm text-slate-500">
            No projects linked yet — assign projects to this initiative on the Projects page.
          </p>
        ) : (
          <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {r.projects.map((p) => (
              <li key={p.id}>
                <PreviewLink
                  target={{ kind: "project", id: p.id }}
                  className="block rounded-lg border border-slate-200 bg-white p-4 hover:bg-slate-50"
                >
                  <div className="flex items-center justify-between">
                    <span>
                      <span className="font-mono text-xs text-slate-400">{p.key}</span>{" "}
                      <span className="font-medium">{p.name}</span>
                    </span>
                    <span className="flex gap-1">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${riskTone(p.risk_level).badge}`}
                      >
                        risk {p.risk_score}
                      </span>
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${riskTone(p.drift_level).badge}`}
                      >
                        drift {p.drift_score}
                      </span>
                    </span>
                  </div>
                  {(p.pod_name || p.owner_name) && (
                    <div className="mt-1 text-xs text-slate-500">
                      {p.pod_name && <span>{p.pod_name} pod</span>}
                      {p.pod_name && p.owner_name && " · "}
                      {p.owner_name && <span>Owner: {p.owner_name}</span>}
                    </div>
                  )}
                  <div className="mt-2 text-xs text-slate-400">
                    {p.avg_percent_complete}% · {p.completed_tasks}/{p.total_tasks} tasks ·{" "}
                    {p.critical_tasks} critical · {p.project_end ? `ends ${p.project_end}` : "unscheduled"}
                  </div>
                </PreviewLink>
              </li>
            ))}
          </ul>
        )}
      </div>

      <JiraLinksPanel targetType="initiative" targetId={id} />
    </div>
  );
}
