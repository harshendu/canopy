import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import type { Connection, JiraLink, JiraLinkSyncResult, JiraLinkTarget } from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";
import { isPlanner } from "../lib/permissions";

/** Link Jira tickets (initiative/epic/story) into a canopy project or initiative. For a
 *  project target the ticket + its whole descendant subtree become tasks; for an initiative
 *  target each descendant epic becomes a Project (with its stories as tasks). */
export default function JiraLinksPanel({
  targetType,
  targetId,
}: {
  targetType: JiraLinkTarget;
  targetId: number;
}) {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const mayLink = isPlanner(me?.role);

  const [jiraKey, setJiraKey] = useState("");
  const [connId, setConnId] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<JiraLinkSyncResult | null>(null);

  const linksKey = ["jira-links", targetType, targetId];
  const links = useQuery({
    queryKey: linksKey,
    queryFn: () =>
      api.get<JiraLink[]>(`/jira-links?target_type=${targetType}&target_id=${targetId}`),
  });
  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<Connection[]>(`/connectors/connections`),
  });

  const jiraConns = (connections.data ?? []).filter(
    (c) => c.provider === "jira" && c.active && c.authorized,
  );
  const resolvedConnId = connId === "" && jiraConns.length === 1 ? jiraConns[0].id : connId;
  const canLink = mayLink && jiraKey.trim() !== "" && resolvedConnId !== "";

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: linksKey });
    qc.invalidateQueries({ queryKey: ["projects"] });
    qc.invalidateQueries({ queryKey: ["initiatives"] });
  };

  const create = useMutation({
    mutationFn: () =>
      api.post<JiraLinkSyncResult>("/jira-links", {
        connection_id: resolvedConnId,
        jira_key: jiraKey.trim(),
        target_type: targetType,
        target_id: targetId,
      }),
    onSuccess: (res) => {
      setJiraKey("");
      setError(null);
      setResult(res);
      invalidate();
    },
    onError: (e: ApiError) => setError(e.message),
  });

  const resync = useMutation({
    mutationFn: (linkId: number) => api.post<JiraLinkSyncResult>(`/jira-links/${linkId}/resync`),
    onSuccess: (res) => {
      setResult(res);
      invalidate();
    },
    onError: (e: ApiError) => setError(e.message),
  });

  const unlink = useMutation({
    mutationFn: (linkId: number) => api.del(`/jira-links/${linkId}`),
    onSuccess: invalidate,
  });

  const linkList = links.data ?? [];

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="font-semibold">Linked Jira tickets</h2>
        <p className="mt-1 text-sm text-slate-500">
          Link a Jira ticket (initiative / epic / story) to this {targetType}. canopy maps the
          ticket <strong>and its whole descendant subtree</strong> into canopy
          {targetType === "initiative"
            ? " — each child epic becomes a project under this initiative, with its stories as tasks."
            : " as tasks (epics → phases, stories → tasks)."}{" "}
          Jira stays the source of truth for status; re-linking is an idempotent update.
        </p>
      </div>

      {mayLink && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canLink) create.mutate();
          }}
          className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-4"
        >
          <input
            value={jiraKey}
            onChange={(e) => setJiraKey(e.target.value)}
            placeholder="Jira key, e.g. PLAT-123"
            className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
          />
          {jiraConns.length > 1 && (
            <select
              value={connId}
              onChange={(e) => setConnId(e.target.value === "" ? "" : Number(e.target.value))}
              className="rounded border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">Pick a Jira connection…</option>
              {jiraConns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
          <button
            disabled={!canLink || create.isPending}
            className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {create.isPending ? "Linking…" : "Link ticket"}
          </button>
          {jiraConns.length === 0 && (
            <span className="text-xs text-slate-400">
              No authorized Jira connection — add one in Connectors.
            </span>
          )}
        </form>
      )}

      {error && <div className="text-sm text-red-600">{error}</div>}

      {result && (
        <div className="rounded border border-slate-200 bg-white px-4 py-2 text-xs text-slate-600">
          Mapped {result.link.jira_key}: {result.projects_created} projects created ·{" "}
          {result.projects_linked} linked · {result.tasks_created} tasks created ·{" "}
          {result.tasks_updated} updated · {result.skipped} skipped.
          {result.notes.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-slate-400">
              {result.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {linkList.map((l) => (
          <li key={l.id} className="flex items-center justify-between gap-2 px-4 py-3">
            <span className="text-sm">
              <span className="rounded bg-canopy-100 px-2 py-0.5 text-xs font-medium text-canopy-700">
                {l.jira_key}
              </span>
              {l.jira_issue_type && (
                <span className="ml-2 text-xs uppercase text-slate-400">{l.jira_issue_type}</span>
              )}
              {l.last_synced_at && (
                <span className="ml-2 text-xs text-slate-400">
                  synced {new Date(l.last_synced_at).toLocaleString()}
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
                  className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
                >
                  Unlink
                </button>
              </span>
            )}
          </li>
        ))}
        {linkList.length === 0 && (
          <li className="px-4 py-6 text-center text-sm text-slate-400">
            No Jira tickets linked yet.
          </li>
        )}
      </ul>
    </div>
  );
}
