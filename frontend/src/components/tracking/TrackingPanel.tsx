import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";
import {
  TRACKERS_KEY,
  getProjectTracking,
  getTrackers,
  publishProjectTracking,
  syncProjectTracking,
  trackingKey,
  updateProjectTracking,
} from "../../api/trackers";
import type {
  Connection,
  ProjectTrackingUpdate,
  StatusCategory,
  TrackerBinding,
  TrackerCapabilities,
  TrackerInfo,
  TrackerStatus,
} from "../../api/types";
import { CATEGORY_LABELS, trackingFailure } from "../../lib/board";
import { parseUtc, timeAgo } from "../../lib/proposals";
import {
  bindingDraft,
  bindingUpdate,
  labelledEntries,
  modeHeadline,
  orderedStatuses,
  ownershipLine,
  schemaFields,
  strategyOptions,
  syncBlocker,
  trackerInfo,
  trackingLabel,
  type BindingDraft,
} from "../../lib/tracking";
import { invalidateTracking } from "../../lib/trackingCache";
import { featureOn, useFeatures } from "../../lib/useFeatures";
import { CATEGORY_ORDER } from "../../lib/workflow";
import { QueryError } from "../QueryError";
import { Icon } from "../icons";
import { SchemaInputs } from "./SchemaInputs";
import SwitchWizard from "./SwitchWizard";

// Status chips by category (with a legend and the category in each chip's text, so colour is
// never the only cue).
const CATEGORY_CHIP: Record<StatusCategory, string> = {
  todo: "border-slate-300 bg-slate-100 text-slate-700",
  in_progress: "border-sky-200 bg-sky-50 text-sky-800",
  done: "border-green-200 bg-green-50 text-green-800",
  cancelled: "border-slate-200 bg-white text-slate-500 line-through",
};
const CATEGORY_SWATCH: Record<StatusCategory, string> = {
  todo: "border-slate-400 bg-slate-300",
  in_progress: "border-sky-500 bg-sky-400",
  done: "border-green-600 bg-green-500",
  cancelled: "border-slate-400 bg-white",
};

const button =
  "rounded px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50";
const primary = `${button} bg-canopy-700 text-white hover:bg-canopy-500`;
const secondary = `${button} border border-slate-300 bg-white text-slate-700 hover:bg-slate-50`;

function localDate(iso: string): string {
  return parseUtc(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function StatusChips({ statuses }: { statuses: readonly TrackerStatus[] }) {
  const ordered = orderedStatuses(statuses);
  const present = CATEGORY_ORDER.filter((c) => ordered.some((s) => s.category === c));
  return (
    <div>
      <ol aria-label="The tracker's statuses, in order" className="flex flex-wrap gap-1.5">
        {ordered.map((s) => (
          <li
            key={s.name}
            title={CATEGORY_LABELS[s.category] ?? s.category}
            className={`rounded-full border px-2 py-0.5 text-xs font-medium ${CATEGORY_CHIP[s.category] ?? CATEGORY_CHIP.todo}`}
          >
            {s.name}
            <span className="sr-only"> — {CATEGORY_LABELS[s.category] ?? s.category}</span>
          </li>
        ))}
      </ol>
      <p aria-hidden="true" className="mt-1.5 flex flex-wrap gap-3 text-xs text-slate-500">
        {present.map((c) => (
          <span key={c} className="inline-flex items-center gap-1">
            <span className={`h-2.5 w-2.5 rounded-full border ${CATEGORY_SWATCH[c]}`} />
            {CATEGORY_LABELS[c]}
          </span>
        ))}
      </p>
    </div>
  );
}

function Entries({ entries, empty }: { entries: { key: string; label: string; value: string }[]; empty: string }) {
  if (entries.length === 0) return <span className="text-slate-500">{empty}</span>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {entries.map((e) => (
        <li key={e.key} className="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs text-slate-700">
          <span className="text-slate-500">{e.label}:</span> <span className="font-mono">{e.value}</span>
        </li>
      ))}
    </ul>
  );
}

/** Adjust the active binding in place (§C12.1): scope, sprint mirroring, mapping. */
function BindingEditor({
  projectId,
  binding,
  tracker,
  capabilities,
  onDone,
}: {
  projectId: number;
  binding: TrackerBinding;
  tracker: TrackerInfo | null;
  capabilities: TrackerCapabilities | null;
  onDone: (message: string | null) => void;
}) {
  const qc = useQueryClient();
  const scopeFields = useMemo(() => schemaFields(tracker?.scope_schema), [tracker]);
  const [draft, setDraft] = useState<BindingDraft>(() => bindingDraft(binding, scopeFields));
  const [failure, setFailure] = useState<string | null>(null);
  const { update, errors, scopeChanged } = bindingUpdate(binding, scopeFields, draft, capabilities);
  const dirty = Object.keys(update).length > 0;

  const save = useMutation({
    mutationFn: (body: ProjectTrackingUpdate) => updateProjectTracking(projectId, body),
    onSuccess: (res, body) => {
      qc.setQueryData(trackingKey(projectId), res);
      void invalidateTracking(qc, projectId);
      onDone(body.scope ? "Binding saved — the next sync re-reads everything in the new scope." : "Binding saved.");
    },
    onError: (err) => setFailure(trackingFailure(err).message),
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (dirty && errors.length === 0) {
          setFailure(null);
          save.mutate(update);
        }
      }}
      aria-labelledby="edit-binding-heading"
      className="space-y-4 border-t border-slate-100 pt-4"
    >
      <h4 id="edit-binding-heading" className="text-sm font-semibold text-slate-800">
        Edit binding
      </h4>
      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm text-slate-600">Scope — where in {binding.label}</legend>
        <SchemaInputs
          fields={scopeFields}
          values={draft.scopeValues}
          onChange={(key, value) => setDraft((d) => ({ ...d, scopeValues: { ...d.scopeValues, [key]: value } }))}
          idPrefix="binding-scope"
        />
      </fieldset>
      {capabilities?.iterations && (
        <label className="flex items-start gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={draft.syncIterations}
            onChange={(e) => setDraft((d) => ({ ...d, syncIterations: e.target.checked }))}
            className="mt-1"
          />
          <span>
            Mirror {binding.label}’s sprints
            <span className="block text-xs text-slate-500">They then come from {binding.label} and are read-only in canopy.</span>
          </span>
        </label>
      )}
      <div className="flex flex-col gap-1">
        <label htmlFor="binding-mapping" className="text-sm text-slate-600">
          Advanced mapping (JSON)
        </label>
        <textarea
          id="binding-mapping"
          value={draft.mappingText}
          onChange={(e) => setDraft((d) => ({ ...d, mappingText: e.target.value }))}
          rows={4}
          spellCheck={false}
          placeholder='{"epic_types": ["Epic"], "estimate_field": "customfield_10016"}'
          className="w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
        />
      </div>
      {scopeChanged && (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          A new scope resets the sync watermark and the tracker’s statuses — the next sync re-reads everything.
        </p>
      )}
      {errors.length > 0 && (
        <ul className="space-y-0.5 text-sm text-red-700">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {failure && (
        <p role="alert" className="text-sm text-red-700">
          {failure}
        </p>
      )}
      <div className="flex gap-2">
        <button type="submit" disabled={!dirty || errors.length > 0 || save.isPending} className={primary}>
          {save.isPending ? "Saving…" : "Save binding"}
        </button>
        <button type="button" onClick={() => onDone(null)} disabled={save.isPending} className={secondary}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/**
 * A project's Tracking tab (USER_FLOWS §C12): native or mirrored, the binding (connection,
 * scope, the tracker's statuses, last sync, sprint mirroring), who owns how many statuses and
 * the trackers it used before. A planner who may edit the project (with `integrations` on)
 * syncs, adjusts the binding, publishes canopy-owned work and switches tracking from here.
 */
export default function TrackingPanel({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const features = useFeatures();
  const integrationsOn = featureOn(features, "integrations");
  const [panel, setPanel] = useState<"edit" | "switch" | null>(null);
  const [notice, setNotice] = useState<{ text: string; error: boolean; details?: string[] } | null>(null);

  const tracking = useQuery({ queryKey: trackingKey(projectId), queryFn: () => getProjectTracking(projectId) });
  const catalog = useQuery({ queryKey: TRACKERS_KEY, queryFn: getTrackers, staleTime: 5 * 60 * 1000 });
  const t = tracking.data;
  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<Connection[]>("/connectors/connections"),
    enabled: integrationsOn && t !== undefined,
  });

  const boundConnectionId = t?.binding?.connection_id ?? null;
  const boundConnection = (connections.data ?? []).find((c) => c.id === boundConnectionId) ?? null;
  const label = t ? trackingLabel(t) : null;
  const trackerName = label ?? "the tracker";

  const sync = useMutation({
    mutationFn: (full: boolean) => syncProjectTracking(projectId, full),
    onSuccess: (res, full) => {
      setNotice({
        text: `${full ? "Full sync" : "Synced"} from ${trackerName}: ${res.created} created · ${res.updated} updated · ${res.skipped} skipped.`,
        error: false,
      });
      void invalidateTracking(qc, projectId);
    },
    onError: (err) => setNotice({ text: trackingFailure(err).message, error: true }),
  });

  const publish = useMutation({
    mutationFn: () => publishProjectTracking(projectId),
    onSuccess: (res) => {
      setNotice({
        text: `Published to ${trackerName}: ${res.created} created · ${res.skipped} already there · ${res.failed} failed.`,
        error: res.failed > 0,
        details: res.errors,
      });
      void invalidateTracking(qc, projectId);
    },
    onError: (err) => setNotice({ text: trackingFailure(err).message, error: true }),
  });

  if (tracking.isLoading) return <p className="text-sm text-slate-500">Loading tracking…</p>;
  if (tracking.isError || !t) {
    return (
      <QueryError
        error={new Error(trackingFailure(tracking.error).message)}
        onRetry={() => void tracking.refetch()}
        label="Couldn’t load how this project is tracked"
      />
    );
  }

  const binding = t.binding;
  const bound = binding !== null;
  const tracker = trackerInfo(catalog.data, binding?.provider);
  const scopeFields = schemaFields(tracker?.scope_schema);
  const mayChange = t.can_edit && integrationsOn;
  const busy = sync.isPending || publish.isPending;
  const syncReason = bound ? syncBlocker(trackerName, t.capabilities, boundConnection) : null;
  const canPublish = t.mode === "mirrored" && binding !== null && Boolean(t.capabilities?.create_items);
  const publishReason =
    canPublish && t.capabilities
      ? (strategyOptions({ label: trackerName, capabilities: t.capabilities }, boundConnection).find(
          (o) => o.value === "publish",
        )?.disabledReason ?? null)
      : null;
  const unavailable = [syncReason && `Sync: ${syncReason}`, publishReason && `Publish: ${publishReason}`].filter(
    (r): r is string => Boolean(r),
  );
  const iterations = t.capabilities?.iterations ?? false;

  const confirmPublish = () => {
    const message = [
      `Publish this project's open canopy-owned tasks to ${trackerName}?`,
      "",
      `canopy creates each as a ${trackerName} item — content only, never status — and ${trackerName} owns its status from then on (it starts in ${trackerName}'s first status). Done and cancelled work stays canopy history.`,
    ].join("\n");
    if (window.confirm(message)) {
      setNotice(null);
      publish.mutate();
    }
  };

  return (
    <div className="space-y-4">
      <section aria-labelledby="tracking-mode" className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id="tracking-mode" className="flex items-center gap-2 font-semibold text-slate-800">
              <Icon name="tracking" size={16} />
              {modeHeadline(t.mode, label)}
            </h2>
            <p className="mt-1 text-sm tabular-nums text-slate-700">{ownershipLine(t, label)}</p>
            <p className="mt-1 max-w-2xl text-sm text-slate-500">
              {t.mode === "native"
                ? "The board is the source of truth: every task's status moves here."
                : bound
                  ? `Work ${trackerName} knows keeps its status there — read-only here, it arrives with each sync. Tasks canopy owns (work ${trackerName} doesn't know) move on the board as usual.`
                  : "No tracker feeds it yet: switch its tracking to bind one, or back to native."}
            </p>
          </div>
          {mayChange && (
            <div className="flex flex-wrap gap-2">
              {bound && (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      setNotice(null);
                      sync.mutate(false);
                    }}
                    disabled={busy || syncReason !== null}
                    className={primary}
                  >
                    {sync.isPending && sync.variables === false ? "Syncing…" : "Sync now"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setNotice(null);
                      sync.mutate(true);
                    }}
                    disabled={busy || syncReason !== null}
                    title={`Re-read everything and refresh ${trackerName}'s statuses`}
                    className={secondary}
                  >
                    {sync.isPending && sync.variables === true ? "Syncing…" : "Full re-sync"}
                  </button>
                </>
              )}
              {binding && (
                <button
                  type="button"
                  onClick={() => {
                    setNotice(null);
                    setPanel(panel === "edit" ? null : "edit");
                  }}
                  aria-expanded={panel === "edit"}
                  disabled={!catalog.data}
                  className={secondary}
                >
                  Edit binding
                </button>
              )}
              {canPublish && (
                <button
                  type="button"
                  onClick={confirmPublish}
                  disabled={busy || publishReason !== null || t.canopy_owned === 0}
                  className={secondary}
                >
                  {publish.isPending ? "Publishing…" : "Publish open tasks…"}
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  setNotice(null);
                  setPanel(panel === "switch" ? null : "switch");
                }}
                aria-expanded={panel === "switch"}
                className={secondary}
              >
                Switch tracking…
              </button>
            </div>
          )}
        </div>
        {mayChange && unavailable.length > 0 && (
          <ul className="mt-3 space-y-0.5 text-xs text-slate-500">
            {unavailable.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
        {t.can_edit && !integrationsOn && (
          <p className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
            Integrations are turned off in this workspace (feature <code>integrations</code>) — tracking can be read
            here, but not synced or changed.
          </p>
        )}
        {notice && (
          <div
            role={notice.error ? "alert" : "status"}
            className={`mt-3 rounded border px-3 py-2 text-sm ${
              notice.error ? "border-red-200 bg-red-50 text-red-700" : "border-canopy-500/30 bg-canopy-50 text-canopy-700"
            }`}
          >
            {notice.text}
            {notice.details && notice.details.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-xs">
                {notice.details.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      {panel === "switch" && mayChange && (
        <SwitchWizard
          projectId={projectId}
          tracking={t}
          fromLabel={t.mode === "mirrored" ? label : null}
          catalog={catalog.data}
          connections={connections.data}
          connectionsLoading={connections.isLoading}
          connectionsError={connections.isError ? trackingFailure(connections.error).message : null}
          onClose={() => setPanel(null)}
        />
      )}

      {binding && (
        <section aria-labelledby="tracking-binding" className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 id="tracking-binding" className="font-semibold text-slate-800">
            Binding
          </h3>
          <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-[10rem_1fr]">
            <dt className="text-slate-500">Connection</dt>
            <dd className="text-slate-800">
              {binding.connection_name ?? `Connection #${binding.connection_id}`}{" "}
              <span className="text-slate-500">· {binding.label}</span>
            </dd>
            <dt className="text-slate-500">Scope</dt>
            <dd>
              <Entries
                entries={labelledEntries(binding.scope, scopeFields)}
                empty={`Everything the connection sees in ${binding.label}`}
              />
            </dd>
            {Object.keys(binding.mapping).length > 0 && (
              <>
                <dt className="text-slate-500">Mapping</dt>
                <dd>
                  <Entries entries={labelledEntries(binding.mapping)} empty="" />
                </dd>
              </>
            )}
            <dt className="text-slate-500">{binding.label} statuses</dt>
            <dd>
              {binding.status_map.length > 0 ? (
                <StatusChips statuses={binding.status_map} />
              ) : (
                <span className="text-slate-500">They arrive with the next full sync — until then the board shows the statuses its cards carry.</span>
              )}
            </dd>
            <dt className="text-slate-500">Last synced</dt>
            <dd className="text-slate-800">
              {binding.last_synced_at ? (
                <time dateTime={parseUtc(binding.last_synced_at).toISOString()} title={parseUtc(binding.last_synced_at).toLocaleString()}>
                  {timeAgo(binding.last_synced_at)}
                </time>
              ) : (
                <span className="text-slate-500">Not yet</span>
              )}
            </dd>
            <dt className="text-slate-500">Sprints</dt>
            <dd className="text-slate-800">
              {!iterations
                ? `${binding.label} has no sprints to mirror`
                : binding.sync_iterations
                  ? `Mirrored from ${binding.label} (read-only in canopy)`
                  : "Not mirrored"}
            </dd>
          </dl>
          {panel === "edit" && mayChange && (
            <div className="mt-4">
              <BindingEditor
                projectId={projectId}
                binding={binding}
                tracker={tracker}
                capabilities={t.capabilities}
                onDone={(message) => {
                  setPanel(null);
                  if (message) setNotice({ text: message, error: false });
                }}
              />
            </div>
          )}
        </section>
      )}

      {t.history.length > 0 && (
        <section aria-labelledby="tracking-history" className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 id="tracking-history" className="font-semibold text-slate-800">
            Past trackers
          </h3>
          <ul className="mt-2 divide-y divide-slate-100">
            {t.history.map((b) => {
              const fields = schemaFields(trackerInfo(catalog.data, b.provider)?.scope_schema);
              const scope = labelledEntries(b.scope, fields).map((e) => e.value).join(" · ");
              return (
                <li key={b.id} className="flex flex-wrap items-baseline gap-x-2 py-2 text-sm">
                  <span className="font-medium text-slate-800">{b.label}</span>
                  <span className="text-slate-600">{b.connection_name ?? `connection #${b.connection_id}`}</span>
                  {scope && <span className="font-mono text-xs text-slate-500">{scope}</span>}
                  <span className="ml-auto text-xs text-slate-500">
                    {localDate(b.created_at)} – {b.detached_at ? localDate(b.detached_at) : "?"}
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="mt-2 text-xs text-slate-500">
            Tasks that left a tracker keep the link to their item as history (“formerly …”).
          </p>
        </section>
      )}
    </div>
  );
}
