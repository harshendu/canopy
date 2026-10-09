import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Initiative, InitiativeAccess, Project, Team } from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";
import { canWriteProjects, isPlanner } from "../lib/permissions";
import {
  groupByOwnership,
  groupByTeam,
  leadTeamLabel,
  leadsFor,
  podsForInitiative,
  teamSeatsLabel,
} from "../lib/initiativeAccess";
import { PageHeader } from "../components/PageHeader";
import { PreviewLink } from "../components/PreviewLink";

export default function Initiatives() {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [outcome, setOutcome] = useState("");
  const [target, setTarget] = useState("");
  const { data: me } = useCurrentUser();
  const mayCreate = canWriteProjects(me?.role);

  const { data: initiatives = [], isLoading } = useQuery({
    queryKey: ["initiatives"],
    queryFn: () => api.get<Initiative[]>("/initiatives"),
  });
  // Ownership (§R6): which initiatives the current user leads, plus every lead team.
  const access = useQuery({
    queryKey: ["initiative-access"],
    queryFn: () => api.get<InitiativeAccess>("/initiatives/access"),
  });
  // Org model (§R6): teams → pods; an initiative spans the pods of its projects.
  const teams = useQuery({ queryKey: ["teams"], queryFn: () => api.get<Team[]>("/teams") });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<Project[]>("/projects"),
  });
  const grouped = groupByOwnership(initiatives, access.data?.led_initiative_ids);
  // A planner who owns something sees "Initiatives I own" first; everyone sees the teams.
  const showOwned = isPlanner(me?.role) && grouped.led.length > 0;
  const byTeam = groupByTeam(showOwned ? grouped.others : initiatives, teams.data ?? []);
  const editable = new Set(access.data?.editable_initiative_ids ?? []);
  const podsOf = (id: number) => podsForInitiative(id, projects.data ?? [], teams.data ?? []);
  const teamName = (id: number | null | undefined) =>
    (teams.data ?? []).find((t) => t.id === id)?.name ?? null;
  const planner = isPlanner(me?.role);

  const create = useMutation({
    mutationFn: () =>
      api.post<Initiative>("/initiatives", {
        key,
        name,
        outcome_statement: outcome || null,
        target_date: target || null,
      }),
    onSuccess: () => {
      setKey("");
      setName("");
      setOutcome("");
      setTarget("");
      qc.invalidateQueries({ queryKey: ["initiatives"] });
    },
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Initiatives"
        subtitle="A program spanning multiple projects executed concurrently. Open one to roll up health across its sub-projects."
      />

      {mayCreate && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (key && name) create.mutate();
          }}
          className="grid grid-cols-1 gap-2 rounded-lg border border-slate-200 bg-white p-4 md:grid-cols-2"
        >
          <div className="flex gap-2">
            <input
              value={key}
              onChange={(e) => setKey(e.target.value.toUpperCase())}
              placeholder="KEY"
              className="w-36 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Initiative name"
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div className="flex gap-2">
            <input
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
              placeholder="Outcome statement (optional)"
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <input
              type="date"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="rounded border border-slate-300 px-2 py-2 text-sm"
            />
            <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
              Add
            </button>
          </div>
        </form>
      )}

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : (
        <>
          {showOwned && (
            <InitiativeList
              title="Initiatives I own"
              hint="you are an owner — full planning controls"
              items={grouped.led}
              leads={access.data?.leads}
              podsOf={podsOf}
              teamName={teamName}
              mode={() => "owner"}
            />
          )}
          {byTeam.map((g) => (
            <InitiativeList
              key={g.team?.id ?? "none"}
              title={g.team ? `${g.team.name} team` : "No team"}
              hint={
                g.team
                  ? [teamSeatsLabel(g.team.members), `Pods: ${g.team.pods.map((p) => p.name).join(", ")}`]
                      .filter(Boolean)
                      .join(" · ")
                  : undefined
              }
              items={g.initiatives}
              leads={access.data?.leads}
              podsOf={podsOf}
              mode={(i) => (!planner ? "none" : editable.has(i.id) ? "editable" : "read-only")}
            />
          ))}
        </>
      )}
    </div>
  );
}

type RowMode = "owner" | "editable" | "read-only" | "none";

function InitiativeList({
  title,
  hint,
  items,
  leads,
  podsOf,
  teamName,
  mode,
}: {
  title: string;
  hint?: string;
  items: Initiative[];
  leads: InitiativeAccess["leads"] | undefined;
  podsOf: (id: number) => string[];
  teamName?: (id: number | null | undefined) => string | null;
  mode: (i: Initiative) => RowMode;
}) {
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        {title}
        {hint && (
          <span className="ml-2 text-xs font-normal normal-case tracking-normal text-slate-400">
            {hint}
          </span>
        )}
      </h2>
      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {items.map((i) => {
          const owners = leadTeamLabel(leadsFor(leads, i.id));
          const pods = podsOf(i.id);
          const m = mode(i);
          const team = teamName?.(i.team_id);
          return (
            <li key={i.id}>
              <PreviewLink
                target={{ kind: "initiative", id: i.id }}
                className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-slate-50"
              >
                <span className="min-w-0">
                  <span className="font-mono text-xs text-slate-400">{i.key}</span>{" "}
                  <span className="font-medium">{i.name}</span>
                  {i.outcome_statement && (
                    <span className="ml-2 text-sm text-slate-400">{i.outcome_statement}</span>
                  )}
                  <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                    {team && <span className="text-slate-400">{team} ·</span>}
                    {pods.map((p) => (
                      <span key={p} className="rounded bg-canopy-50 px-1.5 py-0.5 text-canopy-700">
                        {p} pod
                      </span>
                    ))}
                    {pods.length > 1 && <span className="text-slate-400">spans pods ·</span>}
                    {owners && <span>Owners: {owners}</span>}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-2 text-xs text-slate-400">
                  {m === "owner" && (
                    <span className="rounded bg-canopy-100 px-1.5 py-0.5 font-medium text-canopy-700">
                      owner
                    </span>
                  )}
                  {m === "editable" && (
                    <span className="rounded bg-canopy-50 px-1.5 py-0.5 text-canopy-700">
                      editable
                    </span>
                  )}
                  {m === "read-only" && (
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-500">
                      read-only
                    </span>
                  )}
                  {i.target_date ? `target ${i.target_date}` : "no target"}
                </span>
              </PreviewLink>
            </li>
          );
        })}
        {items.length === 0 && (
          <li className="px-4 py-6 text-center text-sm text-slate-400">
            No initiatives yet — create one above, then link projects to it.
          </li>
        )}
      </ul>
    </section>
  );
}
