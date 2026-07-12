import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import type {
  Proposal,
  ProposalApplyResult,
  ProposalDetail,
  ProposalItem,
  ProposalStatus,
} from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";
import { isPlanner } from "../lib/permissions";
import { diffRows, includedCount, itemHeadline } from "../lib/proposals";

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

const ACTION_BADGE: Record<string, string> = {
  create: "bg-emerald-50 text-emerald-700 border-emerald-200",
  update: "bg-sky-50 text-sky-700 border-sky-200",
  resolve: "bg-violet-50 text-violet-700 border-violet-200",
};

export default function Reviews() {
  const { proposalId } = useParams();
  const [status, setStatus] = useState<ProposalStatus | "all">("open");
  const [lastApplied, setLastApplied] = useState<ProposalApplyResult | null>(null);
  const { data: me } = useCurrentUser();
  const planner = isPlanner(me?.role);

  const proposals = useQuery({
    queryKey: ["proposals", status],
    queryFn: () =>
      api.get<Proposal[]>(status === "all" ? "/proposals" : `/proposals?status=${status}`),
    enabled: !proposalId,
  });

  if (proposalId) {
    return (
      <div className="space-y-4">
        <Link to="/reviews" className="text-sm text-canopy-700 hover:underline">
          ← All reviews
        </Link>
        <ProposalCard id={Number(proposalId)} planner={planner} initiallyOpen />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Reviews</h1>
        <p className="mt-1 text-sm text-slate-500">
          Changes staged by Claude (and teammates) that only land after <em>you</em> review
          and apply them. Each line shows where the fact came from; untick anything you
          don&apos;t want before applying.
        </p>
      </div>

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

      {lastApplied && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">
          <span>
            Applied {lastApplied.applied} change{lastApplied.applied === 1 ? "" : "s"} from
            &ldquo;{lastApplied.proposal.title}&rdquo;
            {lastApplied.skipped > 0 ? ` (${lastApplied.skipped} excluded)` : ""}
            {lastApplied.replanned_projects.length > 0 ? " — schedules replanned." : "."}
          </span>
          <button
            onClick={() => setLastApplied(null)}
            className="ml-auto text-emerald-600 hover:text-emerald-800"
          >
            ×
          </button>
        </div>
      )}

      {proposals.data?.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
          {status === "open"
            ? "Nothing awaits review. Staged changes from Claude sessions will appear here."
            : "No proposals with this status."}
        </div>
      ) : (
        <div className="space-y-3">
          {(proposals.data ?? []).map((p) => (
            <ProposalCard
              key={p.id}
              id={p.id}
              planner={planner}
              summaryRow={p}
              onApplied={setLastApplied}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ProposalCard({
  id,
  planner,
  summaryRow,
  initiallyOpen = false,
  onApplied,
}: {
  id: number;
  planner: boolean;
  summaryRow?: Proposal;
  initiallyOpen?: boolean;
  onApplied?: (result: ProposalApplyResult) => void;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(initiallyOpen);
  const [rejectNote, setRejectNote] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["proposal", id],
    queryFn: () => api.get<ProposalDetail>(`/proposals/${id}`),
    enabled: open,
  });

  const refreshAll = () => {
    void qc.invalidateQueries(); // apply replans projects — refresh everything
  };

  const apply = useMutation({
    mutationFn: () => api.post<ProposalApplyResult>(`/proposals/${id}/apply`),
    onSuccess: (result) => {
      setApplyError(null);
      onApplied?.(result);
      refreshAll();
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        try {
          const body = JSON.parse(err.message) as {
            detail?: { code?: string; errors?: { error: string }[] };
          };
          if (body.detail?.code === "invalid_items") {
            setApplyError(
              `${body.detail.errors?.length ?? 0} item(s) failed validation — details shown inline below. Exclude or fix them, then apply again.`
            );
          } else {
            setApplyError(err.message);
          }
        } catch {
          setApplyError(err.message);
        }
      } else {
        setApplyError(String(err));
      }
      void qc.invalidateQueries({ queryKey: ["proposal", id] });
    },
  });

  const reject = useMutation({
    mutationFn: () =>
      api.post<Proposal>(`/proposals/${id}/reject`, { note: rejectNote || null }),
    onSuccess: () => {
      setRejecting(false);
      refreshAll();
    },
  });

  const toggleItem = useMutation({
    mutationFn: (input: { itemId: number; excluded: boolean }) =>
      api.patch<ProposalItem>(`/proposals/${id}/items/${input.itemId}`, {
        excluded: input.excluded,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["proposal", id] }),
  });

  const header = detail.data ?? summaryRow;
  if (!header) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-400">
        {detail.isError ? "Proposal not found." : "Loading…"}
      </div>
    );
  }

  const isOpen = header.status === "open";
  const items = detail.data?.items ?? [];
  const included = includedCount(items);

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left"
      >
        <span
          className={`rounded px-1.5 py-0.5 text-xs font-medium ${STATUS_BADGE[header.status]}`}
        >
          {header.status}
        </span>
        {header.scope_label && (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">
            {header.scope_label}
          </span>
        )}
        <span className="truncate font-medium">{header.title}</span>
        <span className="ml-auto shrink-0 text-xs text-slate-400">
          {header.item_count} change{header.item_count === 1 ? "" : "s"}
          {header.origin ? ` · ${header.origin}` : ""}
        </span>
      </button>

      {open && (
        <div className="space-y-4 border-t border-slate-100 px-4 py-4">
          {header.summary && (
            <p className="whitespace-pre-wrap text-sm text-slate-600">{header.summary}</p>
          )}
          {header.status === "rejected" && header.review_note && (
            <p className="rounded bg-red-50 p-2 text-sm text-red-700">
              Rejected: {header.review_note}
            </p>
          )}
          {header.status === "applied" && (
            <p className="rounded bg-emerald-50 p-2 text-sm text-emerald-700">
              Applied {header.applied_count} change{header.applied_count === 1 ? "" : "s"}
              {header.reviewed_at ? ` on ${header.reviewed_at.slice(0, 10)}` : ""}.
            </p>
          )}
          {applyError && (
            <p className="rounded bg-red-50 p-2 text-sm text-red-700">{applyError}</p>
          )}

          {detail.isLoading ? (
            <p className="text-sm text-slate-400">Loading changes…</p>
          ) : (
            <ul className="space-y-3">
              {items.map((item) => (
                <ItemRow
                  key={item.id}
                  item={item}
                  canEdit={planner && isOpen}
                  onToggle={(excluded) =>
                    toggleItem.mutate({ itemId: item.id, excluded })
                  }
                />
              ))}
            </ul>
          )}

          {planner && isOpen && (
            <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
              <button
                onClick={() => apply.mutate()}
                disabled={apply.isPending || included === 0}
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
                <span className="flex flex-1 items-center gap-2">
                  <input
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
              <span className="ml-auto text-xs text-slate-400">
                Applying replans affected schedules.
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ItemRow({
  item,
  canEdit,
  onToggle,
}: {
  item: ProposalItem;
  canEdit: boolean;
  onToggle: (excluded: boolean) => void;
}) {
  const rows = diffRows(item);
  return (
    <li
      className={`rounded border p-3 ${
        item.excluded ? "border-slate-100 bg-slate-50 opacity-60" : "border-slate-200"
      }`}
    >
      <div className="flex items-start gap-2">
        {canEdit && (
          <input
            type="checkbox"
            checked={!item.excluded}
            onChange={(e) => onToggle(!e.target.checked)}
            className="mt-1"
            title={item.excluded ? "Excluded — won't be applied" : "Included"}
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded border px-1.5 py-0.5 text-xs ${
                ACTION_BADGE[item.action] ?? "bg-slate-50 text-slate-600"
              }`}
            >
              {item.action}
            </span>
            <span className="truncate text-sm font-medium">{itemHeadline(item)}</span>
            {item.stale && (
              <span
                className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800"
                title="The live value changed after this was staged — check the diff."
              >
                changed since staged
              </span>
            )}
            {item.error && (
              <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-700">
                {item.error}
              </span>
            )}
          </div>
          {item.reason && <p className="mt-1 text-xs text-slate-500">{item.reason}</p>}
          {(item.source_label || item.source_kind) && (
            <p className="mt-1 text-xs text-slate-400">
              Source: {item.source_kind ? `[${item.source_kind}] ` : ""}
              {item.source_url ? (
                <a
                  href={item.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-canopy-700 hover:underline"
                >
                  {item.source_label ?? item.source_url}
                </a>
              ) : (
                item.source_label
              )}
            </p>
          )}
          {rows.length > 0 && (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-xs">
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.field} className="border-t border-slate-100">
                      <td className="py-1 pr-3 font-mono text-slate-400">{r.field}</td>
                      {r.before !== null ? (
                        <>
                          <td className="py-1 pr-2 text-slate-500 line-through decoration-slate-300">
                            {r.before}
                          </td>
                          <td className="py-1 pr-2 text-slate-300">→</td>
                        </>
                      ) : (
                        <td className="py-1 pr-2 text-slate-300" colSpan={2} />
                      )}
                      <td className="py-1 font-medium text-slate-700">{r.after}</td>
                      {r.current !== null && (
                        <td className="py-1 pl-2 text-amber-700">now: {r.current}</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </li>
  );
}
