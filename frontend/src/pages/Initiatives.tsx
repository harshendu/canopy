import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Initiative, InitiativeAccess } from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";
import { canWriteProjects, isPlanner } from "../lib/permissions";
import { groupByOwnership, leadTeamLabel, leadsFor } from "../lib/initiativeAccess";
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
  const grouped = groupByOwnership(initiatives, access.data?.led_initiative_ids);
  // A planner who leads something sees the split; everyone else sees one list.
  const split = isPlanner(me?.role) && grouped.led.length > 0;

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
      ) : split ? (
        <>
          <InitiativeList
            title="Initiatives I lead"
            hint="your core team owns these — full planning controls"
            items={grouped.led}
            leads={access.data?.leads}
          />
          <InitiativeList
            title="Other initiatives"
            hint="read-only — complete visibility, no edits outside your lead team"
            items={grouped.others}
            leads={access.data?.leads}
            readOnly
          />
        </>
      ) : (
        <InitiativeList items={initiatives} leads={access.data?.leads} />
      )}
    </div>
  );
}

function InitiativeList({
  title,
  hint,
  items,
  leads,
  readOnly = false,
}: {
  title?: string;
  hint?: string;
  items: Initiative[];
  leads: InitiativeAccess["leads"] | undefined;
  readOnly?: boolean;
}) {
  return (
    <section className="space-y-2">
      {title && (
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          {title}
          {hint && <span className="ml-2 font-normal normal-case tracking-normal">{hint}</span>}
        </h2>
      )}
      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {items.map((i) => {
          const team = leadTeamLabel(leadsFor(leads, i.id));
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
                  {team && <span className="mt-0.5 block text-xs text-slate-400">{team}</span>}
                </span>
                <span className="flex shrink-0 items-center gap-2 text-xs text-slate-400">
                  {readOnly && (
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
            {title
              ? "Nothing here."
              : "No initiatives yet — create one above, then link projects to it."}
          </li>
        )}
      </ul>
    </section>
  );
}
