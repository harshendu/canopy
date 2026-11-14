import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import type {
  Engineer,
  Proposal,
  ProposalApplyResult,
  ProposalDetail,
  ProposalItem,
  ProposalPreview,
  ProposalStatus,
} from "../api/types";
import { ChangeList } from "../components/review/ChangeList";
import { PlanCompare } from "../components/review/PlanCompare";
import { PageHeader } from "../components/PageHeader";
import { isPlanner } from "../lib/permissions";
import {
  buildContext,
  formatDay,
  impactChips,
  includedCount,
  reviewPrompt,
  timeAgo,
  withDependents,
  withPrerequisites,
  type ImpactChip,
} from "../lib/proposals";
import { deltaTone, formatDayDelta } from "../lib/scenarioDiff";
import { useCurrentUser } from "../lib/useCurrentUser";

const STATUS_BADGE: Record<ProposalStatus, string> = {
  open: "bg-amber-100 text-amber-800",
  applied: "bg-emerald-100 text-emerald-700",
  rejected: "bg-red-100 text-red-700",
  withdrawn: "bg-slate-100 text-slate-500",
};
const STATUS_LABEL: Record<ProposalStatus, string> = {
  open: "Awaiting review",
  applied: "Applied",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};
const CHIP_TONE: Record<ImpactChip["tone"], string> = {
  add: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  edit: "bg-sky-50 text-sky-800 ring-sky-200",
  shift: "bg-amber-50 text-amber-800 ring-amber-200",
  neutral: "bg-slate-50 text-slate-700 ring-slate-200",
};

type View = "plan" | "changes";

/**
 * Reviewing one staged proposal. Two passes, in the order a person thinks:
 *
 *  1. **Plan** — the schedule as a whole, current ⇄ proposed, so the effect is visible
 *     before any detail (what moves, by how much, does the finish slip).
 *  2. **Changes** — the fine-grained list: every change in plain words, each one
 *     excludable and editable in place.
 *
 * It is a live page: the author (usually Claude) can revise the proposal while it is open
 * — the reviewer asks for changes in conversation and watches them land here.
 */
export default function ReviewWorkspace() {
  const { proposalId } = useParams();
  const id = Number(proposalId);
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const planner = isPlanner(me?.role);

  const [view, setView] = useState<View>("plan");
  const [focusIds, setFocusIds] = useState<number[]>([]);
  const clearFocus = useCallback(() => setFocusIds([]), []);
  const [rejecting, setRejecting] = useState(false);
  const [rejectNote, setRejectNote] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [applied, setApplied] = useState<ProposalApplyResult | null>(null);
  // The revision this reviewer has already seen — anything newer arrived while they watched.
  const [seenRevision, setSeenRevision] = useState<number | null>(null);
  // An apply/reject is in flight. The server announces the close over SSE *before* our own
  // call returns, so the preview (which a closed proposal no longer has) is paused meanwhile.
  const [closing, setClosing] = useState(false);
  // The last include/exclude that pulled other changes along with it (offered as an undo):
  // every item whose state it flipped, and how many of those the reviewer didn't click.
  const [cascade, setCascade] = useState<{
    ids: number[];
    excluded: boolean;
    pulled: number;
  } | null>(null);

  const detail = useQuery({
    queryKey: ["proposal", id],
    queryFn: () => api.get<ProposalDetail>(`/proposals/${id}`),
    enabled: Number.isFinite(id),
  });
  const proposal = detail.data;
  const isOpen = proposal?.status === "open";
  const preview = useQuery({
    queryKey: ["proposal", id, "preview"],
    queryFn: () => api.get<ProposalPreview>(`/proposals/${id}/preview`),
    enabled: isOpen && !closing,
    placeholderData: keepPreviousData, // keep the chart up while it recalculates
    // A 4xx is an answer (e.g. 409: the proposal was just closed), not a blip to retry.
    retry: (failures, err) => !(err instanceof ApiError && err.status < 500) && failures < 2,
  });
  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
    enabled: isOpen && planner,
  });

  if (proposal && seenRevision === null) setSeenRevision(proposal.revision);

  const refreshProposal = () => qc.invalidateQueries({ queryKey: ["proposal", id] });
  // Once a proposal closes it has no future state: mark it closed in the cache first (so the
  // preview stops being asked for), then refresh everything else the change may have moved.
  const closeAndRefresh = (closed: Proposal) => {
    qc.setQueryData<ProposalDetail>(["proposal", id], (prev) =>
      prev ? { ...prev, ...closed } : prev
    );
    void qc.invalidateQueries({
      predicate: (q) => !(q.queryKey[0] === "proposal" && q.queryKey[2] === "preview"),
    });
  };

  const toggle = useMutation({
    mutationFn: (input: { itemIds: number[]; excluded: boolean }) =>
      api.patch<ProposalDetail>(`/proposals/${id}/items`, {
        excluded: input.excluded,
        item_ids: input.itemIds,
      }),
    // Flip the checkbox at once (the server round-trip follows); roll back if it refuses.
    onMutate: async (input) => {
      await qc.cancelQueries({ queryKey: ["proposal", id], exact: true });
      const previous = qc.getQueryData<ProposalDetail>(["proposal", id]);
      if (previous) {
        qc.setQueryData<ProposalDetail>(["proposal", id], {
          ...previous,
          items: previous.items.map((item) =>
            input.itemIds.includes(item.id) ? { ...item, excluded: input.excluded } : item
          ),
        });
      }
      return { previous };
    },
    onError: (err, _input, context) => {
      if (context?.previous) qc.setQueryData(["proposal", id], context.previous);
      setActionError(err instanceof ApiError ? err.message : String(err));
    },
    onSettled: () => void refreshProposal(),
  });
  const override = useMutation({
    mutationFn: (input: { itemId: number; overrides: Record<string, unknown> }) =>
      api.patch<ProposalItem>(`/proposals/${id}/items/${input.itemId}`, {
        overrides: input.overrides,
      }),
    onSuccess: () => void refreshProposal(),
  });
  const apply = useMutation({
    mutationFn: () => api.post<ProposalApplyResult>(`/proposals/${id}/apply`),
    onMutate: () => setClosing(true),
    onSuccess: (result) => {
      setActionError(null);
      setApplied(result);
      closeAndRefresh(result.proposal); // apply replans projects — refresh everything
    },
    onError: (err) => {
      setClosing(false);
      setActionError(applyErrorMessage(err));
      setView("changes");
      void refreshProposal();
    },
  });
  const reject = useMutation({
    mutationFn: () => api.post<Proposal>(`/proposals/${id}/reject`, { note: rejectNote || null }),
    onMutate: () => setClosing(true),
    onSuccess: (closed) => {
      setRejecting(false);
      closeAndRefresh(closed);
    },
    onError: (err) => {
      setClosing(false);
      setActionError(err instanceof ApiError ? err.message : String(err));
    },
  });

  if (!proposal) {
    return (
      <div className="space-y-4">
        <PageHeader breadcrumbs={[{ label: "Reviews", to: "/reviews" }, { label: "Review" }]} title="Review" />
        <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-400">
          {detail.isError ? "This proposal doesn’t exist (or was removed)." : "Loading…"}
        </div>
      </div>
    );
  }

  const ctx = buildContext(proposal);
  const items = proposal.items;
  const included = includedCount(items);
  const canEdit = planner && isOpen;
  const issues = preview.data?.issues;
  const blocked = preview.data ? !preview.data.can_apply && included > 0 : false;
  const justRevised = seenRevision !== null && proposal.revision > seenRevision;
  const openChanges = (itemIds: number[]) => {
    setFocusIds(itemIds);
    setView("changes");
  };
  // Changes that build on each other move together: excluding one takes what depends on it,
  // including one brings back what it needs — so the set can always still apply.
  const toggleItems = (itemIds: number[], excluded: boolean) => {
    const all = excluded ? withDependents(items, itemIds) : withPrerequisites(items, itemIds);
    const flipped = all.filter(
      (itemId) => items.find((i) => i.id === itemId)?.excluded !== excluded
    );
    const pulled = flipped.filter((itemId) => !itemIds.includes(itemId)).length;
    setCascade(pulled > 0 ? { ids: flipped, excluded, pulled } : null);
    toggle.mutate({ itemIds: all, excluded });
  };

  return (
    <div className="space-y-5 pb-4">
      <PageHeader
        breadcrumbs={[{ label: "Reviews", to: "/reviews" }, { label: proposal.title }]}
        title={proposal.title}
        titleAdornment={
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[proposal.status]}`}>
            {STATUS_LABEL[proposal.status]}
          </span>
        }
        subtitle={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {proposal.scope_label && (
              <Link
                to={`/${proposal.scope_level === "project" ? "projects" : "initiatives"}/${proposal.scope_id}`}
                className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600 hover:bg-slate-200"
              >
                {proposal.scope_label}
              </Link>
            )}
            <span>
              Staged {timeAgo(proposal.created_at)}
              {proposal.created_by ? ` by ${proposal.created_by}` : ""}
              {proposal.origin ? ` · ${proposal.origin}` : ""}
            </span>
            {proposal.revision > 1 && (
              <span title={proposal.revision_note ?? undefined}>
                · revision {proposal.revision}, updated {timeAgo(proposal.revised_at)}
              </span>
            )}
          </span>
        }
      />

      {justRevised && (
        <div className="canopy-fade-in flex items-start gap-3 rounded-lg border border-canopy-500/40 bg-canopy-50 px-4 py-3 text-sm text-canopy-700">
          <span aria-hidden>✦</span>
          <div className="min-w-0 flex-1">
            <span className="font-medium">This proposal was just revised</span> (revision{" "}
            {proposal.revision}).{" "}
            {proposal.revision_note && <span>“{proposal.revision_note}”</span>} The plan and
            changes below are up to date; revised changes are tagged.
          </div>
          <button
            onClick={() => setSeenRevision(proposal.revision)}
            className="shrink-0 text-canopy-700 hover:underline"
          >
            Got it
          </button>
        </div>
      )}

      {proposal.summary && (
        <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-400">Why</div>
          <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{proposal.summary}</p>
        </div>
      )}

      {proposal.status === "applied" && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          Applied {proposal.applied_count} change{proposal.applied_count === 1 ? "" : "s"}
          {proposal.reviewed_at ? ` ${timeAgo(proposal.reviewed_at)}` : ""}
          {applied && applied.skipped > 0 ? ` (${applied.skipped} excluded)` : ""}
          {applied && applied.replanned_projects.length > 0 ? " — schedules replanned." : "."}{" "}
          <Link
            to={
              proposal.scope_level === "project"
                ? `/projects/${proposal.scope_id}?tab=gantt`
                : `/initiatives/${proposal.scope_id}`
            }
            className="font-medium underline"
          >
            Open the updated plan
          </Link>
        </div>
      )}
      {proposal.status === "rejected" && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Rejected{proposal.reviewed_at ? ` ${timeAgo(proposal.reviewed_at)}` : ""}
          {proposal.review_note ? ` — “${proposal.review_note}”` : "."}
        </div>
      )}
      {proposal.status === "withdrawn" && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">
          Withdrawn by its author — nothing was applied.
        </div>
      )}

      {isOpen && preview.data && (
        <ImpactStrip
          preview={preview.data}
          onShowIssues={() =>
            openChanges(
              (issues ?? []).map((i) => i.item_id).filter((x): x is number => x !== null)
            )
          }
        />
      )}
      {isOpen && preview.isError && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
          The plan preview couldn&apos;t be computed. You can still review the changes one by one.
        </p>
      )}

      {isOpen && <CoReviewHint proposal={proposal} />}

      {isOpen && (
        <div role="tablist" className="flex gap-6 border-b border-slate-200">
          {(
            [
              { key: "plan", label: "Plan" },
              { key: "changes", label: `Changes (${items.length})` },
            ] as const
          ).map((tab) => (
            <button
              key={tab.key}
              role="tab"
              aria-selected={view === tab.key}
              onClick={() => setView(tab.key)}
              className={`-mb-px border-b-2 pb-2 text-sm font-medium ${
                view === tab.key
                  ? "border-canopy-500 text-slate-900"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      {actionError && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {actionError}
        </p>
      )}
      {cascade && view === "changes" && (
        <p className="canopy-fade-in flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-600">
          <span>
            {cascade.excluded
              ? `Also excluded ${cascade.pulled} change${cascade.pulled === 1 ? "" : "s"} that depend${cascade.pulled === 1 ? "s" : ""} on it.`
              : `Also included ${cascade.pulled} change${cascade.pulled === 1 ? "" : "s"} it needs.`}
          </span>
          <button
            onClick={() => {
              toggle.mutate({ itemIds: cascade.ids, excluded: !cascade.excluded });
              setCascade(null);
            }}
            className="font-medium text-canopy-700 hover:underline"
          >
            Undo
          </button>
          <button
            onClick={() => setCascade(null)}
            aria-label="Dismiss"
            className="ml-auto text-slate-400 hover:text-slate-600"
          >
            ×
          </button>
        </p>
      )}

      {isOpen && view === "plan" ? (
        preview.data ? (
          <PlanCompare preview={preview.data} onOpenChanges={openChanges} />
        ) : (
          <p className="text-sm text-slate-400">
            {preview.isError ? "No plan preview available." : "Working out what changes…"}
          </p>
        )
      ) : (
        <ChangeList
          proposal={proposal}
          items={items}
          ctx={ctx}
          issues={issues}
          engineers={engineers.data ?? []}
          canEdit={canEdit}
          focusIds={focusIds}
          onFocusSeen={clearFocus}
          onToggle={toggleItems}
          onOverride={(itemId, overrides) => override.mutateAsync({ itemId, overrides })}
        />
      )}

      {isOpen && !planner && (
        <p className="text-sm text-slate-400">
          You can read this proposal; applying or rejecting it needs a planner (architect,
          engineering manager or admin).
        </p>
      )}

      {canEdit && (
        <div className="sticky bottom-0 -mx-6 -mb-10 flex flex-wrap items-center gap-3 border-t border-slate-200 bg-white/95 px-6 py-3 backdrop-blur">
          <button
            onClick={() => apply.mutate()}
            disabled={apply.isPending || included === 0 || blocked}
            title={blocked ? "Some changes can't apply yet — see the changes list" : undefined}
            className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {apply.isPending
              ? "Applying…"
              : `Apply ${included} change${included === 1 ? "" : "s"}`}
          </button>
          {!rejecting ? (
            <button
              onClick={() => setRejecting(true)}
              className="rounded border border-slate-300 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              Reject…
            </button>
          ) : (
            <span className="flex min-w-64 flex-1 items-center gap-2">
              <input
                autoFocus
                value={rejectNote}
                onChange={(e) => setRejectNote(e.target.value)}
                placeholder="Why? (the author reads this and adjusts)"
                className="min-w-40 flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
              />
              <button
                onClick={() => reject.mutate()}
                disabled={reject.isPending}
                className="rounded bg-red-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                Reject
              </button>
              <button
                onClick={() => setRejecting(false)}
                className="text-sm text-slate-400 hover:text-slate-600"
              >
                Cancel
              </button>
            </span>
          )}
          <span className="ml-auto text-xs text-slate-500">
            {blocked
              ? "Fix or exclude the flagged changes to apply."
              : included < items.length
                ? `${items.length - included} excluded · all-or-nothing · schedules replan on apply`
                : "All-or-nothing · schedules replan on apply"}
          </span>
        </div>
      )}
    </div>
  );
}

function applyErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return String(err);
  try {
    const body = JSON.parse(err.message) as {
      detail?: { code?: string; errors?: unknown[] } | string;
    };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail?.code === "invalid_items") {
      const n = body.detail.errors?.length ?? 0;
      return `${n} change${n === 1 ? "" : "s"} failed validation, so nothing was applied. They’re flagged below — fix or exclude them, then apply again.`;
    }
  } catch {
    /* not JSON */
  }
  return err.message;
}

/** The headline before any detail: does the finish move, what is the proposal's shape, and
 *  will it apply. */
function ImpactStrip({
  preview,
  onShowIssues,
}: {
  preview: ProposalPreview;
  onShowIssues: () => void;
}) {
  const chips = impactChips(preview.counts);
  const scheduled = preview.projects.filter((p) => p.end_current || p.end_proposed);
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="grid gap-4 px-4 py-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <div className="space-y-2">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
            Finish date
          </div>
          {scheduled.length === 0 && (
            <p className="text-sm text-slate-500">No schedule is affected.</p>
          )}
          {scheduled.map((p) => {
            const moved = Boolean(p.end_delta_days);
            return (
              <div key={p.project_id}>
                {preview.projects.length > 1 && (
                  <div className="font-mono text-xs text-slate-400">{p.key}</div>
                )}
                {p.cycle ? (
                  <div className="text-sm font-medium text-red-600">
                    Can&apos;t be scheduled — dependency loop
                  </div>
                ) : moved ? (
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-slate-400 line-through decoration-slate-300">
                      {formatDay(p.end_current)}
                    </span>
                    <span className="text-slate-300">→</span>
                    <span className="text-xl font-semibold">{formatDay(p.end_proposed)}</span>
                    <span className={`text-sm font-medium ${deltaTone(p.end_delta_days)}`}>
                      {formatDayDelta(p.end_delta_days)}
                    </span>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-xl font-semibold">{formatDay(p.end_proposed)}</span>
                    <span className="text-sm text-slate-500">unchanged</span>
                  </div>
                )}
                {!p.cycle && p.critical_proposed !== p.critical_current && (
                  <div className="text-xs text-slate-500">
                    Critical path: {p.critical_current} → {p.critical_proposed} tasks
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <div className="space-y-2">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
            What this proposal does
          </div>
          <div className="flex flex-wrap gap-1.5">
            {chips.length === 0 && <span className="text-sm text-slate-500">Nothing included.</span>}
            {chips.map((chip) => (
              <span
                key={chip.key}
                className={`rounded-full px-2.5 py-0.5 text-sm ring-1 ring-inset ${CHIP_TONE[chip.tone]}`}
              >
                {chip.label}
              </span>
            ))}
          </div>
        </div>
      </div>
      <div
        className={`flex flex-wrap items-center gap-2 border-t px-4 py-2 text-sm ${
          preview.can_apply
            ? "border-slate-100 text-slate-500"
            : "border-red-100 bg-red-50 text-red-700"
        }`}
      >
        {preview.can_apply ? (
          <>
            <span className="text-canopy-700">✓</span> Ready to apply — {preview.included} change
            {preview.included === 1 ? "" : "s"}
            {preview.excluded > 0 ? `, ${preview.excluded} excluded` : ""}.
          </>
        ) : preview.included === 0 ? (
          <>Every change is excluded — include at least one to apply.</>
        ) : (
          <>
            <span>
              {preview.issues.length} thing{preview.issues.length === 1 ? "" : "s"} to fix before
              this can apply.
            </span>
            {preview.issues.some((i) => i.item_id !== null) && (
              <button onClick={onShowIssues} className="font-medium underline">
                Show me
              </button>
            )}
            {preview.issues
              .filter((i) => i.item_id === null)
              .map((i) => (
                <span key={i.error}>{i.error}</span>
              ))}
          </>
        )}
      </div>
    </div>
  );
}

/** The conversational half of a review: keep this page open, ask Claude for changes. */
function CoReviewHint({ proposal }: { proposal: ProposalDetail }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(reviewPrompt(proposal, window.location.href));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-dashed border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-600">
      <span aria-hidden className="text-canopy-700">
        ✦
      </span>
      <span className="min-w-0 flex-1">
        <span className="font-medium text-slate-800">Refine it by talking to Claude.</span> Keep
        this page open and say what you want — <em>“push the pentest out a week”</em>,{" "}
        <em>“drop the vendor risk”</em> — and it updates here as Claude revises.
      </span>
      <button
        onClick={() => void copy()}
        className="shrink-0 rounded border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
      >
        {copied ? "Copied ✓" : "Copy a starter prompt"}
      </button>
      <Link to="/agent-setup" className="shrink-0 text-xs text-canopy-700 hover:underline">
        Connect Claude
      </Link>
    </div>
  );
}
