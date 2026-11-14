import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import {
  TRACKERS_KEY,
  createTrackerLink,
  deleteTrackerLink,
  getTrackers,
  listTrackerLinks,
  resyncTrackerLink,
} from "../api/trackers";
import type { Connection, TrackerLinkSyncResult, TrackerLinkTarget } from "../api/types";
import { trackingFailure } from "../lib/board";
import { parseUtc, timeAgo } from "../lib/proposals";
import { linkableConnections, providerLabel } from "../lib/tracking";

/** Link tracker items (initiative / epic / story — any tracker canopy reads directly with a
 *  hierarchy) into a canopy project or initiative (§J9). For a project target the item and its
 *  whole descendant subtree become tasks; for an initiative target each descendant epic becomes
 *  a project (with its stories as tasks). The tracker stays the status owner. */
export default function TrackerLinksPanel({
  targetType,
  targetId,
  mayLink,
}: {
  targetType: TrackerLinkTarget;
  targetId: number;
  /** A planner who may edit the target. */
  mayLink: boolean;
}) {
  const qc = useQueryClient();
  const [rootKey, setRootKey] = useState("");
  const [connId, setConnId] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TrackerLinkSyncResult | null>(null);

  const linksKey = ["tracker-links", targetType, targetId];
  const links = useQuery({
    queryKey: linksKey,
    queryFn: () => listTrackerLinks({ target_type: targetType, target_id: targetId }),
  });
  const catalog = useQuery({ queryKey: TRACKERS_KEY, queryFn: getTrackers, staleTime: 5 * 60 * 1000 });
  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<Connection[]>("/connectors/connections"),
  });

  const usable = linkableConnections(connections.data, catalog.data);
  const resolvedConnId = connId === "" && usable.length === 1 ? usable[0].id : connId;
  const labels = [...new Set(usable.map((c) => providerLabel(c.provider, catalog.data)))];
  const tracker = labels.length === 1 ? labels[0] : "tracker";
  const canLink = mayLink && rootKey.trim() !== "" && resolvedConnId !== "";

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: linksKey });
    void qc.invalidateQueries({ queryKey: ["projects"] });
    void qc.invalidateQueries({ queryKey: ["initiatives"] });
    if (targetType === "project") {
      for (const key of ["tasks", "gantt", "board", "tracking"]) {
        void qc.invalidateQueries({ queryKey: [key, targetId] });
      }
    } else {
      void qc.invalidateQueries({ queryKey: ["initiative-rollup", targetId] });
    }
  };

  const create = useMutation({
    mutationFn: (connectionId: number) =>
      createTrackerLink({
        connection_id: connectionId,
        root_key: rootKey.trim(),
        target_type: targetType,
        target_id: targetId,
      }),
    onSuccess: (res) => {
      setRootKey("");
      setError(null);
      setResult(res);
      invalidate();
    },
    onError: (e) => setError(trackingFailure(e).message),
  });

  const resync = useMutation({
    mutationFn: (linkId: number) => resyncTrackerLink(linkId),
    onSuccess: (res) => {
      setError(null);
      setResult(res);
      invalidate();
    },
    onError: (e) => setError(trackingFailure(e).message),
  });

  const unlink = useMutation({
    mutationFn: (linkId: number) => deleteTrackerLink(linkId),
    onSuccess: invalidate,
    onError: (e) => setError(trackingFailure(e).message),
  });

  const linkList = links.data ?? [];
  const heading = targetType === "initiative" ? "Linked tracker items" : "Tracker links";
  const owner = tracker === "tracker" ? "The tracker" : tracker;

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="font-semibold">{heading}</h2>
        <p className="mt-1 text-sm text-slate-500">
          Link a {tracker} item (initiative / epic / story) to this {targetType}. canopy maps the item{" "}
          <strong>and its whole descendant subtree</strong> into canopy
          {targetType === "initiative"
            ? " — each child epic becomes a project under this initiative, with its stories as tasks."
            : " as tasks (epics → phases, stories → tasks)."}{" "}
          {owner} stays the source of truth for status; re-linking is an idempotent update.
        </p>
      </div>

      {mayLink && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canLink && typeof resolvedConnId === "number") create.mutate(resolvedConnId);
          }}
          className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-4"
        >
          <input
            value={rootKey}
            onChange={(e) => setRootKey(e.target.value)}
            placeholder="Item key, e.g. PLAT-123"
            aria-label="Item key"
            spellCheck={false}
            className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
          />
          {usable.length > 1 && (
            <select
              value={connId}
              onChange={(e) => setConnId(e.target.value === "" ? "" : Number(e.target.value))}
              aria-label="Tracker connection"
              className="rounded border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">Pick a tracker connection…</option>
              {usable.map((c) => (
                <option key={c.id} value={c.id}>
                  {providerLabel(c.provider, catalog.data)} · {c.name}
                </option>
              ))}
            </select>
          )}
          <button
            disabled={!canLink || create.isPending}
            className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {create.isPending ? "Linking…" : "Link item"}
          </button>
          {connections.data && catalog.data && usable.length === 0 && (
            <span className="w-full text-xs text-slate-500">
              No authorized tracker connection canopy reads directly — add one in Connectors.
            </span>
          )}
        </form>
      )}

      {error && (
        <div role="alert" className="text-sm text-red-700">
          {error}
        </div>
      )}

      {result && (
        <div role="status" className="rounded border border-slate-200 bg-white px-4 py-2 text-xs text-slate-600">
          Mapped {result.link.root_key}: {result.projects_created} projects created ·{" "}
          {result.projects_linked} linked · {result.tasks_created} tasks created · {result.tasks_updated} updated
          · {result.skipped} skipped.
          {result.notes.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-slate-500">
              {result.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {linkList.map((l) => (
          <li key={l.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
            <span className="text-sm">
              {l.url ? (
                <a
                  href={l.url}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded bg-canopy-50 px-2 py-0.5 text-xs font-medium text-canopy-700 hover:underline"
                >
                  {l.root_key}
                </a>
              ) : (
                <span className="rounded bg-canopy-50 px-2 py-0.5 text-xs font-medium text-canopy-700">
                  {l.root_key}
                </span>
              )}
              <span className="ml-2 text-xs text-slate-500">{providerLabel(l.provider, catalog.data)}</span>
              {l.root_type && <span className="ml-2 text-xs uppercase text-slate-400">{l.root_type}</span>}
              {l.last_synced_at && (
                <span className="ml-2 text-xs text-slate-400" title={parseUtc(l.last_synced_at).toLocaleString()}>
                  synced {timeAgo(l.last_synced_at)}
                </span>
              )}
            </span>
            {mayLink && (
              <span className="flex gap-2">
                <button
                  onClick={() => resync.mutate(l.id)}
                  disabled={resync.isPending}
                  className="rounded border border-canopy-500 px-3 py-1 text-xs font-medium text-canopy-700 disabled:opacity-50"
                >
                  Resync
                </button>
                <button
                  onClick={() => unlink.mutate(l.id)}
                  disabled={unlink.isPending}
                  className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                >
                  Unlink
                </button>
              </span>
            )}
          </li>
        ))}
        {links.isError && (
          <li role="alert" className="px-4 py-3 text-sm text-red-700">
            Couldn’t load the links: {trackingFailure(links.error).message}
          </li>
        )}
        {links.data && linkList.length === 0 && (
          <li className="px-4 py-6 text-center text-sm text-slate-400">No tracker items linked yet.</li>
        )}
      </ul>
    </div>
  );
}
