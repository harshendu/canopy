import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { ActivityEvent, ActivityKind } from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";
import { isPlanner } from "../lib/permissions";

const KIND_BADGE: Record<string, string> = {
  deploy: "bg-emerald-100 text-emerald-700",
  build_failure: "bg-red-100 text-red-700",
  incident_open: "bg-orange-100 text-orange-700",
  incident_close: "bg-slate-100 text-slate-500",
};

const KINDS: ActivityKind[] = ["deploy", "build_failure", "incident_open", "incident_close"];

export default function ActivityView({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const mayRecord = isPlanner(me?.role);
  const [kind, setKind] = useState<ActivityKind>("deploy");
  const [summary, setSummary] = useState("");
  const [reference, setReference] = useState("");

  const feed = useQuery({
    queryKey: ["activity", projectId],
    queryFn: () => api.get<ActivityEvent[]>(`/projects/${projectId}/activity`),
  });

  const record = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/activity`, {
        kind,
        summary,
        reference: reference || null,
        source: "manual",
      }),
    onSuccess: () => {
      setSummary("");
      setReference("");
      qc.invalidateQueries({ queryKey: ["activity", projectId] });
      // An incident_open auto-opens a postmortem.
      qc.invalidateQueries({ queryKey: ["retros", projectId] });
    },
  });

  const events = feed.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Activity</h2>
        <span className="text-xs text-slate-400">
          deploys · build failures · incidents (CI/observability via /webhooks/events)
        </span>
      </div>

      {mayRecord && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (summary.trim()) record.mutate();
          }}
          className="flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-white p-3"
        >
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as ActivityKind)}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <input
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="Summary"
            className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <input
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            placeholder="Reference (optional)"
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <button className="rounded bg-canopy-500 px-3 py-1 text-sm font-medium text-white">
            Record
          </button>
        </form>
      )}

      {events.length === 0 ? (
        <p className="text-sm text-slate-400">No activity yet.</p>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
          {events.map((e) => (
            <li key={e.id} className="flex items-center gap-2 px-4 py-2 text-sm">
              <span className={`rounded px-1.5 py-0.5 text-xs ${KIND_BADGE[e.kind] ?? ""}`}>
                {e.kind.replace("_", " ")}
              </span>
              <span className="truncate">{e.summary}</span>
              <span className="ml-auto flex shrink-0 items-center gap-2 text-xs text-slate-400">
                {e.reference && <span>{e.reference}</span>}
                <span>{e.source}</span>
                <span>{new Date(e.created_at).toLocaleDateString()}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
