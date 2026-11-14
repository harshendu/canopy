import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Proposal, ProposalStatus } from "../api/types";
import { proposalShape, timeAgo } from "../lib/proposals";
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

/** The review queue: every staged proposal as a scannable row. Opening one goes to its
 *  review workspace (`/reviews/:id`) — plan first, then the change-by-change list. */
export default function Reviews() {
  const [status, setStatus] = useState<ProposalStatus | "all">("open");
  const proposals = useQuery({
    queryKey: ["proposals", status],
    queryFn: () =>
      api.get<Proposal[]>(status === "all" ? "/proposals" : `/proposals?status=${status}`),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reviews"
        subtitle={
          <>
            Changes staged by Claude (and teammates) that only land after <em>you</em> review
            and apply them. Open one to see what it does to the plan as a whole, then go
            through the changes one by one.
          </>
        }
      />

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
