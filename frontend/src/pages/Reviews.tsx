import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Gate, Proposal, ProposalStatus } from "../api/types";
import { gateLabel, isParked, waitedPhrase } from "../lib/execution";
import { proposalShape, timeAgo } from "../lib/proposals";
import { featureOn, useFeatures } from "../lib/useFeatures";
import { PageHeader } from "../components/PageHeader";
import { Icon } from "../components/icons";

const STATUS_FILTERS: { key: ProposalStatus | "all"; label: string }[] = [
  { key: "open", label: "Awaiting review" },
  { key: "applied", label: "Applied" },
  { key: "rejected", label: "Rejected" },
  { key: "withdrawn", label: "Withdrawn" },
  { key: "all", label: "All" },
];

const STATUS_BADGE: Record<ProposalStatus, string> = {
  open: "bg-amber-100 text-amber-800",
  applied: "bg-emerald-100 text-emerald-700",
  rejected: "bg-red-100 text-red-700",
  withdrawn: "bg-slate-100 text-slate-500",
};

// Compact tint for the shape chips (create / update / resolve).
const SHAPE_TONE: Record<string, string> = {
  create: "text-emerald-600",
  update: "text-sky-600",
  resolve: "text-violet-600",
};

type Inbox = "changes" | "decisions";

/** The review inbox: **Changes** — staged proposals that only land once a person applies them
 *  (`/reviews/:id`) — and **Decisions** — agent work waiting on a person: plans to approve,
 *  questions to answer, parked tasks (`/reviews/gates/:id`). Each tab follows its feature gate
 *  (`ai.proposals`, `ai.work_queue`). */
export default function Reviews() {
  const features = useFeatures();
  const [params, setParams] = useSearchParams();
  const changesOn = featureOn(features, "ai.proposals");
  const decisionsOn = featureOn(features, "ai.work_queue");
  const requested = params.get("tab") as Inbox | null;
  const inbox: Inbox =
    requested === "decisions" && decisionsOn
      ? "decisions"
      : requested === "changes" && changesOn
        ? "changes"
        : changesOn
          ? "changes"
          : "decisions";
  const pick = (next: Inbox) => setParams(next === "changes" ? {} : { tab: next });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reviews"
        subtitle={
          inbox === "changes" ? (
            <>
              Changes staged by Claude (and teammates) that only land after <em>you</em> review
              and apply them. Open one to see what it does to the plan as a whole, then go
              through the changes one by one.
            </>
          ) : (
            <>
              Agent work waiting on a person: plans to approve, questions to answer, tasks
              sessions couldn’t finish. Nothing here is ever decided by a timeout — the work
              waits for you.
            </>
          )
        }
      />
      {changesOn && decisionsOn && (
        <div role="tablist" aria-label="Review inbox" className="flex gap-1 border-b border-slate-200">
          {(
            [
              ["changes", "Changes"],
              ["decisions", "Decisions"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={inbox === key}
              onClick={() => pick(key)}
              className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${
                inbox === key
                  ? "border-canopy-500 font-medium text-canopy-700"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      {inbox === "changes" ? <ChangesInbox /> : <DecisionsInbox />}
    </div>
  );
}

function ChangesInbox() {
  const [status, setStatus] = useState<ProposalStatus | "all">("open");
  const proposals = useQuery({
    queryKey: ["proposals", status],
    queryFn: () =>
      api.get<Proposal[]>(status === "all" ? "/proposals" : `/proposals?status=${status}`),
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setStatus(f.key)}
            className={`rounded-full px-3 py-1 text-sm ${
              status === f.key
                ? "bg-canopy-500 text-white"
                : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {proposals.isLoading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : proposals.data?.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
          {status === "open"
            ? "Nothing awaits review. Staged changes from Claude sessions will appear here."
            : "No proposals with this status."}
        </div>
      ) : (
        <ul className="space-y-3">
          {(proposals.data ?? []).map((p) => (
            <li key={p.id}>
              <ProposalRow proposal={p} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const GATE_FILTERS: { key: "mine" | "open" | "all"; label: string }[] = [
  { key: "mine", label: "Waiting on me" },
  { key: "open", label: "All open" },
  { key: "all", label: "All" },
];

function DecisionsInbox() {
  const [filter, setFilter] = useState<"mine" | "open" | "all">("mine");
  const gates = useQuery({
    queryKey: ["gates", filter],
    queryFn: () =>
      api.get<Gate[]>(
        filter === "mine" ? "/gates?mine=true" : filter === "open" ? "/gates" : "/gates?status=all",
      ),
  });
  const rows = [...(gates.data ?? [])].sort((a, b) =>
    a.status === b.status ? b.age_hours - a.age_hours : a.status === "open" ? -1 : 1,
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2">
        {GATE_FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`rounded-full px-3 py-1 text-sm ${
              filter === f.key
                ? "bg-canopy-500 text-white"
                : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>
      {gates.isLoading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : rows.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
          {filter === "mine"
            ? "Nothing is waiting on you. When an agent needs a decision you can make, it shows up here."
            : "No decisions here."}
        </div>
      ) : (
        <ul className="space-y-3">
          {rows.map((g) => (
            <li key={g.id}>
              <GateRow gate={g} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function GateRow({ gate: g }: { gate: Gate }) {
  const parked = isParked(g);
  const open = g.status === "open";
  return (
    <Link
      to={`/reviews/gates/${g.id}`}
      className="group block rounded-lg border border-slate-200 bg-white px-4 py-3 hover:border-canopy-500/50 hover:shadow-sm"
    >
      <div className="flex items-center gap-2">
        <span
          className={`rounded px-1.5 py-0.5 text-xs font-medium ${
            !open
              ? "bg-slate-100 text-slate-500"
              : parked
                ? "bg-red-100 text-red-700"
                : "bg-amber-100 text-amber-800"
          }`}
        >
          {gateLabel(g)}
        </span>
        {g.task_key && (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">
            {g.task_key}
          </span>
        )}
        <span className="truncate font-medium group-hover:text-canopy-700">{g.title}</span>
        <span className="ml-auto flex shrink-0 items-center gap-2 text-xs text-slate-400">
          {open ? (
            <span title="How long it has waited">waiting {waitedPhrase(g.age_hours)}</span>
          ) : (
            <span>{g.status.replaceAll("_", " ")}</span>
          )}
          {open && g.may_decide && <span className="font-medium text-canopy-700">Decide</span>}
          <Icon name="chevron-right" size={14} className="text-slate-300" />
        </span>
      </div>
      <p className="mt-1.5 text-xs text-slate-400">
        {g.task_name}
        {g.project_key ? ` · ${g.project_key}` : ""}
        {g.requester_name ? ` · asked by ${g.requester_name}'s agent` : ""}
        {g.escalation_level > 0 ? ` · escalated` : ""}
        {g.waiting_for_evidence ? " · approved, waiting for the PR" : ""}
      </p>
    </Link>
  );
}

function ProposalRow({ proposal: p }: { proposal: Proposal }) {
  return (
    <Link
      to={`/reviews/${p.id}`}
      className="group block rounded-lg border border-slate-200 bg-white px-4 py-3 hover:border-canopy-500/50 hover:shadow-sm"
    >
      <div className="flex items-center gap-2">
        <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${STATUS_BADGE[p.status]}`}>
          {p.status}
        </span>
        {p.scope_label && (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">
            {p.scope_label}
          </span>
        )}
        <span className="truncate font-medium group-hover:text-canopy-700">{p.title}</span>
        {p.attention_count > 0 && (
          <span
            className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800"
            title="Some changes errored or the plan moved since they were staged — look before applying."
          >
            ⚠ {p.attention_count} need{p.attention_count === 1 ? "s" : ""} attention
          </span>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-2 text-xs text-slate-400">
          {/* The change's shape at a glance (create / update / resolve). */}
          {proposalShape(p.action_counts).map((c) => (
            <span key={c.action} className={`font-medium tabular-nums ${SHAPE_TONE[c.action]}`}>
              {c.glyph}
              {c.count}
            </span>
          ))}
          <span>
            {p.item_count} change{p.item_count === 1 ? "" : "s"}
          </span>
          <Icon name="chevron-right" size={14} className="text-slate-300" />
        </span>
      </div>
      {p.summary && <p className="mt-1.5 line-clamp-2 text-sm text-slate-600">{p.summary}</p>}
      <p className="mt-1.5 text-xs text-slate-400">
        Staged {timeAgo(p.created_at)}
        {p.created_by ? ` by ${p.created_by}` : ""}
        {p.origin ? ` · ${p.origin}` : ""}
        {p.revision > 1 ? ` · revision ${p.revision}, updated ${timeAgo(p.revised_at)}` : ""}
        {p.status === "rejected" && p.review_note ? ` · “${p.review_note}”` : ""}
      </p>
    </Link>
  );
}
