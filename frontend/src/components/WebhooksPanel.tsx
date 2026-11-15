import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  OutboundWebhook,
  RuleScope,
  RuleScopeInfo,
  WebhookCatalog,
  WebhookDelivery,
  WebhookEvent,
  WebhookTestResult,
} from "../api/types";
import { refusalText } from "../lib/execution";
import {
  EVENT_HELP,
  EVENT_LABEL,
  draftFromHook,
  emptyHookDraft,
  hookBody,
  hookProblem,
  hookStatusText,
  type HookDraft,
} from "../lib/notify";
import { ORIGIN_LABEL, addableScopes } from "../lib/policy";
import { timeAgo } from "../lib/proposals";
import { Icon } from "./icons";

/** Where the webhooks are shown: a project (everything that reaches it), a team, or the
 *  workspace (admins). */
export type WebhooksTarget = { kind: "project"; id: number } | { kind: "team"; id: number } | { kind: "workspace" };

/**
 * Outbound webhooks (USER_FLOWS §AE9): push starts for runners (`work.ready`) and decisions
 * waiting on people (`gate.*`) to Slack or anything that takes a signed JSON POST. Managed
 * where they live — the workspace by admins, a team by its directors and managers, a project
 * by its planners — and only people who may edit one see its full URL.
 */
export default function WebhooksPanel({ target }: { target: WebhooksTarget }) {
  const qc = useQueryClient();
  const param =
    target.kind === "project" ? `?project_id=${target.id}` : target.kind === "team" ? `?team_id=${target.id}` : "";
  const hooks = useQuery({
    queryKey: ["webhooks", target.kind, target.kind === "workspace" ? 0 : target.id],
    queryFn: () => api.get<OutboundWebhook[]>(`/outbound-webhooks${param}`),
  });
  const catalog = useQuery({
    queryKey: ["webhook-catalog"],
    queryFn: () => api.get<WebhookCatalog>("/outbound-webhooks/catalog"),
  });
  const scopes = useQuery({
    queryKey: ["webhook-scopes", target.kind, target.kind === "workspace" ? 0 : target.id],
    queryFn: () => api.get<RuleScopeInfo[]>(`/outbound-webhooks/scopes${param}`),
    enabled: target.kind !== "workspace",
  });
  const workspaceScope: RuleScopeInfo = { scope_level: "workspace", scope_id: 0, name: "Workspace", can_edit: true };
  const addable = target.kind === "workspace" ? [workspaceScope] : addableScopes(scopes.data);
  const [draft, setDraft] = useState<{ value: HookDraft; editing: OutboundWebhook | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tested, setTested] = useState<Record<number, WebhookTestResult>>({});
  const [openLog, setOpenLog] = useState<number | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["webhooks"] });
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/outbound-webhooks/${id}`),
    onSuccess: refresh,
    onError: (e) => setError(refusalText(e)),
  });
  const toggle = useMutation({
    mutationFn: (hook: OutboundWebhook) => api.patch(`/outbound-webhooks/${hook.id}`, { enabled: !hook.enabled }),
    onSuccess: refresh,
    onError: (e) => setError(refusalText(e)),
  });
  const test = useMutation({
    mutationFn: (id: number) => api.post<WebhookTestResult>(`/outbound-webhooks/${id}/test`),
    onSuccess: (result, id) => {
      setTested((prev) => ({ ...prev, [id]: result }));
      refresh();
    },
    onError: (e) => setError(refusalText(e)),
  });

  const list = hooks.data ?? [];
  const shown = target.kind === "workspace" ? list.filter((h) => h.scope_level === "workspace") : list;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h2 className="text-lg font-semibold">Notifications</h2>
          <p className="text-sm text-slate-500">
            Point a runner at <code className="text-xs">work.ready</code> so sessions start when delegated work is
            ready, and Slack at decisions waiting on people. JSON deliveries are signed (
            <code className="text-xs">{catalog.data?.signature_header ?? "X-Canopy-Signature"}: sha256=…</code> over the
            body) and carry ids and keys only — never what an agent wrote.
          </p>
          {catalog.data && (
            <p className="mt-1 text-xs text-slate-500">
              Email to the people who may decide:{" "}
              {catalog.data.email_enabled ? "on" : "off (an admin sets NOTIFY_EMAIL_GATES and SMTP)"}.
            </p>
          )}
        </div>
        {addable.length > 0 && (
          <button
            type="button"
            onClick={() => {
              setError(null);
              setDraft({ value: emptyHookDraft(addable[addable.length - 1]), editing: null });
            }}
            className="flex items-center gap-1 rounded-md bg-canopy-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-canopy-700"
          >
            <Icon name="plus" size={14} /> Add webhook
          </button>
        )}
      </div>
      {error && <p className="rounded-md bg-red-50 p-2 text-sm text-red-700">{error}</p>}
      {hooks.isError ? (
        <p className="text-sm text-red-700">Couldn’t load the webhooks: {refusalText(hooks.error)}</p>
      ) : hooks.isLoading ? (
        <p className="text-sm text-slate-500">Loading webhooks…</p>
      ) : shown.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-200 p-4 text-sm text-slate-400">
          No webhooks yet.
        </p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
          {shown.map((hook) => (
            <li key={hook.id} className={`space-y-1 p-3 ${hook.enabled ? "" : "opacity-60"}`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{hook.name}</span>
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
                  {ORIGIN_LABEL[hook.scope_level as RuleScope]}
                  {hook.scope_level !== "workspace" && hook.scope_name ? ` · ${hook.scope_name}` : ""}
                </span>
                <span className="text-[11px] text-slate-500">
                  {hook.format === "slack" ? "Slack message" : hook.has_secret ? "JSON, signed" : "JSON, unsigned"}
                </span>
                <code className="truncate text-[11px] text-slate-400">{hook.url}</code>
              </div>
              <div className="flex flex-wrap gap-1">
                {hook.events.map((e) => (
                  <span key={e} title={EVENT_HELP[e]} className="rounded border border-slate-200 px-1.5 text-[11px] text-slate-600">
                    {EVENT_LABEL[e] ?? e}
                  </span>
                ))}
              </div>
              <p className={`text-xs ${hook.consecutive_failures ? "text-red-700" : "text-slate-500"}`}>
                {hookStatusText(hook, timeAgo)}
                {tested[hook.id] &&
                  ` — test: ${tested[hook.id].delivered ? `delivered (${tested[hook.id].response_status})` : tested[hook.id].error}`}
              </p>
              {hook.can_edit && (
                <div className="flex flex-wrap gap-3 text-xs">
                  <button
                    type="button"
                    onClick={() => {
                      setError(null);
                      setDraft({ value: draftFromHook(hook), editing: hook });
                    }}
                    className="font-medium text-canopy-700 hover:underline"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => test.mutate(hook.id)}
                    disabled={test.isPending}
                    className="font-medium text-canopy-700 hover:underline disabled:opacity-50"
                  >
                    Send a test
                  </button>
                  <button type="button" onClick={() => toggle.mutate(hook)} className="font-medium text-slate-600 hover:underline">
                    {hook.enabled ? "Switch off" : "Switch on"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setOpenLog(openLog === hook.id ? null : hook.id)}
                    className="font-medium text-slate-600 hover:underline"
                  >
                    {openLog === hook.id ? "Hide deliveries" : "Deliveries"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (window.confirm(`Delete the webhook “${hook.name}”?`)) remove.mutate(hook.id);
                    }}
                    className="font-medium text-red-700 hover:underline"
                  >
                    Delete
                  </button>
                </div>
              )}
              {openLog === hook.id && <Deliveries hookId={hook.id} />}
            </li>
          ))}
        </ul>
      )}
      {draft && catalog.data && (
        <HookDialog
          initial={draft.value}
          editing={draft.editing}
          scopes={addable}
          events={catalog.data.events}
          onClose={() => setDraft(null)}
          onSaved={() => {
            setDraft(null);
            refresh();
          }}
        />
      )}
    </div>
  );
}

function Deliveries({ hookId }: { hookId: number }) {
  const rows = useQuery({
    queryKey: ["webhook-deliveries", hookId],
    queryFn: () => api.get<WebhookDelivery[]>(`/outbound-webhooks/${hookId}/deliveries`),
  });
  if (!rows.data) return <p className="text-xs text-slate-400">Loading…</p>;
  if (rows.data.length === 0) return <p className="text-xs text-slate-400">Nothing sent yet.</p>;
  return (
    <ul className="mt-1 space-y-0.5 border-l border-slate-200 pl-2 text-[11px] text-slate-600">
      {rows.data.map((d) => (
        <li key={d.id}>
          <span className="text-slate-400">{timeAgo(d.created_at)}</span> · {d.event} ·{" "}
          <span className={d.status === "failed" ? "text-red-700" : d.status === "pending" ? "text-amber-700" : ""}>
            {d.status}
            {d.response_status ? ` ${d.response_status}` : ""}
          </span>
          {d.attempts > 1 ? ` · ${d.attempts} attempts` : ""}
          {d.last_error ? ` — ${d.last_error}` : ""}
        </li>
      ))}
    </ul>
  );
}

function HookDialog({
  initial,
  editing,
  scopes,
  events,
  onClose,
  onSaved,
}: {
  initial: HookDraft;
  editing: OutboundWebhook | null;
  scopes: RuleScopeInfo[];
  events: WebhookEvent[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [d, setD] = useState<HookDraft>(initial);
  const set = (patch: Partial<HookDraft>) => setD((prev) => ({ ...prev, ...patch }));
  const problem = hookProblem(d, Boolean(editing));
  const save = useMutation({
    mutationFn: () =>
      editing
        ? api.patch(`/outbound-webhooks/${editing.id}`, hookBody(d, true))
        : api.post("/outbound-webhooks", hookBody(d, false)),
    onSuccess: onSaved,
  });
  const input = "w-full rounded-md border border-slate-300 px-2 py-1 text-sm";
  return (
    <div role="dialog" aria-modal aria-label={editing ? `Edit webhook ${editing.name}` : "Add a webhook"} className="fixed inset-0 z-50 flex justify-end bg-black/30">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!problem) save.mutate();
        }}
        className="h-full w-full max-w-lg space-y-3 overflow-y-auto bg-white p-5 shadow-xl"
      >
        <div className="flex items-start justify-between">
          <h2 className="text-lg font-semibold">{editing ? "Edit webhook" : "Add a webhook"}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-slate-600">
            <Icon name="close" size={18} />
          </button>
        </div>
        {!editing && (
          <label className="block space-y-1 text-sm">
            <span className="font-medium">Where it lives</span>
            <select className={input} value={d.scope} onChange={(e) => set({ scope: e.target.value })}>
              {scopes.map((s) => (
                <option key={`${s.scope_level}:${s.scope_id}`} value={`${s.scope_level}:${s.scope_id}`}>
                  {s.scope_level === "workspace" ? "The workspace" : `${ORIGIN_LABEL[s.scope_level]} · ${s.name}`}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="block space-y-1 text-sm">
          <span className="font-medium">Name</span>
          <input className={input} value={d.name} maxLength={120} onChange={(e) => set({ name: e.target.value })} />
        </label>
        <fieldset className="space-y-1 text-sm">
          <legend className="font-medium">Format</legend>
          <label className="mr-4 inline-flex items-center gap-1">
            <input type="radio" checked={d.format === "json"} onChange={() => set({ format: "json" })} /> JSON (a runner,
            a service)
          </label>
          <label className="inline-flex items-center gap-1">
            <input type="radio" checked={d.format === "slack"} onChange={() => set({ format: "slack" })} /> Slack message
          </label>
        </fieldset>
        <label className="block space-y-1 text-sm">
          <span className="font-medium">URL</span>
          <input className={`${input} font-mono`} value={d.url} placeholder="https://…" onChange={(e) => set({ url: e.target.value })} />
          {d.format === "slack" && (
            <span className="text-xs text-slate-500">A Slack incoming-webhook URL — treat it like a password.</span>
          )}
        </label>
        {d.format === "json" && (
          <label className="block space-y-1 text-sm">
            <span className="font-medium">Signing secret</span>
            <input
              className={input}
              type="password"
              autoComplete="new-password"
              value={d.secret}
              placeholder={editing?.has_secret ? "unchanged — type to replace" : "optional"}
              onChange={(e) => set({ secret: e.target.value })}
            />
            {editing?.has_secret && (
              <label className="flex items-center gap-1 text-xs text-slate-600">
                <input type="checkbox" checked={d.clearSecret} onChange={(e) => set({ clearSecret: e.target.checked })} />
                Remove the secret (deliveries go unsigned)
              </label>
            )}
          </label>
        )}
        <fieldset className="space-y-1 text-sm">
          <legend className="font-medium">Send when</legend>
          {events.map((e) => (
            <label key={e} className="flex items-start gap-2">
              <input
                type="checkbox"
                className="mt-1"
                checked={d.events.includes(e)}
                onChange={(ev) =>
                  set({ events: ev.target.checked ? [...d.events, e] : d.events.filter((x) => x !== e) })
                }
              />
              <span>
                {EVENT_LABEL[e] ?? e} <code className="text-[11px] text-slate-400">{e}</code>
                <span className="block text-xs text-slate-500">{EVENT_HELP[e]}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={d.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> On
        </label>
        {(save.error || problem) && (
          <p className={`text-sm ${save.error ? "text-red-700" : "text-slate-500"}`}>
            {save.error ? refusalText(save.error) : problem}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="rounded-md px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100">
            Cancel
          </button>
          <button
            type="submit"
            disabled={Boolean(problem) || save.isPending}
            className="rounded-md bg-canopy-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-canopy-700 disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
