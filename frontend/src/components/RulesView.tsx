import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { ADR, DeliveryRule, EffectiveRule, RuleScope, RuleScopeInfo, RuleWrite } from "../api/types";
import { refusalText } from "../lib/execution";
import {
  ENFORCEMENTS,
  ORIGIN_LABEL,
  addableScopes,
  draftFrom,
  draftProblem,
  emptyDraft,
  inheritedFrom,
  ruleBody,
  ruleEffectText,
  ruleReachText,
  slugKey,
  type RuleDraft,
} from "../lib/policy";
import { featureOn, useFeatures } from "../lib/useFeatures";
import { Icon } from "./icons";

/** Where the rules are shown: a project (its resolved rules) or a team (its own, beside the
 *  workspace's it inherits). */
export type RulesTarget = { kind: "project"; id: number } | { kind: "team"; id: number };

const ORIGIN_CHIP: Record<RuleScope, string> = {
  workspace: "bg-slate-100 text-slate-600",
  team: "bg-sky-50 text-sky-700",
  project: "bg-canopy-50 text-canopy-700",
};

/** One row: a rule as it applies here. */
interface Row {
  rule: DeliveryRule;
  origin: RuleScope;
  enforcement: DeliveryRule["enforcement"];
  overrides: RuleScope[];
  stale: boolean;
  staleReason: string | null;
  canEdit: boolean;
  /** Why the rule doesn't apply as written here: overridden or switched off below, or held
   *  back by a locked rule above. Such a row is shown dimmed and offers no override. */
  inactive?: string;
}

function fromEffective(e: EffectiveRule): Row {
  return {
    rule: e.rule,
    origin: e.origin,
    enforcement: e.enforcement,
    overrides: e.overrides,
    stale: e.stale,
    staleReason: e.stale_reason,
    canEdit: e.can_edit,
  };
}

/**
 * Rules — team and project working agreements and the Definition of Done
 * (docs/AGENT_EXECUTION.md §10). A project shows its resolved set: workspace, then team, then
 * its own; nearest wins unless a rule is locked; for Definition-of-Done items the stricter
 * enforcement wins. People edit them where they may; agents only read them (in the brief).
 */
export default function RulesView({ target }: { target: RulesTarget }) {
  const qc = useQueryClient();
  const features = useFeatures();
  const here: RuleScope = target.kind;
  const param = target.kind === "project" ? `project_id=${target.id}` : `team_id=${target.id}`;
  const scopes = useQuery({
    queryKey: ["rule-scopes", target.kind, target.id],
    queryFn: () => api.get<RuleScopeInfo[]>(`/rules/scopes?${param}`),
  });
  const effective = useQuery({
    queryKey: ["rules-effective", target.id],
    queryFn: () => api.get<EffectiveRule[]>(`/rules/effective?project_id=${target.id}`),
    enabled: target.kind === "project",
  });
  const own = useQuery({
    queryKey: ["rules", here, target.id],
    queryFn: () => api.get<DeliveryRule[]>(`/rules?scope_level=${here}&scope_id=${target.id}`),
  });
  const workspace = useQuery({
    queryKey: ["rules", "workspace", 0],
    queryFn: () => api.get<DeliveryRule[]>("/rules?scope_level=workspace&scope_id=0"),
    enabled: target.kind === "team",
  });
  const adrs = useQuery({
    queryKey: ["adrs", target.id],
    queryFn: () => api.get<ADR[]>(`/architecture/adrs?project_id=${target.id}`),
    enabled: target.kind === "project" && featureOn(features, "architecture"),
  });
  const [draft, setDraft] = useState<{ value: RuleDraft; editing: DeliveryRule | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["rules"] });
    void qc.invalidateQueries({ queryKey: ["rules-effective"] });
  };
  const remove = useMutation({
    mutationFn: (ruleId: number) => api.del(`/rules/${ruleId}`),
    onSuccess: refresh,
    onError: (e) => setError(refusalText(e)),
  });
  const switchOff = useMutation({
    mutationFn: (rule: DeliveryRule) =>
      api.post("/rules", {
        scope_level: here,
        scope_id: target.id,
        key: rule.key,
        title: rule.title,
        kind: rule.kind,
        disabled: true,
      }),
    onSuccess: refresh,
    onError: (e) => setError(refusalText(e)),
  });

  const hereScope = scopes.data?.find((s) => s.scope_level === here);
  const mayEditHere = hereScope?.can_edit ?? false;
  const addable = addableScopes(scopes.data);
  const adrLabel = new Map((adrs.data ?? []).map((a) => [a.id, `ADR-${String(a.number).padStart(4, "0")} ${a.title}`]));

  let rows: Row[] = [];
  if (target.kind === "project") {
    rows = (effective.data ?? []).map(fromEffective);
  } else {
    const teamKeys = new Map((own.data ?? []).map((r) => [r.key, r]));
    const locked = new Set((workspace.data ?? []).filter((r) => r.locked && !r.disabled).map((r) => r.key));
    const workspaceCanEdit = scopes.data?.find((s) => s.scope_level === "workspace")?.can_edit ?? false;
    rows = [
      ...(workspace.data ?? [])
        .filter((r) => !r.disabled)
        .map<Row>((r) => {
          const below = r.locked ? undefined : teamKeys.get(r.key);
          return {
            rule: r,
            origin: "workspace",
            enforcement: r.enforcement,
            overrides: [],
            stale: false,
            staleReason: null,
            canEdit: workspaceCanEdit,
            inactive: below ? (below.disabled ? "switched off by the team" : "replaced by the team’s") : undefined,
          };
        }),
      ...(own.data ?? [])
        .filter((r) => !r.disabled)
        .map<Row>((r) => ({
          rule: r,
          origin: "team",
          enforcement: r.enforcement,
          overrides: [],
          stale: false,
          staleReason: null,
          canEdit: mayEditHere,
          inactive: locked.has(r.key) ? "not in effect — the workspace’s locked rule holds this key" : undefined,
        })),
    ];
  }
  if (target.kind === "project" && effective.data) {
    // The project's own rules that the merge set aside: a locked rule above holds the key.
    const inEffect = new Set(effective.data.map((e) => e.rule.id));
    for (const r of own.data ?? []) {
      if (r.disabled || inEffect.has(r.id)) continue;
      rows.push({
        rule: r,
        origin: "project",
        enforcement: r.enforcement,
        overrides: [],
        stale: false,
        staleReason: null,
        canEdit: mayEditHere,
        inactive: "not in effect — a locked rule above holds this key",
      });
    }
  }
  const switchedOff = (own.data ?? []).filter((r) => r.disabled);
  const dod = rows.filter((r) => r.rule.kind === "attestation");
  const guidance = rows.filter((r) => r.rule.kind === "guidance");
  const loading = scopes.isLoading || own.isLoading || effective.isLoading || workspace.isLoading;
  const failed = scopes.error ?? own.error ?? effective.error ?? workspace.error;

  const open = (value: RuleDraft, editing: DeliveryRule | null) => {
    setError(null);
    setDraft({ value, editing });
  };

  const section = (title: string, hint: string, list: Row[]) => (
    <section className="space-y-2">
      <div>
        <h3 className="font-semibold">{title}</h3>
        <p className="text-xs text-slate-500">{hint}</p>
      </div>
      {list.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-200 p-3 text-sm text-slate-400">None yet.</p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
          {list.map((row) => (
            <RuleRow
              key={`${row.origin}-${row.rule.id}`}
              row={row}
              here={here}
              adrLabel={row.rule.source_adr_id != null ? adrLabel.get(row.rule.source_adr_id) : undefined}
              mayActHere={mayEditHere}
              onEdit={() => open(draftFrom(row.rule), row.rule)}
              onDelete={() => {
                if (window.confirm(`Delete the rule “${row.rule.title}”?`)) remove.mutate(row.rule.id);
              }}
              onOverride={() => hereScope && open(draftFrom(row.rule, hereScope), null)}
              onSwitchOff={() => switchOff.mutate(row.rule)}
            />
          ))}
        </ul>
      )}
    </section>
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h2 className="text-lg font-semibold">Rules</h2>
          <p className="text-sm text-slate-500">
            {target.kind === "project"
              ? "The working agreements and Definition of Done this project’s work follows — the workspace’s, then the team’s, then its own. A rule lower down replaces one with the same key unless that one is locked."
              : "The team’s working agreements and Definition of Done, beside the workspace’s it inherits. Every project the team runs gets them; a project can override or switch off what isn’t locked."}{" "}
            Code conventions belong in the repository’s CLAUDE.md or AGENTS.md; hard constraints are entry checks.
          </p>
        </div>
        {addable.length > 0 && (
          <button
            type="button"
            onClick={() => open(emptyDraft(addable[addable.length - 1]), null)}
            className="flex items-center gap-1 rounded-md bg-canopy-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-canopy-700"
          >
            <Icon name="plus" size={14} /> Add rule
          </button>
        )}
      </div>
      {error && <p className="rounded-md bg-red-50 p-2 text-sm text-red-700">{error}</p>}
      {failed ? (
        <p className="text-sm text-red-700">Couldn’t load the rules: {refusalText(failed)}</p>
      ) : loading ? (
        <p className="text-sm text-slate-500">Loading rules…</p>
      ) : (
        <>
          {section(
            "Definition of Done",
            "Each hand-off attests these with evidence (done, n/a or not done); a reviewer can dispute one.",
            dod,
          )}
          {section("Guidance", "Delivered in every agent’s brief for the roles and work it names.", guidance)}
          {switchedOff.length > 0 && (
            <section className="space-y-1">
              <h3 className="text-sm font-semibold text-slate-600">Switched off here</h3>
              <ul className="space-y-1">
                {switchedOff.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center gap-2 text-sm text-slate-500">
                    <span className="line-through">{r.title}</span>
                    <code className="text-xs text-slate-400">{r.key}</code>
                    {mayEditHere && (
                      <button
                        type="button"
                        onClick={() => remove.mutate(r.id)}
                        className="text-xs font-medium text-canopy-700 hover:underline"
                      >
                        Turn back on
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
      {draft && (
        <RuleDialog
          initial={draft.value}
          editing={draft.editing}
          scopes={draft.editing ? (scopes.data ?? []) : addable}
          adrs={adrs.data ?? []}
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

function RuleRow({
  row,
  here,
  adrLabel,
  mayActHere,
  onEdit,
  onDelete,
  onOverride,
  onSwitchOff,
}: {
  row: Row;
  here: RuleScope;
  adrLabel: string | undefined;
  mayActHere: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onOverride: () => void;
  onSwitchOff: () => void;
}) {
  const { rule } = row;
  const inherited = inheritedFrom(row.origin, here);
  const tightened = rule.kind === "attestation" && row.enforcement !== rule.enforcement;
  return (
    <li className={`space-y-1 p-3 ${row.inactive ? "opacity-60" : ""}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{rule.title}</span>
        <code className="text-xs text-slate-400">{rule.key}</code>
        <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${ORIGIN_CHIP[row.origin]}`}>
          {ORIGIN_LABEL[row.origin]}
        </span>
        {rule.locked && (
          <span className="flex items-center gap-0.5 text-[11px] text-slate-500" title="Lower scopes can't override or switch it off">
            <Icon name="lock" size={11} /> locked
          </span>
        )}
        {row.overrides.length > 0 && (
          <span className="text-[11px] text-slate-500">replaces the {row.overrides.map((o) => ORIGIN_LABEL[o]).join(" and ")}’s</span>
        )}
        {row.inactive && <span className="text-[11px] text-slate-500">{row.inactive}</span>}
        {row.stale && (
          <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-800" title={row.staleReason ?? undefined}>
            stale — {row.staleReason ?? "its decision moved on"}
          </span>
        )}
      </div>
      <p className="text-xs text-slate-500">
        {ruleEffectText(rule.kind, row.enforcement)}
        {tightened ? ` (a lower scope tightened it to ${row.enforcement})` : ""} · {ruleReachText(rule)}
      </p>
      {rule.body && <p className="whitespace-pre-wrap text-sm text-slate-700">{rule.body}</p>}
      {(adrLabel || rule.source_adr_id != null || rule.source_url) && (
        <p className="text-xs text-slate-500">
          From{" "}
          {rule.source_adr_id != null && <span>{adrLabel ?? `decision #${rule.source_adr_id}`}</span>}
          {rule.source_adr_id != null && rule.source_url && " · "}
          {rule.source_url && (
            <a href={rule.source_url} target="_blank" rel="noreferrer" className="text-canopy-700 hover:underline">
              {rule.source_url}
            </a>
          )}
        </p>
      )}
      <div className="flex flex-wrap gap-3 pt-0.5 text-xs">
        {row.canEdit && (
          <>
            <button type="button" onClick={onEdit} className="font-medium text-canopy-700 hover:underline">
              Edit
            </button>
            <button type="button" onClick={onDelete} className="font-medium text-red-700 hover:underline">
              Delete
            </button>
          </>
        )}
        {inherited && mayActHere && !rule.locked && !row.inactive && (
          <>
            <button type="button" onClick={onOverride} className="font-medium text-canopy-700 hover:underline">
              Override here
            </button>
            <button type="button" onClick={onSwitchOff} className="font-medium text-slate-600 hover:underline">
              Switch off here
            </button>
          </>
        )}
      </div>
    </li>
  );
}

function RuleDialog({
  initial,
  editing,
  scopes,
  adrs,
  onClose,
  onSaved,
}: {
  initial: RuleDraft;
  editing: DeliveryRule | null;
  scopes: RuleScopeInfo[];
  adrs: ADR[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [d, setD] = useState<RuleDraft>(initial);
  const [keyTouched, setKeyTouched] = useState(Boolean(initial.key));
  const set = (patch: Partial<RuleDraft>) => setD((prev) => ({ ...prev, ...patch }));
  const problem = draftProblem(d);
  const level = d.scope.split(":")[0] as RuleScope;
  const save = useMutation({
    mutationFn: () => {
      const body = ruleBody(d, editing?.selector?.components ?? []);
      if (editing) {
        // Where a rule lives and its key are its identity; an edit changes the rest.
        const patch: Partial<RuleWrite> = { ...body };
        delete patch.scope_level;
        delete patch.scope_id;
        delete patch.key;
        return api.patch(`/rules/${editing.id}`, patch);
      }
      return api.post("/rules", body);
    },
    onSuccess: onSaved,
  });
  const input = "w-full rounded-md border border-slate-300 px-2 py-1 text-sm";
  return (
    <div role="dialog" aria-modal aria-label={editing ? `Edit rule ${editing.key}` : "Add a rule"} className="fixed inset-0 z-50 flex justify-end bg-black/30">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!problem) save.mutate();
        }}
        className="h-full w-full max-w-lg space-y-3 overflow-y-auto bg-white p-5 shadow-xl"
      >
        <div className="flex items-start justify-between">
          <h2 className="text-lg font-semibold">{editing ? "Edit rule" : "Add a rule"}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-slate-600">
            <Icon name="close" size={18} />
          </button>
        </div>
        <label className="block space-y-1 text-sm">
          <span className="font-medium">Where it lives</span>
          <select
            className={input}
            value={d.scope}
            disabled={Boolean(editing)}
            onChange={(e) => set({ scope: e.target.value })}
          >
            {scopes.map((s) => (
              <option key={`${s.scope_level}:${s.scope_id}`} value={`${s.scope_level}:${s.scope_id}`}>
                {s.scope_level === "workspace" ? "The workspace" : `${ORIGIN_LABEL[s.scope_level]} · ${s.name}`}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="space-y-1 text-sm">
          <legend className="font-medium">Kind</legend>
          <label className="mr-4 inline-flex items-center gap-1">
            <input type="radio" checked={d.kind === "guidance"} onChange={() => set({ kind: "guidance" })} /> Guidance —
            read in the brief
          </label>
          <label className="inline-flex items-center gap-1">
            <input type="radio" checked={d.kind === "attestation"} onChange={() => set({ kind: "attestation" })} />{" "}
            Definition of Done — attested at hand-off
          </label>
        </fieldset>
        <label className="block space-y-1 text-sm">
          <span className="font-medium">Title</span>
          <input
            className={input}
            value={d.title}
            maxLength={200}
            onChange={(e) => set(keyTouched || editing ? { title: e.target.value } : { title: e.target.value, key: slugKey(e.target.value) })}
          />
        </label>
        <label className="block space-y-1 text-sm">
          <span className="font-medium">Key</span>
          <input
            className={`${input} font-mono`}
            value={d.key}
            disabled={Boolean(editing)}
            onChange={(e) => {
              setKeyTouched(true);
              set({ key: e.target.value });
            }}
          />
          <span className="text-xs text-slate-500">The same key lower down replaces this rule (unless it is locked).</span>
        </label>
        <label className="block space-y-1 text-sm">
          <span className="font-medium">Body</span>
          <textarea className={input} rows={4} value={d.body} onChange={(e) => set({ body: e.target.value })} />
          <span className={`text-xs ${d.body.length > 800 ? "text-red-700" : "text-slate-500"}`}>{d.body.length}/800</span>
        </label>
        {d.kind === "attestation" && (
          <label className="block space-y-1 text-sm">
            <span className="font-medium">A hand-off that doesn’t attest it</span>
            <select
              className={input}
              value={d.enforcement}
              onChange={(e) => set({ enforcement: e.target.value as RuleDraft["enforcement"] })}
            >
              {ENFORCEMENTS.map((x) => (
                <option key={x} value={x}>
                  {x === "block" ? "is refused (block)" : x === "warn" ? "is flagged (warn)" : "isn’t checked (off)"}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="block space-y-1 text-sm">
          <span className="font-medium">Roles</span>
          <input className={input} value={d.roles} placeholder="all roles" onChange={(e) => set({ roles: e.target.value })} />
          <span className="text-xs text-slate-500">Comma-separated role keys, e.g. implementer, reviewer.</span>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block space-y-1 text-sm">
            <span className="font-medium">Only tasks tagged</span>
            <input className={input} value={d.tags} placeholder="any tag" onChange={(e) => set({ tags: e.target.value })} />
          </label>
          <label className="block space-y-1 text-sm">
            <span className="font-medium">Only paths</span>
            <input className={input} value={d.paths} placeholder="e.g. web/**" onChange={(e) => set({ paths: e.target.value })} />
          </label>
        </div>
        {level !== "project" && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={d.locked} onChange={(e) => set({ locked: e.target.checked })} />
            Locked — lower scopes can’t override or switch it off
          </label>
        )}
        {adrs.length > 0 && (
          <label className="block space-y-1 text-sm">
            <span className="font-medium">From a decision</span>
            <select className={input} value={d.sourceAdrId} onChange={(e) => set({ sourceAdrId: e.target.value })}>
              <option value="">—</option>
              {adrs.map((a) => (
                <option key={a.id} value={a.id}>
                  ADR-{String(a.number).padStart(4, "0")} {a.title}
                </option>
              ))}
            </select>
            <span className="text-xs text-slate-500">The rule is flagged stale when that decision is superseded.</span>
          </label>
        )}
        <label className="block space-y-1 text-sm">
          <span className="font-medium">Source link</span>
          <input className={input} value={d.sourceUrl} placeholder="https://…" onChange={(e) => set({ sourceUrl: e.target.value })} />
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
