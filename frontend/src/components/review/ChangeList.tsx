import { useEffect, useState } from "react";

import { ApiError } from "../../api/client";
import type { Engineer, PreviewIssue, Proposal, ProposalItem } from "../../api/types";
import {
  addableFields,
  buildOverrides,
  coerceInput,
  effectivePayload,
  fieldMeta,
  groupItems,
  inputValue,
  itemAttention,
  itemFacts,
  itemKindLabel,
  itemScopeNote,
  itemTitle,
  optionLabel,
  visibleFacts,
  type Fact,
  type ItemContext,
} from "../../lib/proposals";

const ACTION_TONE: Record<string, string> = {
  create: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  update: "bg-sky-50 text-sky-700 ring-sky-200",
  resolve: "bg-violet-50 text-violet-700 ring-violet-200",
};

export interface ChangeListProps {
  proposal: Pick<Proposal, "scope_level" | "revision" | "status">;
  items: ProposalItem[];
  ctx: ItemContext;
  issues: PreviewIssue[] | undefined;
  engineers: Engineer[];
  /** planner reviewing an open proposal */
  canEdit: boolean;
  /** items to scroll to + ring (arrived from the plan view) */
  focusIds: number[];
  /** the ring has been shown long enough — let go of the focus */
  onFocusSeen: () => void;
  onToggle: (itemIds: number[], excluded: boolean) => void;
  onOverride: (itemId: number, overrides: Record<string, unknown>) => Promise<unknown>;
}

type Filter = "all" | "attention" | "revised";

/**
 * The fine-grained half of a review: every staged change as a card in plain words, grouped
 * by the part of the plan it touches. Each can be excluded, or edited in place — the
 * reviewer's values apply instead of the agent's, which stay on record.
 */
export function ChangeList({
  proposal,
  items,
  ctx,
  issues,
  engineers,
  canEdit,
  focusIds,
  onFocusSeen,
  onToggle,
  onOverride,
}: ChangeListProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const attentionOf = (item: ProposalItem) => itemAttention(item, issues, ctx);
  const isRevised = (item: ProposalItem) =>
    proposal.revision > 1 && item.revision === proposal.revision;

  const attentionCount = items.filter((i) => attentionOf(i) !== null).length;
  const revisedCount = items.filter(isRevised).length;
  const focusKey = focusIds.join(",");

  // Arriving from the plan view: make sure the target isn't filtered away, then show it.
  useEffect(() => {
    if (!focusKey) return;
    setFilter("all");
    const first = Number(focusKey.split(",")[0]);
    const scroll = window.setTimeout(() => {
      document
        .getElementById(`change-${first}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
    // The ring is a pointer, not a state: fade it once the eye has landed.
    const release = window.setTimeout(onFocusSeen, 3500);
    return () => {
      window.clearTimeout(scroll);
      window.clearTimeout(release);
    };
  }, [focusKey, onFocusSeen]);

  const shown = items.filter((item) =>
    filter === "attention" ? attentionOf(item) !== null : filter === "revised" ? isRevised(item) : true
  );
  const groups = groupItems(shown);
  const filters: { key: Filter; label: string; count: number }[] = [
    { key: "all", label: "All changes", count: items.length },
    { key: "attention", label: "Needs attention", count: attentionCount },
    { key: "revised", label: "Just revised", count: revisedCount },
  ];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        {filters
          .filter((f) => f.key === "all" || f.count > 0)
          .map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`rounded-full px-3 py-1 text-sm ${
                filter === f.key
                  ? "bg-slate-800 text-white"
                  : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {f.label} <span className="opacity-70">{f.count}</span>
            </button>
          ))}
        {canEdit && (
          <span className="ml-auto flex items-center gap-3 text-sm">
            <button
              onClick={() => onToggle(items.map((i) => i.id), false)}
              className="text-canopy-700 hover:underline"
            >
              Include all
            </button>
            <button
              onClick={() => onToggle(items.map((i) => i.id), true)}
              className="text-slate-500 hover:underline"
            >
              Exclude all
            </button>
          </span>
        )}
      </div>

      {groups.length === 0 && (
        <p className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-400">
          Nothing matches this filter.
        </p>
      )}

      {groups.map(({ group, items: groupItemsList }) => {
        const included = groupItemsList.filter((i) => !i.excluded).length;
        const ids = groupItemsList.map((i) => i.id);
        return (
          <section key={group.key}>
            <div className="mb-2 flex items-baseline gap-2">
              <h3 className="text-sm font-semibold text-slate-700">{group.label}</h3>
              <span className="text-xs text-slate-400">
                {included === groupItemsList.length
                  ? `${groupItemsList.length} ${groupItemsList.length === 1 ? "change" : "changes"}`
                  : `${included} of ${groupItemsList.length} included`}
              </span>
              {canEdit && groupItemsList.length > 1 && (
                <button
                  onClick={() => onToggle(ids, included > 0)}
                  className="ml-auto text-xs text-slate-500 hover:underline"
                >
                  {included > 0 ? "Exclude these" : "Include these"}
                </button>
              )}
            </div>
            <ul className="space-y-2">
              {groupItemsList.map((item) => (
                <ChangeCard
                  key={item.id}
                  item={item}
                  ctx={ctx}
                  scope={proposal.scope_level}
                  attention={attentionOf(item)}
                  revised={isRevised(item)}
                  focused={focusIds.includes(item.id)}
                  engineers={engineers}
                  canEdit={canEdit}
                  onToggle={(excluded) => onToggle([item.id], excluded)}
                  onOverride={(overrides) => onOverride(item.id, overrides)}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function ChangeCard({
  item,
  ctx,
  scope,
  attention,
  revised,
  focused,
  engineers,
  canEdit,
  onToggle,
  onOverride,
}: {
  item: ProposalItem;
  ctx: ItemContext;
  scope: Proposal["scope_level"];
  attention: ReturnType<typeof itemAttention>;
  revised: boolean;
  focused: boolean;
  engineers: Engineer[];
  canEdit: boolean;
  onToggle: (excluded: boolean) => void;
  onOverride: (overrides: Record<string, unknown>) => Promise<unknown>;
}) {
  const [editing, setEditing] = useState(false);
  const facts = itemFacts(item, ctx);
  const shownFacts = visibleFacts(item, facts);
  const shortFacts = shownFacts.filter((f) => !f.long);
  const longFacts = shownFacts.filter((f) => f.long);
  const scopeNote = itemScopeNote(item, ctx, scope);
  const hasOverrides = Object.keys(item.overrides ?? {}).length > 0;
  const editable =
    canEdit && !item.excluded && (facts.some((f) => f.editable) || addableFields(item).length > 0);

  return (
    <li
      id={`change-${item.id}`}
      className={`rounded-lg border bg-white transition-shadow ${
        focused ? "border-canopy-500 ring-2 ring-canopy-500/30" : "border-slate-200"
      } ${item.excluded ? "opacity-60" : ""}`}
    >
      <div className="flex items-start gap-3 px-4 py-3">
        {canEdit && (
          <input
            type="checkbox"
            checked={!item.excluded}
            onChange={(e) => onToggle(!e.target.checked)}
            className="mt-1 h-4 w-4 accent-canopy-500"
            aria-label={item.excluded ? "Include this change" : "Exclude this change"}
            title={item.excluded ? "Excluded — won't be applied" : "Included — will be applied"}
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span
              className={`rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${
                ACTION_TONE[item.action] ?? "bg-slate-50 text-slate-600 ring-slate-200"
              }`}
            >
              {itemKindLabel(item)}
            </span>
            <span
              className={`min-w-0 break-words font-medium ${
                item.excluded ? "line-through decoration-slate-300" : ""
              }`}
            >
              {itemTitle(item, ctx)}
            </span>
            {scopeNote && <span className="text-xs text-slate-400">{scopeNote}</span>}
            {revised && (
              <span
                className="rounded bg-canopy-50 px-1.5 py-0.5 text-xs font-medium text-canopy-700"
                title="Added or rewritten in the latest revision"
              >
                revised
              </span>
            )}
            {hasOverrides && (
              <span
                className="rounded bg-violet-100 px-1.5 py-0.5 text-xs text-violet-700"
                title="A reviewer changed a proposed value — the original is kept on record."
              >
                edited{item.overridden_by ? ` by ${item.overridden_by}` : ""}
              </span>
            )}
            {item.excluded && <span className="text-xs text-slate-400">excluded</span>}
            {editable && !editing && (
              <button
                onClick={() => setEditing(true)}
                className="ml-auto rounded border border-slate-200 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-50"
              >
                Edit
              </button>
            )}
          </div>

          {attention && (
            <p
              className={`mt-2 rounded px-2 py-1 text-xs ${
                attention.tone === "error"
                  ? "bg-red-50 text-red-700"
                  : "bg-amber-50 text-amber-800"
              }`}
            >
              {attention.tone === "error" ? "Can’t apply: " : ""}
              {attention.message}
            </p>
          )}

          {editing ? (
            <EditForm
              item={item}
              facts={facts}
              engineers={engineers}
              onCancel={() => setEditing(false)}
              onSave={async (overrides) => {
                await onOverride(overrides);
                setEditing(false);
              }}
            />
          ) : (
            <>
              {item.action === "create" ? (
                shortFacts.length > 0 && (
                  <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm">
                    {shortFacts.map((f) => (
                      <div key={f.field} className="flex items-baseline gap-1.5">
                        <dt className="text-xs text-slate-400">{f.label}</dt>
                        <dd>
                          <FactValue fact={f} />
                        </dd>
                      </div>
                    ))}
                  </dl>
                )
              ) : (
                shortFacts.length > 0 && (
                  <table className="mt-1.5 text-sm">
                    <tbody>
                      {shortFacts.map((f) => (
                        <tr key={f.field}>
                          <td className="py-0.5 pr-4 align-top text-xs text-slate-400">
                            {f.label}
                          </td>
                          <td className="py-0.5 align-top">
                            {f.before !== null && !f.unchanged && (
                              <>
                                <span className="text-slate-400 line-through decoration-slate-300">
                                  {f.before}
                                </span>
                                <span className="mx-1.5 text-slate-300">→</span>
                              </>
                            )}
                            <FactValue fact={f} />
                            {f.unchanged && (
                              <span className="ml-2 text-xs text-slate-400">already set</span>
                            )}
                            {f.current !== null && (
                              <span className="ml-2 rounded bg-amber-50 px-1.5 text-xs text-amber-800">
                                now {f.current}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )
              )}
              {longFacts.map((f) => (
                <div key={f.field} className="mt-2 text-sm">
                  <div className="text-xs text-slate-400">{f.label}</div>
                  {f.before !== null && f.before !== f.after && (
                    <p className="whitespace-pre-wrap text-slate-400 line-through decoration-slate-300">
                      {f.before}
                    </p>
                  )}
                  <p className="whitespace-pre-wrap text-slate-700">
                    <FactValue fact={f} />
                  </p>
                </div>
              ))}
            </>
          )}

          {(item.reason || item.source_label || item.source_kind) && (
            <p className="mt-2 text-xs text-slate-500">
              {item.reason && <span className="italic">“{item.reason}”</span>}
              {(item.source_label || item.source_kind) && (
                <span className="text-slate-400">
                  {item.reason ? " — " : ""}
                  {item.source_kind && (
                    <span className="mr-1 rounded bg-slate-100 px-1 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
                      {item.source_kind}
                    </span>
                  )}
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
                </span>
              )}
            </p>
          )}
        </div>
      </div>
    </li>
  );
}

/** A value as it will apply — with the agent's original struck through when a reviewer
 *  changed it, so the audit trail reads "Claude proposed X → you set Y". */
function FactValue({ fact }: { fact: Fact }) {
  if (fact.proposed !== null) {
    return (
      <>
        <span className="text-slate-400 line-through decoration-slate-300">{fact.proposed}</span>{" "}
        <span className="font-semibold text-violet-700">{fact.after}</span>
      </>
    );
  }
  return (
    <span className={fact.added ? "font-semibold text-violet-700" : "font-medium text-slate-800"}>
      {fact.after}
    </span>
  );
}

function errorMessage(err: unknown): string {
  const raw = err instanceof ApiError ? err.message : String(err);
  try {
    const body = JSON.parse(raw) as { detail?: { error?: string } | string };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail?.error) return body.detail.error;
  } catch {
    /* not JSON — show as-is */
  }
  return raw;
}

const INPUT = "w-full rounded border border-slate-300 px-2 py-1 text-sm focus:border-canopy-500 focus:outline-none";

/** Edit every plain value on a change at once, with the right control for each (a date
 *  picker for dates, a people list for assignees…), and add a value the proposal left out. */
function EditForm({
  item,
  facts,
  engineers,
  onCancel,
  onSave,
}: {
  item: ProposalItem;
  facts: Fact[];
  engineers: Engineer[];
  onCancel: () => void;
  onSave: (overrides: Record<string, unknown>) => Promise<void>;
}) {
  const effective = effectivePayload(item);
  // Start from the values the change already carries; when it carries none that can be
  // edited (a bare dependency), open straight onto what could be added instead.
  const [fields, setFields] = useState<string[]>(() => {
    const staged = facts.filter((f) => f.editable).map((f) => f.field);
    return staged.length > 0 ? staged : addableFields(item);
  });
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((field) => [field, inputValue(effective[field])]))
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const canAdd = addableFields(item).filter((f) => !fields.includes(f));
  const hasOverrides = Object.keys(item.overrides ?? {}).length > 0;

  const submit = async (overrides: Record<string, unknown>) => {
    setSaving(true);
    setError(null);
    try {
      await onSave(overrides);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };
  const save = () => {
    const edits: Record<string, unknown> = {};
    for (const field of fields) {
      if (draft[field] === inputValue(effective[field])) continue; // untouched
      edits[field] = coerceInput(fieldMeta(item.entity_type, field), draft[field]);
    }
    void submit(buildOverrides(item, edits));
  };

  return (
    <div className="mt-2 rounded-md border border-slate-200 bg-slate-50 p-3">
      <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
        {fields.map((field) => {
          const meta = fieldMeta(item.entity_type, field);
          const fact = facts.find((f) => f.field === field);
          const value = draft[field] ?? "";
          const set = (next: string) => setDraft((d) => ({ ...d, [field]: next }));
          const id = `edit-${item.id}-${field}`;
          return (
            <div key={field} className={meta.kind === "longtext" ? "sm:col-span-2" : ""}>
              <label htmlFor={id} className="mb-0.5 flex items-baseline gap-2 text-xs text-slate-500">
                {meta.label}
                {fact?.before != null && (
                  <span className="text-slate-400">currently {fact.before}</span>
                )}
              </label>
              {meta.kind === "longtext" ? (
                <textarea
                  id={id}
                  value={value}
                  onChange={(e) => set(e.target.value)}
                  rows={2}
                  className={INPUT}
                />
              ) : meta.kind === "enum" ? (
                <select id={id} value={value} onChange={(e) => set(e.target.value)} className={INPUT}>
                  {(value === "" || !meta.options?.includes(value)) && (
                    <option value={value}>{value === "" ? "—" : value}</option>
                  )}
                  {meta.options?.map((o) => (
                    <option key={o} value={o}>
                      {optionLabel(o)}
                    </option>
                  ))}
                </select>
              ) : meta.kind === "engineer" ? (
                <select id={id} value={value} onChange={(e) => set(e.target.value)} className={INPUT}>
                  <option value="">Nobody</option>
                  {engineers
                    .filter((e) => e.active || String(e.id) === value)
                    .map((e) => (
                      <option key={e.id} value={String(e.id)}>
                        {e.name}
                      </option>
                    ))}
                </select>
              ) : (
                <span className="flex items-center gap-1.5">
                  <input
                    id={id}
                    type={meta.kind === "number" ? "number" : meta.kind === "date" ? "date" : "text"}
                    value={value}
                    onChange={(e) => set(e.target.value)}
                    className={INPUT}
                  />
                  {meta.unit && <span className="text-xs text-slate-400">{meta.unit}</span>}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {error && <p className="mt-2 text-xs text-red-600">Couldn&apos;t save: {error}</p>}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          onClick={save}
          disabled={saving}
          className="rounded bg-canopy-500 px-3 py-1 text-sm font-medium text-white disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button onClick={onCancel} className="px-2 py-1 text-sm text-slate-500 hover:text-slate-700">
          Cancel
        </button>
        {canAdd.length > 0 && (
          <select
            value=""
            onChange={(e) => {
              const field = e.target.value;
              if (!field) return;
              setFields((f) => [...f, field]);
              setDraft((d) => ({ ...d, [field]: "" }));
            }}
            className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-600"
            aria-label="Add a field"
          >
            <option value="">+ Add a field…</option>
            {canAdd.map((f) => (
              <option key={f} value={f}>
                {fieldMeta(item.entity_type, f).label}
              </option>
            ))}
          </select>
        )}
        {hasOverrides && (
          <button
            onClick={() => void submit({})}
            disabled={saving}
            className="ml-auto text-xs text-slate-500 hover:underline"
            title="Discard your edits on this change"
          >
            Reset to the proposed values
          </button>
        )}
      </div>
    </div>
  );
}
