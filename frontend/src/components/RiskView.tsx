import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  AlertsResponse,
  Engineer,
  RiskFamily,
  RiskMitigation,
  RiskResponse,
  RiskSnapshot,
} from "../api/types";
import { riskTone, scoreBar } from "../lib/risk";
import { useCurrentUser } from "../lib/useCurrentUser";
import { isPlanner } from "../lib/permissions";

const SEVERITY_STYLES: Record<string, string> = {
  error: "border-red-300 bg-red-50 text-red-700",
  warning: "border-amber-300 bg-amber-50 text-amber-700",
  info: "border-slate-200 bg-slate-50 text-slate-600",
};

export default function RiskView({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const [ackKey, setAckKey] = useState<string | null>(null);
  const { data: me } = useCurrentUser();
  const mayWrite = isPlanner(me?.role);

  const risk = useQuery({
    queryKey: ["risk", projectId],
    queryFn: () => api.get<RiskResponse>(`/projects/${projectId}/risk`),
  });
  const alerts = useQuery({
    queryKey: ["alerts", projectId],
    queryFn: () => api.get<AlertsResponse>(`/projects/${projectId}/alerts`),
  });
  const engineers = useQuery({
    queryKey: ["engineers"],
    queryFn: () => api.get<Engineer[]>("/team/engineers"),
  });
  const timeline = useQuery({
    queryKey: ["risk-timeline", projectId],
    queryFn: () => api.get<RiskSnapshot[]>(`/projects/${projectId}/risk/timeline`),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["risk", projectId] });

  const resolveMit = useMutation({
    mutationFn: (vars: { id: number; resolved: boolean }) =>
      api.patch(`/projects/${projectId}/risk/mitigations/${vars.id}`, {
        resolved: vars.resolved,
      }),
    onSuccess: invalidate,
  });
  const deleteMit = useMutation({
    mutationFn: (id: number) => api.del(`/projects/${projectId}/risk/mitigations/${id}`),
    onSuccess: invalidate,
  });
  const snapshot = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/risk/snapshot`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["risk-timeline", projectId] }),
  });

  if (!risk.data) {
    return <p className="text-sm text-slate-500">Loading risk…</p>;
  }
  const data = risk.data;
  const tone = riskTone(data.level);
  const engineerName = (id: number | null) =>
    id == null ? null : (engineers.data ?? []).find((e) => e.id === id)?.name ?? `#${id}`;
  const mitigationsFor = (key: string) =>
    data.mitigations.filter((m) => m.indicator_key === key && !m.resolved);

  return (
    <div className="space-y-5">
      {/* Overall score */}
      <div className="flex items-center gap-4 rounded-lg border border-slate-200 bg-white p-4">
        <div className="text-4xl font-bold tabular-nums">{data.score}</div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="font-semibold">Risk score</span>
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${tone.badge}`}>
              {tone.label}
            </span>
          </div>
          <div className="mt-1 h-2 w-full overflow-hidden rounded bg-slate-100">
            <div className={`h-full ${tone.bar}`} style={{ width: `${data.score}%` }} />
          </div>
          <p className="mt-1 text-xs text-slate-400">
            A leading-indicator score (0–100, higher = riskier). Opinionated and arguable —
            its job is to start a conversation.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          {(timeline.data?.length ?? 0) > 0 && (
            <div className="flex h-12 items-end gap-0.5" title="Risk trend">
              {(timeline.data ?? []).map((s) => (
                <div
                  key={s.id}
                  className={`w-1.5 rounded-sm ${riskTone(s.level).bar}`}
                  style={{ height: `${Math.max(4, s.score)}%` }}
                  title={`${s.score} (${new Date(s.created_at).toLocaleDateString()})`}
                />
              ))}
            </div>
          )}
          {mayWrite && (
            <button
              onClick={() => snapshot.mutate()}
              disabled={snapshot.isPending}
              className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 disabled:opacity-50"
            >
              Capture snapshot
            </button>
          )}
        </div>
      </div>

      {/* Confidence flag — a blind project is flagged, not silently scored as safe. */}
      {data.confidence === "low" && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-700">
          <span className="font-medium">Low confidence.</span> {data.confidence_note}
        </div>
      )}

      {/* Families + indicators */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {data.families.map((f) => (
          <FamilyCard
            key={f.key}
            family={f}
            mitigationsFor={mitigationsFor}
            ackKey={ackKey}
            setAckKey={setAckKey}
            engineers={engineers.data ?? []}
            projectId={projectId}
            onChange={invalidate}
            engineerName={engineerName}
            mayWrite={mayWrite}
          />
        ))}
      </div>

      {/* Indicator acknowledgements — NOT "mitigations": these acknowledge a *computed* indicator
          with a note/owner/check-in. Distinct from the RAID register's own mitigation/contingency
          fields (its own sub-view), which is why the old "Mitigation log" name was confusing. */}
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-2 font-semibold">Indicator acknowledgements</h2>
        {data.mitigations.length === 0 ? (
          <p className="text-sm text-slate-400">
            Nothing acknowledged yet — acknowledge an indicator above to track a response.
          </p>
        ) : (
          <ul className="space-y-2 text-sm">
            {[...data.mitigations]
              .sort((a, b) => Number(a.resolved) - Number(b.resolved))
              .map((m: RiskMitigation) => (
                <li
                  key={m.id}
                  className={`flex items-center gap-2 rounded border px-3 py-2 ${
                    m.resolved ? "border-slate-200 bg-slate-50 text-slate-400" : "border-slate-200"
                  }`}
                >
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">
                    {m.indicator_key}
                  </span>
                  <span className={m.resolved ? "line-through" : ""}>{m.note}</span>
                  <span className="ml-auto flex items-center gap-3 text-xs text-slate-400">
                    {engineerName(m.owner_engineer_id) && (
                      <span>{engineerName(m.owner_engineer_id)}</span>
                    )}
                    {m.check_in && <span>check-in {m.check_in}</span>}
                    {mayWrite && (
                      <>
                        <button
                          onClick={() => resolveMit.mutate({ id: m.id, resolved: !m.resolved })}
                          className="text-canopy-700 hover:underline"
                        >
                          {m.resolved ? "reopen" : "resolve"}
                        </button>
                        <button
                          onClick={() => deleteMit.mutate(m.id)}
                          className="text-slate-400 hover:text-red-600"
                        >
                          delete
                        </button>
                      </>
                    )}
                  </span>
                </li>
              ))}
          </ul>
        )}
      </div>

      {/* Lagging indicators: the alerts digest */}
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-2 font-semibold">
          Alerts <span className="text-xs font-normal text-slate-400">(lagging indicators)</span>
        </h2>
        {!alerts.data ? (
          <p className="text-sm text-slate-500">Loading alerts…</p>
        ) : alerts.data.alerts.length === 0 ? (
          <p className="text-sm text-slate-500">No alerts — everything looks on track.</p>
        ) : (
          <ul className="space-y-2">
            {alerts.data.alerts.map((a, i) => (
              <li
                key={i}
                className={`rounded border px-4 py-2 text-sm ${
                  SEVERITY_STYLES[a.severity] ?? SEVERITY_STYLES.info
                }`}
              >
                <span className="font-medium uppercase">{a.severity}</span> · {a.message}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function FamilyCard({
  family,
  mitigationsFor,
  ackKey,
  setAckKey,
  engineers,
  projectId,
  onChange,
  engineerName,
  mayWrite,
}: {
  family: RiskFamily;
  mitigationsFor: (key: string) => RiskMitigation[];
  ackKey: string | null;
  setAckKey: (k: string | null) => void;
  engineers: Engineer[];
  projectId: number;
  onChange: () => void;
  engineerName: (id: number | null) => string | null;
  mayWrite: boolean;
}) {
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">{family.label}</h3>
        <span className="text-sm tabular-nums text-slate-500">{family.score}</span>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded bg-slate-100">
        <div className={`h-full ${scoreBar(family.score)}`} style={{ width: `${family.score}%` }} />
      </div>

      <ul className="mt-3 space-y-2">
          {family.indicators.map((ind) => {
            const open_ = open === ind.key;
            const mits = mitigationsFor(ind.key);
            return (
              <li key={ind.key} className="text-sm">
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-block h-2 w-2 shrink-0 rounded-full ${scoreBar(ind.score)}`}
                  />
                  <span className="truncate">{ind.summary}</span>
                  <span className="ml-auto shrink-0 text-xs tabular-nums text-slate-400">
                    {ind.score}
                  </span>
                </div>
                <div className="mt-0.5 flex gap-3 pl-4 text-xs text-slate-400">
                  {ind.details.length > 0 && (
                    <button onClick={() => setOpen(open_ ? null : ind.key)} className="hover:underline">
                      {open_ ? "hide" : `details (${ind.details.length})`}
                    </button>
                  )}
                  {mayWrite && (
                    <button
                      onClick={() => setAckKey(ackKey === ind.key ? null : ind.key)}
                      className="text-canopy-700 hover:underline"
                    >
                      acknowledge
                    </button>
                  )}
                  {mits.length > 0 && <span>{mits.length} open mitigation(s)</span>}
                </div>
                {open_ && (
                  <ul className="ml-4 mt-1 list-disc pl-4 text-xs text-slate-500">
                    {ind.details.map((d, i) => (
                      <li key={i}>{d}</li>
                    ))}
                  </ul>
                )}
                {mayWrite && ackKey === ind.key && (
                  <AcknowledgeForm
                    projectId={projectId}
                    indicatorKey={ind.key}
                    engineers={engineers}
                    onDone={() => {
                      setAckKey(null);
                      onChange();
                    }}
                  />
                )}
                {mits.map((m) => (
                  <div key={m.id} className="ml-4 mt-1 text-xs text-slate-500">
                    ↳ {m.note}
                    {engineerName(m.owner_engineer_id) && ` · ${engineerName(m.owner_engineer_id)}`}
                    {m.check_in && ` · check-in ${m.check_in}`}
                  </div>
                ))}
              </li>
            );
          })}
      </ul>
    </div>
  );
}

function AcknowledgeForm({
  projectId,
  indicatorKey,
  engineers,
  onDone,
}: {
  projectId: number;
  indicatorKey: string;
  engineers: Engineer[];
  onDone: () => void;
}) {
  const [note, setNote] = useState("");
  const [owner, setOwner] = useState<number | "">("");
  const [checkIn, setCheckIn] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/risk/mitigations`, {
        indicator_key: indicatorKey,
        note,
        owner_engineer_id: owner || null,
        check_in: checkIn || null,
      }),
    onSuccess: onDone,
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (note.trim()) create.mutate();
      }}
      className="ml-4 mt-2 space-y-1 rounded bg-slate-50 p-2"
    >
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Mitigation note…"
        rows={2}
        className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
      />
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={owner}
          onChange={(e) => setOwner(e.target.value ? Number(e.target.value) : "")}
          className="rounded border border-slate-300 px-2 py-1 text-xs"
        >
          <option value="">Owner… (optional)</option>
          {engineers.map((eng) => (
            <option key={eng.id} value={eng.id}>
              {eng.name}
            </option>
          ))}
        </select>
        <input
          type="date"
          value={checkIn}
          onChange={(e) => setCheckIn(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-xs"
        />
        <button className="ml-auto rounded bg-canopy-500 px-3 py-1 text-xs font-medium text-white">
          Acknowledge
        </button>
      </div>
    </form>
  );
}
