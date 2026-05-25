import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { DocCoverage, DocKind, DocReference, DocScope } from "../api/types";

const DOC_KINDS: DocKind[] = [
  "prd",
  "design",
  "tech_design",
  "architecture",
  "release",
  "qa",
  "runbook",
  "other",
];

const KIND_LABEL: Record<DocKind, string> = {
  prd: "PRD",
  design: "Design",
  tech_design: "Tech design",
  architecture: "Architecture",
  release: "Release",
  qa: "QA",
  runbook: "Runbook",
  other: "Other",
};

/** The document graph for a project / initiative: typed links to docs that live elsewhere
 *  (canopy links, never stores), grouped by kind, with a coverage gap signal. */
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
  const [adding, setAdding] = useState(false);

  const docs = useQuery({
    queryKey: ["docs", scope, scopeId],
    queryFn: () => api.get<DocReference[]>(`/docs?scope_level=${scope}&scope_id=${scopeId}`),
  });
  const coverage = useQuery({
    queryKey: ["docs-coverage", scope, scopeId],
    queryFn: () => api.get<DocCoverage>(`/docs/coverage?scope_level=${scope}&scope_id=${scopeId}`),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["docs", scope, scopeId] });
    qc.invalidateQueries({ queryKey: ["docs-coverage", scope, scopeId] });
  };

  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/docs/${id}`),
    onSuccess: invalidate,
  });

  const items = docs.data ?? [];
  const byKind = new Map<DocKind, DocReference[]>();
  for (const d of items) {
    byKind.set(d.kind, [...(byKind.get(d.kind) ?? []), d]);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">
          Documents
          <span className="ml-2 text-xs font-normal text-slate-400">
            links to docs that live elsewhere — canopy links, never stores
          </span>
        </h2>
        {mayWrite && (
          <button
            onClick={() => setAdding((v) => !v)}
            className="rounded border border-canopy-500 px-3 py-1 text-xs font-medium text-canopy-700"
          >
            {adding ? "Cancel" : "Add link"}
          </button>
        )}
      </div>

      {coverage.data && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-slate-400">coverage:</span>
          {coverage.data.present.map((k) => (
            <span key={k} className="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-700">
              {KIND_LABEL[k]} ✓
            </span>
          ))}
          {coverage.data.missing.map((k) => (
            <span key={k} className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-700">
              {KIND_LABEL[k]} missing
            </span>
          ))}
          {coverage.data.missing.length === 0 && coverage.data.present.length > 0 && (
            <span className="text-emerald-600">all expected kinds present</span>
          )}
        </div>
      )}

      {adding && (
        <AddDocForm
          scope={scope}
          scopeId={scopeId}
          onDone={() => {
            setAdding(false);
            invalidate();
          }}
        />
      )}

      {items.length === 0 ? (
        <p className="text-sm text-slate-500">No document links yet.</p>
      ) : (
        <div className="space-y-3">
          {DOC_KINDS.filter((k) => byKind.has(k)).map((kind) => (
            <div key={kind}>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                {KIND_LABEL[kind]}
              </h3>
              <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white text-sm">
                {(byKind.get(kind) ?? []).map((d) => (
                  <li key={d.id} className="flex items-center gap-2 px-3 py-2">
                    <a
                      href={d.url}
                      target="_blank"
                      rel="noreferrer"
                      className="truncate text-canopy-700 hover:underline"
                      title={d.url}
                    >
                      {d.title || d.url}
                    </a>
                    {d.source === "jira_epic" && (
                      <span className="rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-500">
                        from Jira
                      </span>
                    )}
                    {mayWrite && (
                      <button
                        onClick={() => remove.mutate(d.id)}
                        className="ml-auto text-xs text-slate-400 hover:text-red-600"
                      >
                        remove
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AddDocForm({
  scope,
  scopeId,
  onDone,
}: {
  scope: DocScope;
  scopeId: number;
  onDone: () => void;
}) {
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<DocKind>("prd");

  const create = useMutation({
    mutationFn: () =>
      api.post("/docs", {
        scope_level: scope,
        scope_id: scopeId,
        url,
        title: title || null,
        kind,
      }),
    onSuccess: onDone,
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (url.trim()) create.mutate();
      }}
      className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm"
    >
      <select
        value={kind}
        onChange={(e) => setKind(e.target.value as DocKind)}
        className="rounded border border-slate-300 px-2 py-2"
      >
        {DOC_KINDS.map((k) => (
          <option key={k} value={k}>
            {KIND_LABEL[k]}
          </option>
        ))}
      </select>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title (optional)"
        className="w-40 rounded border border-slate-300 px-3 py-2"
      />
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://…"
        className="flex-1 rounded border border-slate-300 px-3 py-2"
      />
      <button
        type="submit"
        disabled={create.isPending}
        className="rounded bg-canopy-500 px-4 py-2 text-xs font-medium text-white disabled:opacity-50"
      >
        {create.isPending ? "Saving…" : "Link"}
      </button>
    </form>
  );
}
