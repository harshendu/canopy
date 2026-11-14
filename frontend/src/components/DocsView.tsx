import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  DesignDoc,
  DocCoverage,
  DocKindDef,
  DocProvider,
  DocRegisterResult,
  DocReviewStatus,
  DocScope,
  DocStage,
  DocVisibility,
} from "../api/types";
import {
  FORMATS,
  FORMAT_LABEL,
  PROVIDER_LABEL,
  STAGES,
  STATUS_LABEL,
  STATUS_TONE,
  VISIBILITY_LABEL,
  changedSinceApproval,
  classifyUrl,
  docErrorMessage,
  docTitle,
  formatLabel,
  groupByKind,
  kindLabel,
  linkChips,
  needsSharing,
  providerLabel,
  slugify,
  sortDocs,
  stageLabel,
  statusLabel,
  versionLabel,
} from "../lib/docs";
import { useCurrentUser } from "../lib/useCurrentUser";

const STATUS_FILTERS: (DocReviewStatus | "untracked")[] = [
  "approved",
  "in_review",
  "draft",
  "untracked",
  "superseded",
  "archived",
];
const SHARE_OPTIONS: DocVisibility[] = ["org", "users", "public"];
const COVERAGE_TONE: Record<string, string> = {
  approved: "bg-emerald-100 text-emerald-700",
  in_review: "bg-sky-100 text-sky-700",
  draft: "bg-slate-100 text-slate-600",
  linked: "bg-slate-100 text-slate-600",
  missing: "bg-amber-100 text-amber-700",
};

/** The document graph for a project / initiative: design docs and plain links that live
 *  elsewhere (canopy links, never stores), grouped by kind, with review status, versions,
 *  where each is linked, and a coverage signal. */
export default function DocsView({
  scope,
  scopeId,
  mayWrite,
}: {
  scope: DocScope;
  scopeId: number;
  mayWrite: boolean;
}) {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const [adding, setAdding] = useState(false);
  const [showKinds, setShowKinds] = useState(false);
  const [status, setStatus] = useState<DocReviewStatus | "untracked" | "">("");
  const [provider, setProvider] = useState<DocProvider | "">("");
  const [stage, setStage] = useState<DocStage | "">("");
  const [open, setOpen] = useState<number | null>(null);

  const query = new URLSearchParams({ scope_level: scope, scope_id: String(scopeId) });
  if (status) query.set("review_status", status);
  if (provider) query.set("provider", provider);
  if (stage) query.set("stage", stage);
  const docs = useQuery({
    queryKey: ["docs", scope, scopeId, status, provider, stage],
    queryFn: () => api.get<DesignDoc[]>(`/docs?${query.toString()}`),
  });
  const coverage = useQuery({
    queryKey: ["docs-coverage", scope, scopeId],
    queryFn: () => api.get<DocCoverage>(`/docs/coverage?scope_level=${scope}&scope_id=${scopeId}`),
  });
  const kinds = useQuery({
    queryKey: ["doc-kinds"],
    queryFn: () => api.get<DocKindDef[]>("/docs/kinds"),
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["docs"] });
    void qc.invalidateQueries({ queryKey: ["docs-coverage", scope, scopeId] });
    void qc.invalidateQueries({ queryKey: ["doc-kinds"] });
  };

  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/docs/${id}`),
    onSuccess: invalidate,
  });

  const catalog = useMemo(() => kinds.data ?? [], [kinds.data]);
  const items = docs.data ?? [];
  const groups = groupByKind(sortDocs(items), catalog);
  const filtered = status !== "" || provider !== "" || stage !== "";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">
          Documents
          <span className="ml-2 text-xs font-normal text-slate-400">
            design docs and links that live elsewhere — canopy links, never stores
          </span>
        </h2>
        <div className="flex gap-2">
          {mayWrite && (
            <button
              onClick={() => setShowKinds((v) => !v)}
              className="rounded border border-slate-300 px-3 py-1 text-xs text-slate-600"
            >
              {showKinds ? "Hide kinds" : "Kinds"}
            </button>
          )}
          {mayWrite && (
            <button
              onClick={() => setAdding((v) => !v)}
              className="rounded border border-canopy-500 px-3 py-1 text-xs font-medium text-canopy-700"
            >
              {adding ? "Cancel" : "Add doc"}
            </button>
          )}
        </div>
      </div>

      {coverage.data && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-slate-400">coverage:</span>
          {coverage.data.expected && coverage.data.expected.length > 0
            ? coverage.data.expected.map((e) => (
                <span key={e.kind} className={`rounded px-1.5 py-0.5 ${COVERAGE_TONE[e.state]}`}>
                  {e.label} {e.state === "missing" ? "missing" : e.state === "linked" ? "✓" : `· ${e.state.replace("_", " ")}`}
                </span>
              ))
            : coverage.data.missing.map((k) => (
                <span key={k} className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-700">
                  {kindLabel(k, catalog)} missing
                </span>
              ))}
          {coverage.data.missing.length === 0 && coverage.data.present.length > 0 && (
            <span className="text-emerald-600">all expected kinds present</span>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as DocReviewStatus | "untracked" | "")}
          className="rounded border border-slate-300 px-2 py-1"
          aria-label="Filter by review status"
        >
          <option value="">Any status</option>
          {STATUS_FILTERS.map((s) => (
            <option key={s} value={s}>
              {s === "untracked" ? "Plain links" : STATUS_LABEL[s]}
            </option>
          ))}
        </select>
        <select
          value={provider}
          onChange={(e) => setProvider(e.target.value as DocProvider | "")}
          className="rounded border border-slate-300 px-2 py-1"
          aria-label="Filter by where the doc lives"
        >
          <option value="">Anywhere</option>
          {(Object.keys(PROVIDER_LABEL) as DocProvider[]).map((p) => (
            <option key={p} value={p}>
              {PROVIDER_LABEL[p]}
            </option>
          ))}
        </select>
        <select
          value={stage}
          onChange={(e) => setStage(e.target.value as DocStage | "")}
          className="rounded border border-slate-300 px-2 py-1"
          aria-label="Filter by lifecycle stage"
        >
          <option value="">Any stage</option>
          {STAGES.map((s) => (
            <option key={s} value={s}>
              {stageLabel(s)}
            </option>
          ))}
        </select>
      </div>

      {showKinds && mayWrite && (
        <KindCatalog catalog={catalog} isAdmin={me?.role === "admin"} onChange={invalidate} />
      )}

      {adding && (
        <AddDocForm
          scope={scope}
          scopeId={scopeId}
          catalog={catalog}
          onDone={() => {
            setAdding(false);
            invalidate();
          }}
        />
      )}

      {items.length === 0 ? (
        <p className="text-sm text-slate-500">
          {filtered ? "No docs match these filters." : "No documents yet."}
        </p>
      ) : (
        <div className="space-y-3">
          {groups.map(({ kind, docs: group }) => (
            <div key={kind}>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                {kindLabel(kind, catalog)}
              </h3>
              <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white text-sm">
                {group.map((d) => (
                  <DocRow
                    key={d.id}
                    doc={d}
                    open={open === d.id}
                    onToggle={() => setOpen(open === d.id ? null : d.id)}
                    onRemove={mayWrite ? () => remove.mutate(d.id) : undefined}
                  />
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      {remove.isError && <p className="text-xs text-red-600">{docErrorMessage(remove.error)}</p>}
    </div>
  );
}

function DocRow({
  doc,
  open,
  onToggle,
  onRemove,
}: {
  doc: DesignDoc;
  open: boolean;
  onToggle: () => void;
  onRemove?: () => void;
}) {
  const chips = linkChips(doc);
  return (
    <li className="px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <a
          href={doc.url}
          target="_blank"
          rel="noreferrer"
          className="max-w-[22rem] truncate text-canopy-700 hover:underline"
          title={doc.url}
        >
          {docTitle(doc)}
        </a>
        <span className="rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-500">
          {providerLabel(doc.provider)} · {formatLabel(doc.format)}
        </span>
        <span className={`rounded px-1 py-0.5 text-[10px] ${STATUS_TONE[doc.review_status ?? "link"]}`}>
          {statusLabel(doc.review_status)}
        </span>
        {versionLabel(doc) && (
          <span
            className={`rounded px-1 py-0.5 text-[10px] ${
              changedSinceApproval(doc) ? "bg-amber-100 text-amber-800" : "bg-slate-50 text-slate-500"
            }`}
          >
            {versionLabel(doc)}
          </span>
        )}
        {doc.source === "jira_epic" && (
          <span className="rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-500">from Jira</span>
        )}
        {doc.source === "agent" && (
          <span className="rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-500">via Claude</span>
        )}
        {doc.provider === "claude" && doc.visibility === "users" && (
          <span className="rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-500" title="Shared with named people in Claude">
            limited audience
          </span>
        )}
        {needsSharing(doc.provider, doc.visibility) && !doc.personal && (
          <span className="rounded bg-amber-100 px-1 py-0.5 text-[10px] text-amber-800" title="Not shared in Claude">
            not shared
          </span>
        )}
        {(chips.length > 0 || doc.summary) && (
          <button onClick={onToggle} className="text-xs text-slate-400 hover:text-slate-600">
            {open ? "less" : `${chips.length > 0 ? `${chips.length} link${chips.length > 1 ? "s" : ""}` : "more"}`}
          </button>
        )}
        {onRemove && (
          <button onClick={onRemove} className="ml-auto text-xs text-slate-400 hover:text-red-600">
            remove
          </button>
        )}
      </div>
      {open && (
        <div className="mt-1 space-y-1 text-xs text-slate-500">
          {doc.summary && <p className="whitespace-pre-line">{doc.summary}</p>}
          {chips.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {chips.map((c) => (
                <span key={c.key} className="rounded bg-violet-50 px-1.5 py-0.5 text-violet-700">
                  {c.text}
                  {c.relation !== "reference" ? ` (${c.relation})` : ""}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function AddDocForm({
  scope,
  scopeId,
  catalog,
  onDone,
}: {
  scope: DocScope;
  scopeId: number;
  catalog: DocKindDef[];
  onDone: () => void;
}) {
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("prd");
  const [format, setFormat] = useState("");
  const [visibility, setVisibility] = useState<DocVisibility>("org");
  const [track, setTrack] = useState(true);
  const hint = url.trim() ? classifyUrl(url) : null;
  const effectiveFormat = format || hint?.formatHint || "";
  const blockedBySharing = hint ? needsSharing(hint.provider, visibility) : false;

  const create = useMutation({
    mutationFn: () =>
      api.post<DocRegisterResult>("/docs/register", {
        url: url.trim(),
        title: title || null,
        kind: slugify(kind),
        format: effectiveFormat || null,
        visibility: hint?.provider === "claude" ? visibility : "unknown",
        scope_level: scope,
        scope_id: scopeId,
        track,
      }),
    onSuccess: onDone,
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (url.trim() && hint?.https && !blockedBySharing) create.mutate();
      }}
      className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm"
    >
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://… a Claude doc or artifact, Drive, Figma, a repo file"
          className="min-w-0 flex-1 rounded border border-slate-300 px-3 py-2"
          aria-label="Document link"
        />
        {hint && (
          <span className="text-xs text-slate-500">
            {providerLabel(hint.provider)}
            {hint.artifactId ? ` · ${hint.artifactId.slice(0, 8)}…` : ""}
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          list="doc-kind-options"
          placeholder="Kind (any)"
          className="w-40 rounded border border-slate-300 px-2 py-2"
          aria-label="Kind"
        />
        <datalist id="doc-kind-options">
          {catalog.map((k) => (
            <option key={k.key} value={k.key}>
              {k.label}
            </option>
          ))}
        </datalist>
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value)}
          className="rounded border border-slate-300 px-2 py-2"
          aria-label="Format"
        >
          <option value="">{hint?.formatHint ? `${FORMAT_LABEL[hint.formatHint]} (detected)` : "Format…"}</option>
          {FORMATS.map((f) => (
            <option key={f} value={f}>
              {FORMAT_LABEL[f]}
            </option>
          ))}
        </select>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title (optional)"
          className="w-48 rounded border border-slate-300 px-3 py-2"
        />
        {hint?.provider === "claude" && (
          <label className="flex items-center gap-1 text-xs text-slate-600">
            Who can open it?
            <select
              value={visibility}
              onChange={(e) => setVisibility(e.target.value as DocVisibility)}
              className="rounded border border-slate-300 px-2 py-1"
            >
              {[...SHARE_OPTIONS, "owner" as DocVisibility].map((v) => (
                <option key={v} value={v}>
                  {VISIBILITY_LABEL[v]}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="flex items-center gap-1 text-xs text-slate-600" title="Run the review lifecycle (draft → approved)">
          <input type="checkbox" checked={track} onChange={(e) => setTrack(e.target.checked)} />
          track review
        </label>
        <button
          type="submit"
          disabled={create.isPending || !hint?.https || blockedBySharing}
          className="rounded bg-canopy-500 px-4 py-2 text-xs font-medium text-white disabled:opacity-50"
        >
          {create.isPending ? "Saving…" : "Add"}
        </button>
      </div>
      {hint && !hint.https && <p className="text-xs text-amber-700">Use an https link.</p>}
      {blockedBySharing && (
        <p className="text-xs text-amber-700">
          This Claude doc is private. Share it in Claude first, or track it for yourself under My docs.
        </p>
      )}
      {create.isError && <p className="text-xs text-red-600">{docErrorMessage(create.error)}</p>}
    </form>
  );
}

function KindCatalog({
  catalog,
  isAdmin,
  onChange,
}: {
  catalog: DocKindDef[];
  isAdmin: boolean;
  onChange: () => void;
}) {
  const update = useMutation({
    mutationFn: (vars: { key: string; body: Partial<Pick<DocKindDef, "label" | "stage" | "expected">> }) =>
      api.put(`/docs/kinds/${vars.key}`, vars.body),
    onSuccess: onChange,
  });
  const merge = useMutation({
    mutationFn: (vars: { key: string; into: string }) =>
      api.post(`/docs/kinds/${vars.key}/merge`, { into: vars.into }),
    onSuccess: onChange,
  });
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 text-xs">
      <p className="mb-2 text-slate-500">
        Any kind is allowed. Each kind belongs to a lifecycle stage; expected kinds count toward
        coverage.
      </p>
      <table className="w-full">
        <thead>
          <tr className="text-left text-slate-400">
            <th className="py-1">Kind</th>
            <th>Label</th>
            <th>Stage</th>
            <th>Expected</th>
            <th>Docs</th>
            {isAdmin && <th>Merge into</th>}
          </tr>
        </thead>
        <tbody>
          {catalog.map((k) => (
            <tr key={k.key} className="border-t border-slate-100">
              <td className="py-1 font-mono text-slate-500">{k.key}</td>
              <td>
                <input
                  defaultValue={k.label}
                  onBlur={(e) =>
                    e.target.value !== k.label && update.mutate({ key: k.key, body: { label: e.target.value } })
                  }
                  className="w-32 rounded border border-slate-200 px-1 py-0.5"
                />
              </td>
              <td>
                <select
                  value={k.stage}
                  onChange={(e) => update.mutate({ key: k.key, body: { stage: e.target.value } })}
                  className="rounded border border-slate-200 px-1 py-0.5"
                >
                  {STAGES.map((s) => (
                    <option key={s} value={s}>
                      {stageLabel(s)}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={k.expected}
                  onChange={(e) => update.mutate({ key: k.key, body: { expected: e.target.checked } })}
                />
              </td>
              <td className="text-slate-500">{k.doc_count}</td>
              {isAdmin && (
                <td>
                  {!k.builtin && (
                    <select
                      value=""
                      onChange={(e) => e.target.value && merge.mutate({ key: k.key, into: e.target.value })}
                      className="rounded border border-slate-200 px-1 py-0.5"
                    >
                      <option value="">—</option>
                      {catalog
                        .filter((o) => o.key !== k.key)
                        .map((o) => (
                          <option key={o.key} value={o.key}>
                            {o.label}
                          </option>
                        ))}
                    </select>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {(update.isError || merge.isError) && (
        <p className="mt-1 text-red-600">{docErrorMessage(update.error ?? merge.error)}</p>
      )}
    </div>
  );
}
