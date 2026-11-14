import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { switchProjectTracking } from "../../api/trackers";
import type {
  Connection,
  ProjectTracking,
  TrackerCatalog,
  TrackingStrategy,
  TrackingSwitchRequest,
  TrackingSwitchResult,
} from "../../api/types";
import { trackingFailure } from "../../lib/board";
import {
  actionDetail,
  capabilityNotes,
  groupPlan,
  jsonText,
  modeHeadline,
  planSummary,
  prefillMapping,
  prefillScope,
  providerLabel,
  schemaFields,
  strategyOptions,
  switchRequest,
  trackerConnections,
  trackerInfo,
  type FormValues,
} from "../../lib/tracking";
import { invalidateTracking } from "../../lib/trackingCache";
import { SchemaInputs } from "./SchemaInputs";

type Step = "target" | "configure" | "preview" | "result";
type Target = "native" | number;

const STEP_LABELS: Record<Step, string> = {
  target: "Target",
  configure: "Scope & strategy",
  preview: "Preview",
  result: "Done",
};

function Choice({
  name,
  checked,
  onSelect,
  disabled = false,
  title,
  hint,
  reason,
}: {
  name: string;
  checked: boolean;
  onSelect: () => void;
  disabled?: boolean;
  title: string;
  hint?: ReactNode;
  reason?: string | null;
}) {
  return (
    <label
      className={`flex items-start gap-3 rounded-md border px-3 py-2 ${
        checked ? "border-canopy-500 bg-canopy-50" : "border-slate-200"
      } ${disabled ? "cursor-not-allowed bg-slate-50" : "cursor-pointer hover:border-slate-300"}`}
    >
      <input
        type="radio"
        name={name}
        checked={checked}
        onChange={onSelect}
        disabled={disabled}
        className="mt-1"
      />
      <span>
        <span className={`block text-sm font-medium ${disabled ? "text-slate-500" : "text-slate-800"}`}>
          {title}
        </span>
        {hint && <span className="block text-xs text-slate-500">{hint}</span>}
        {reason && <span className="mt-0.5 block text-xs text-amber-800">{reason}</span>}
      </span>
    </label>
  );
}

const button =
  "rounded px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50";
const primary = `${button} bg-canopy-700 text-white hover:bg-canopy-500`;
const secondary = `${button} border border-slate-300 bg-white text-slate-700 hover:bg-slate-50`;

/**
 * Switch a project between native and mirrored tracking, or onto another tracker (§C12.2):
 * pick the target, say where in the tracker and what happens to the existing tasks, preview the
 * plan (nothing changes until then), apply exactly that plan. Applying re-assigns who owns each
 * task's status, so it asks first.
 */
export default function SwitchWizard({
  projectId,
  tracking,
  fromLabel,
  catalog,
  connections,
  connectionsLoading,
  connectionsError,
  onClose,
}: {
  projectId: number;
  tracking: ProjectTracking;
  /** The tracker the project leaves, if it is mirrored. */
  fromLabel: string | null;
  catalog: TrackerCatalog | undefined;
  connections: Connection[] | undefined;
  connectionsLoading: boolean;
  connectionsError: string | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>("target");
  const [target, setTarget] = useState<Target | null>(null);
  const [scopeValues, setScopeValues] = useState<FormValues>({});
  const [mappingText, setMappingText] = useState("");
  const [syncIterations, setSyncIterations] = useState(false);
  const [strategy, setStrategy] = useState<TrackingStrategy>("keep_separate");
  const [errors, setErrors] = useState<string[]>([]);
  const [preview, setPreview] = useState<{
    request: TrackingSwitchRequest;
    result: TrackingSwitchResult;
  } | null>(null);
  const [applied, setApplied] = useState<TrackingSwitchResult | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Each step announces itself: focus its heading.
  useEffect(() => {
    headingRef.current?.focus();
  }, [step]);

  const eligible = trackerConnections(connections, tracking.trackers_enabled);
  const connection = typeof target === "number" ? (eligible.find((c) => c.id === target) ?? null) : null;
  const tracker = trackerInfo(catalog, connection?.provider);
  const toLabel = connection ? providerLabel(connection.provider, catalog) : null;
  const scopeFields = useMemo(() => schemaFields(tracker?.scope_schema), [tracker]);
  const strategies = tracker ? strategyOptions(tracker, connection) : [];
  const steps: Step[] =
    target === "native" ? ["target", "preview", "result"] : ["target", "configure", "preview", "result"];

  const run = useMutation({
    mutationFn: (request: TrackingSwitchRequest) => switchProjectTracking(projectId, request),
    onSuccess: (result, request) => {
      if (request.dry_run) {
        setPreview({ request, result });
        setStep("preview");
      } else {
        setApplied(result);
        setStep("result");
        void invalidateTracking(qc, projectId);
      }
    },
    onError: (err) => setErrors([trackingFailure(err).message]),
  });

  const choose = (next: Target) => {
    setTarget(next);
    setErrors([]);
    setPreview(null);
    if (next === "native") return;
    const picked = eligible.find((c) => c.id === next);
    const info = trackerInfo(catalog, picked?.provider);
    setScopeValues(prefillScope(schemaFields(info?.scope_schema), picked?.config));
    setMappingText(jsonText(prefillMapping(picked?.config)));
    // The server's own default for a connection's binding: mirror sprints when it names a board.
    const board = picked?.config.board_id;
    setSyncIterations(Boolean(info?.capabilities.iterations) && board !== undefined && board !== null && board !== "");
    setStrategy("keep_separate");
  };

  const runPreview = () => {
    const built = switchRequest({
      target,
      scopeFields,
      scopeValues,
      mappingText,
      syncIterations,
      strategy,
      capabilities: tracker?.capabilities ?? null,
    });
    if (!built.request) {
      setErrors(built.errors);
      return;
    }
    setErrors([]);
    run.mutate(built.request);
  };

  const apply = () => {
    if (!preview) return;
    const { result } = preview;
    const publishing = result.counts.publish ?? 0;
    const lines = [
      `Switch this project to “${modeHeadline(result.to_mode, toLabel)}”?`,
      "",
      planSummary(result.counts),
      "",
      `This changes who owns each task's status${
        publishing > 0 ? ` and creates ${publishing} item${publishing === 1 ? "" : "s"} in ${toLabel}` : ""
      }.${fromLabel ? ` Links to ${fromLabel} items are kept as history.` : ""}`,
    ];
    if (!window.confirm(lines.join("\n"))) return;
    setErrors([]);
    run.mutate({ ...preview.request, dry_run: false });
  };

  const back = () => {
    setErrors([]);
    setPreview(null);
    setStep(step === "preview" && target !== "native" ? "configure" : "target");
  };

  const targetReason = (c: Connection): string | null => {
    if (tracking.binding?.connection_id === c.id) {
      return "Its current tracker — change the scope with Edit binding instead.";
    }
    if (!trackerInfo(catalog, c.provider)) return "canopy doesn't know this tracker.";
    return null;
  };

  const groups = preview
    ? groupPlan(preview.result.actions, {
        from: fromLabel,
        to: toLabel,
        toMode: preview.result.to_mode,
      })
    : [];

  return (
    <section
      aria-labelledby="switch-tracking-heading"
      className="space-y-4 rounded-lg border border-canopy-500/40 bg-white p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3
          id="switch-tracking-heading"
          ref={headingRef}
          tabIndex={-1}
          className="font-semibold text-slate-800 outline-none"
        >
          Switch tracking — {STEP_LABELS[step]}
        </h3>
        <ol aria-label="Steps" className="flex flex-wrap gap-1 text-xs">
          {steps.map((s, i) => (
            <li
              key={s}
              aria-current={s === step ? "step" : undefined}
              className={`rounded-full px-2 py-0.5 ${
                s === step ? "bg-canopy-50 font-medium text-canopy-700" : "text-slate-500"
              }`}
            >
              {i + 1}. {STEP_LABELS[s]}
            </li>
          ))}
        </ol>
      </div>

      {step === "target" && (
        <>
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm text-slate-600">Where should this project's statuses live?</legend>
            <Choice
              name="tracking-target"
              checked={target === "native"}
              onSelect={() => choose("native")}
              disabled={tracking.mode === "native"}
              title="Native — canopy owns every status"
              hint="The board is the source of truth. Tasks a tracker owned are released to canopy, their links kept as history."
              reason={tracking.mode === "native" ? "The project is native already." : null}
            />
            {eligible.map((c) => {
              const info = trackerInfo(catalog, c.provider);
              const reason = targetReason(c);
              return (
                <Choice
                  key={c.id}
                  name="tracking-target"
                  checked={target === c.id}
                  onSelect={() => choose(c.id)}
                  disabled={reason !== null}
                  title={`Mirror from ${providerLabel(c.provider, catalog)} · ${c.name}`}
                  hint={info ? capabilityNotes(info.capabilities).join(" · ") : undefined}
                  reason={reason}
                />
              );
            })}
          </fieldset>
          {connectionsLoading && <p className="text-sm text-slate-500">Loading tracker connections…</p>}
          {connectionsError && (
            <p role="alert" className="text-sm text-red-700">
              Couldn’t load the tracker connections: {connectionsError}
            </p>
          )}
          {!connectionsLoading && !connectionsError && eligible.length === 0 && (
            <p className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
              {tracking.trackers_enabled.length === 0 ? (
                <>No tracker is enabled on this instance (<code>TRACKERS_ENABLED</code>), so the project stays native.</>
              ) : (
                <>
                  No {tracking.trackers_enabled.map((p) => providerLabel(p, catalog)).join(" or ")} connection to
                  mirror from yet —{" "}
                  <Link to="/connectors" className="font-medium text-canopy-700 hover:underline">
                    add one on Connectors
                  </Link>
                  .
                </>
              )}
            </p>
          )}
        </>
      )}

      {step === "configure" && tracker && toLabel && (
        <>
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium text-slate-700">Where in {toLabel}</legend>
            <SchemaInputs
              fields={scopeFields}
              values={scopeValues}
              onChange={(key, value) => setScopeValues((prev) => ({ ...prev, [key]: value }))}
              idPrefix="switch-scope"
            />
            <p className="text-xs text-slate-500">
              Prefilled from the connection’s settings. One {toLabel} selection feeds one project.
            </p>
          </fieldset>
          {tracker.capabilities.iterations && (
            <label className="flex items-start gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={syncIterations}
                onChange={(e) => setSyncIterations(e.target.checked)}
                className="mt-1"
              />
              <span>
                Mirror {toLabel}’s sprints
                <span className="block text-xs text-slate-500">
                  For a team that runs sprints: they then come from {toLabel} and are read-only in canopy.
                </span>
              </span>
            </label>
          )}
          <details className="rounded-md border border-slate-200 px-3 py-2">
            <summary className="cursor-pointer text-sm font-medium text-slate-600">
              Advanced mapping (JSON)
            </summary>
            <textarea
              aria-label="Advanced mapping (JSON)"
              value={mappingText}
              onChange={(e) => setMappingText(e.target.value)}
              rows={4}
              spellCheck={false}
              placeholder='{"epic_types": ["Epic"], "estimate_field": "customfield_10016"}'
              className="mt-2 w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
            />
            <p className="text-xs text-slate-500">
              Which item types are epics, the estimate field… Prefilled from the connection’s settings.
            </p>
          </details>
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium text-slate-700">
              What happens to the tasks the project already has
            </legend>
            {strategies.map((o) => (
              <Choice
                key={o.value}
                name="tracking-strategy"
                checked={strategy === o.value}
                onSelect={() => setStrategy(o.value)}
                disabled={o.disabledReason !== null}
                title={o.label}
                hint={o.description}
                reason={o.disabledReason}
              />
            ))}
          </fieldset>
        </>
      )}

      {step === "preview" && preview && (
        <div className="space-y-3">
          <p className="text-sm text-slate-700">
            Nothing has changed yet. Switching to{" "}
            <span className="font-medium">{modeHeadline(preview.result.to_mode, toLabel)}</span>
            {preview.result.to_mode === "mirrored" && (
              <> ({strategies.find((o) => o.value === preview.result.strategy)?.label.toLowerCase() ?? preview.result.strategy})</>
            )}
            : <span className="font-medium">{planSummary(preview.result.counts)}</span>.
          </p>
          {preview.result.warnings.length > 0 && (
            <ul className="space-y-1 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {preview.result.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          {groups.length === 0 && (
            <p className="text-sm text-slate-500">The project has no tasks yet — only its tracking changes.</p>
          )}
          {groups.map((g) => (
            <details
              key={g.action}
              open={g.action !== "keep" || g.items.length <= 12}
              className="rounded-md border border-slate-200"
            >
              <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-slate-800">
                {g.label} <span className="font-normal tabular-nums text-slate-500">· {g.items.length}</span>
              </summary>
              {g.hint && <p className="px-3 pb-1 text-xs text-slate-500">{g.hint}</p>}
              <div className="overflow-x-auto px-3 pb-2">
                <table className="w-full min-w-[32rem] table-fixed text-left text-sm">
                  <caption className="sr-only">
                    {g.label}: {g.items.length} task{g.items.length === 1 ? "" : "s"}
                  </caption>
                  <thead className="text-xs uppercase tracking-wide text-slate-400">
                    <tr>
                      <th scope="col" className="w-32 py-1 pr-3 font-medium">Key</th>
                      <th scope="col" className="py-1 pr-3 font-medium">Task</th>
                      <th scope="col" className="w-1/3 py-1 font-medium">Detail</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {g.items.map((a) => (
                      <tr key={a.task_id}>
                        <td className="truncate py-1 pr-3 font-mono text-xs text-slate-500">{a.key ?? "—"}</td>
                        <td className="py-1 pr-3 break-words text-slate-800">{a.name}</td>
                        <td className="py-1 break-words text-slate-500">{actionDetail(a, catalog)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          ))}
        </div>
      )}

      {step === "result" && applied && (
        <div className="space-y-2" role="status">
          <p className="text-sm font-medium text-canopy-700">
            Switched — {modeHeadline(applied.to_mode, toLabel)}.
          </p>
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
            <li>{planSummary(applied.counts)}</li>
            {applied.published && (
              <li>
                Published to {toLabel}: {applied.published.created} created · {applied.published.skipped} already
                there · {applied.published.failed} failed
              </li>
            )}
            {applied.to_mode === "mirrored" && tracker?.capabilities.direct_read && applied.synced_created != null && (
              <li>
                First sync from {toLabel}: {applied.synced_created} created · {applied.synced_updated ?? 0} updated
              </li>
            )}
          </ul>
          {(applied.published?.errors.length ?? 0) > 0 && (
            <ul className="space-y-0.5 text-xs text-red-700">
              {applied.published?.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
          {applied.warnings.length > 0 && (
            <ul className="space-y-1 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {applied.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {errors.length > 0 && (
        <ul role="alert" className="space-y-0.5 text-sm text-red-700">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-3">
        {step === "result" ? (
          <button type="button" onClick={onClose} className={primary}>
            Done
          </button>
        ) : (
          <>
            {step === "target" && (
              <button
                type="button"
                onClick={target === "native" ? runPreview : () => setStep("configure")}
                disabled={target === null || run.isPending}
                className={primary}
              >
                {target === "native" ? (run.isPending ? "Previewing…" : "Preview") : "Next"}
              </button>
            )}
            {step === "configure" && (
              <button type="button" onClick={runPreview} disabled={run.isPending} className={primary}>
                {run.isPending ? "Previewing…" : "Preview"}
              </button>
            )}
            {step === "preview" && (
              <button type="button" onClick={apply} disabled={run.isPending} className={primary}>
                {run.isPending ? "Applying…" : "Apply switch…"}
              </button>
            )}
            {step !== "target" && (
              <button type="button" onClick={back} disabled={run.isPending} className={secondary}>
                Back
              </button>
            )}
            <button type="button" onClick={onClose} disabled={run.isPending} className={secondary}>
              Cancel
            </button>
          </>
        )}
      </div>
    </section>
  );
}
