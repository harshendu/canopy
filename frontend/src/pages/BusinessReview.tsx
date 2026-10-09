import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { BusinessReview as BusinessReviewData, ReviewInitiative } from "../api/types";
import { NoteBadge } from "../components/LeadershipNotesPanel";
import ExportMenu from "../components/ExportMenu";
import { PageHeader } from "../components/PageHeader";
import { PreviewLink } from "../components/PreviewLink";
import { QueryError } from "../components/QueryError";
import type { Team } from "../api/types";
import { leadTeamLabel, teamSeatsLabel } from "../lib/initiativeAccess";
import { riskTone } from "../lib/risk";
import { featureOn, useFeatures } from "../lib/useFeatures";

/**
 * The monthly business review (USER_FLOWS §BR): every initiative with its lead team, headline
 * health, outcomes and the leadership notes still open — the executive team's one page, and
 * the leadership persona's landing. Read-only here; notes are left on the initiative itself.
 */
export default function BusinessReview() {
  const { data: features = {} } = useFeatures();
  const review = useQuery({
    queryKey: ["business-review"],
    queryFn: () => api.get<BusinessReviewData>("/leadership/review"),
  });

  if (review.isLoading) {
    return <div className="p-2 text-sm text-slate-400">Loading…</div>;
  }
  if (review.isError || !review.data) {
    return <QueryError label="Couldn’t load the business review" error={review.error} />;
  }
  const r = review.data;
  const behind = r.initiatives.filter((i) => i.on_track === false).length;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Business review"
        subtitle={`Every initiative by team — its pods, owners, outcomes and the leadership notes still open — as of ${r.generated_on}.`}
        actions={
          featureOn(features, "reporting.exports") ? (
            <ExportMenu scope="portfolio" />
          ) : undefined
        }
      />

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
          <Stat label="initiatives" value={r.initiatives.length} />
          <Stat label="behind target" value={behind} tone={behind ? "text-red-700" : undefined} />
          <Stat
            label="open leadership notes"
            value={r.open_note_count}
            tone={r.open_note_count ? "text-amber-700" : undefined}
          />
        </div>
        <h2 className="mt-3 font-semibold">Needs attention</h2>
        {r.attention.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing is flagged — every initiative is on track.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {r.attention.map((line) => (
              <li key={line} className="flex gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />
                {line}
              </li>
            ))}
          </ul>
        )}
      </section>

      {teamSections(r.teams, r.initiatives).map((sec) => (
        <section key={sec.team?.id ?? "none"} className="space-y-3">
          <div>
            <h2 className="text-lg font-semibold">
              {sec.team ? `${sec.team.name} team` : "Other initiatives"}
            </h2>
            {sec.team && (
              <p className="text-xs text-slate-500">
                {[
                  teamSeatsLabel(sec.team.members),
                  sec.team.pods.length
                    ? `Pods: ${sec.team.pods.map((p) => p.name).join(", ")}`
                    : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            )}
          </div>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {sec.initiatives.map((i) => (
              <InitiativeCard key={i.id} i={i} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/** Initiatives grouped under their team (team order kept; teamless last). */
function teamSections(
  teams: Team[],
  initiatives: ReviewInitiative[],
): { team: Team | null; initiatives: ReviewInitiative[] }[] {
  const out: { team: Team | null; initiatives: ReviewInitiative[] }[] = teams
    .map((team) => ({ team, initiatives: initiatives.filter((i) => i.team_id === team.id) }))
    .filter((s) => s.initiatives.length > 0);
  const known = new Set(teams.map((t) => t.id));
  const rest = initiatives.filter((i) => i.team_id == null || !known.has(i.team_id));
  if (rest.length) out.push({ team: null, initiatives: rest });
  return out;
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <span>
      <span className={`text-lg font-semibold tabular-nums ${tone ?? ""}`}>{value}</span>{" "}
      <span className="text-slate-500">{label}</span>
    </span>
  );
}

function InitiativeCard({ i }: { i: ReviewInitiative }) {
  const risk = riskTone(i.risk_level);
  const openNotes = i.open_notes.filter((n) => n.status !== "resolved");
  const team = leadTeamLabel(i.leads);
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <PreviewLink target={{ kind: "initiative", id: i.id }} className="hover:underline">
            <span className="font-mono text-xs text-slate-400">{i.key}</span>{" "}
            <span className="text-lg font-semibold">{i.name}</span>
          </PreviewLink>
          {i.outcome_statement && (
            <p className="mt-0.5 text-sm text-slate-500">{i.outcome_statement}</p>
          )}
          <p className="mt-1 text-xs text-slate-500">
            {i.pods.length > 0 && (
              <>
                {i.pods.join(" + ")} pod{i.pods.length > 1 ? "s" : ""} ·{" "}
              </>
            )}
            {team ? <>Owners: {team}</> : "No owners seated"}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {i.on_track != null && (
            <span
              className={`rounded px-2 py-0.5 text-xs font-medium ${
                i.on_track ? "bg-canopy-100 text-canopy-700" : "bg-red-100 text-red-700"
              }`}
            >
              {i.on_track ? "on track" : "behind target"}
            </span>
          )}
          {i.health && (
            <span className="rounded bg-slate-100 px-2 py-0.5 text-xs capitalize text-slate-600">
              {i.health.replace("_", " ")}
            </span>
          )}
        </div>
      </div>

      {i.status_note && <p className="text-sm text-slate-700">{i.status_note}</p>}

      <div className="grid grid-cols-3 gap-2 text-center sm:grid-cols-6">
        <Tile label="Progress" value={`${Math.round(i.avg_percent_complete)}%`} />
        <Tile label="Projects" value={String(i.project_count)} />
        <Tile label="Risk" value={String(i.risk_score)} hint={i.risk_level} tone={risk.badge} />
        <Tile label="Drift" value={String(i.drift_score)} hint={i.drift_level} />
        <Tile label="Decisions" value={String(i.open_decisions)} hint="open" />
        <Tile label="Blockers" value={String(i.open_blockers)} hint="open" />
      </div>

      {i.outcomes.length > 0 && (
        <ul className="space-y-1 text-sm">
          {i.outcomes.map((o) => (
            <li key={o.id} className="flex items-center justify-between gap-2">
              <span className="truncate">{o.statement}</span>
              <span className="shrink-0 text-xs text-slate-500">
                {o.current_value ?? "—"} / {o.target_value ?? "—"} {o.unit ?? ""} ·{" "}
                <span
                  className={
                    o.status === "at_risk" || o.status === "invalidated"
                      ? "text-red-700"
                      : "text-canopy-700"
                  }
                >
                  {o.status.replace("_", " ")}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}

      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Leadership notes {openNotes.length > 0 && `· ${openNotes.length} open`}
        </h3>
        {openNotes.length === 0 ? (
          <p className="text-xs text-slate-400">None open.</p>
        ) : (
          <ul className="mt-1 space-y-1">
            {openNotes.map((n) => (
              <li key={n.id} className="text-sm">
                <NoteBadge note={n} />{" "}
                {n.target_label && <span className="text-slate-500">re: {n.target_label} — </span>}
                {n.body}
                {n.response && (
                  <span className="text-slate-500"> · reply: {n.response}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function Tile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className={`rounded border border-slate-100 px-2 py-1.5 ${tone ?? ""}`}>
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-base font-semibold tabular-nums">{value}</div>
      {hint && <div className="text-[10px] capitalize text-slate-400">{hint}</div>}
    </div>
  );
}
