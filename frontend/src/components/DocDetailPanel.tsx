import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { DesignDocDetail, DocRegisterResult, DocRevisionResult } from "../api/types";
import {
  ENTITY_LABEL,
  RELATION_HINT,
  RELATION_LABEL,
  STATUS_TONE,
  VISIBILITY_LABEL,
  behindPin,
  classifyUrl,
  docErrorMessage,
  docTitle,
  formatLabel,
  healthTone,
  humanize,
  providerLabel,
  revisionSourceLabel,
  shortHash,
  statusLabel,
  versionLabel,
} from "../lib/docs";
import { isPlanner } from "../lib/permissions";
import { useCurrentUser } from "../lib/useCurrentUser";

/** One design doc, in a drawer: what it is, where it is linked (pinned version vs now), its
 *  health, its version log, and the review actions. Canopy links — "Open" goes to the doc in its
 *  own app, with the viewer's own access. */
export default function DocDetailPanel({
  docId,
  mayWrite,
  onClose,
}: {
  docId: number;
  mayWrite: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { data: me } = useCurrentUser();
  const mayApprove = isPlanner(me?.role);
  const [version, setVersion] = useState("");
  const [note, setNote] = useState("");
  const [replaceUrl, setReplaceUrl] = useState("");

  const detail = useQuery({
    queryKey: ["doc", docId],
    queryFn: () => api.get<DesignDocDetail>(`/docs/${docId}`),
  });
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["doc", docId] });
    void qc.invalidateQueries({ queryKey: ["docs"] });
    void qc.invalidateQueries({ queryKey: ["docs-coverage"] });
    void qc.invalidateQueries({ queryKey: ["alerts"] });
    void qc.invalidateQueries({ queryKey: ["my-workspace"] });
  };
  const check = useMutation({
    mutationFn: (reachable: boolean) =>
      api.post<DocRevisionResult>(`/docs/${docId}/revisions`, {
        version: version.trim() || null,
        change_summary: note.trim() || null,
        reachable,
      }),
    onSuccess: () => {
      setVersion("");
      setNote("");
      invalidate();
    },
  });
  const review = useMutation({
    mutationFn: () => api.post(`/docs/${docId}/request-review`, {}),
    onSuccess: invalidate,
  });
  const approve = useMutation({
    mutationFn: () => api.post(`/docs/${docId}/approve`, {}),
    onSuccess: invalidate,
  });
  const archive = useMutation({
    mutationFn: () => api.post(`/docs/${docId}/archive`),
    onSuccess: invalidate,
  });
  const replace = useMutation({
    mutationFn: (doc: DesignDocDetail) =>
      api.post<DocRegisterResult>("/docs/register", {
        url: replaceUrl.trim(),
        title: doc.title,
        kind: doc.kind,
        visibility: doc.visibility,
        scope_level: doc.scope_level,
        scope_id: doc.scope_id,
        supersedes_id: doc.id,
      }),
    onSuccess: () => {
      setReplaceUrl("");
      invalidate();
    },
  });

  const doc = detail.data;
  const err = check.error ?? review.error ?? approve.error ?? archive.error ?? replace.error;
  const retired = doc?.review_status === "superseded" || doc?.review_status === "archived";
  return (
    <>
      <div className="fixed inset-0 z-30 bg-slate-900/20" onClick={onClose} aria-hidden />
      <aside
        className="fixed inset-y-0 right-0 z-40 w-full max-w-lg overflow-y-auto bg-white p-5 shadow-xl"
        aria-label="Design doc"
      >
        <div className="mb-3 flex items-start justify-between gap-2">
          <h2 className="font-semibold text-slate-800">{doc ? docTitle(doc) : "Loading…"}</h2>
          <button onClick={onClose} className="text-sm text-slate-400 hover:text-slate-600">
            close
          </button>
        </div>
        {doc && (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center gap-1.5">
              <a
                href={doc.url}
                target="_blank"
                rel="noreferrer"
                className="rounded bg-canopy-500 px-2 py-1 text-xs font-medium text-white"
              >
                Open in {providerLabel(doc.provider)} ↗
              </a>
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                {doc.kind_label} · {formatLabel(doc.format)}
              </span>
              <span className={`rounded px-1.5 py-0.5 text-xs ${STATUS_TONE[doc.review_status ?? "link"]}`}>
                {statusLabel(doc.review_status)}
              </span>
              {versionLabel(doc) && (
                <span className="rounded bg-slate-50 px-1.5 py-0.5 text-xs text-slate-500">
                  {versionLabel(doc)}
                </span>
              )}
              {doc.provider === "claude" && (
                <span className="rounded bg-slate-50 px-1.5 py-0.5 text-xs text-slate-500">
                  shared with: {VISIBILITY_LABEL[(doc.visibility ?? "unknown") as keyof typeof VISIBILITY_LABEL] ?? doc.visibility}
                </span>
              )}
            </div>
            {doc.summary && <p className="whitespace-pre-line text-slate-600">{doc.summary}</p>}

            {(doc.health ?? []).length > 0 && (
              <ul className="space-y-1">
                {(doc.health ?? []).map((f, i) => (
                  <li key={`${f.flag}-${i}`} className={`rounded px-2 py-1 text-xs ${healthTone(f)}`}>
                    {f.message}
                  </li>
                ))}
              </ul>
            )}

            <section>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Linked to</h3>
              {doc.links.length === 0 ? (
                <p className="text-xs text-slate-400">Not linked to any work yet.</p>
              ) : (
                <ul className="space-y-1">
                  {doc.links.map((l) => (
                    <li key={l.id} className="flex flex-wrap items-center gap-1.5 text-xs">
                      <span className="text-slate-500">{ENTITY_LABEL[l.entity_type] ?? humanize(l.entity_type)}</span>
                      <span className="text-slate-700">{l.label ?? `#${l.entity_id}`}</span>
                      <span className="rounded bg-violet-50 px-1 py-0.5 text-violet-700" title={RELATION_HINT[l.relation]}>
                        {RELATION_LABEL[l.relation]}
                        {l.pinned_version ? ` @ ${l.pinned_version}` : ""}
                      </span>
                      {l.relation === "basis" && behindPin(l.pinned_version, doc.current_version) && (
                        <span className="rounded bg-amber-100 px-1 py-0.5 text-amber-800">
                          doc now {doc.current_version}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Versions</h3>
              {doc.revisions.length === 0 ? (
                <p className="text-xs text-slate-400">No version recorded yet.</p>
              ) : (
                <ol className="space-y-1 border-l border-slate-200 pl-3">
                  {doc.revisions.map((r) => (
                    <li key={r.id} className="text-xs">
                      <span className="font-medium text-slate-700">{r.version}</span>
                      {r.version === doc.approved_version && (
                        <span className="ml-1 rounded bg-emerald-100 px-1 text-emerald-700">approved</span>
                      )}
                      <span className="ml-2 text-slate-400">{r.created_at.slice(0, 10)}</span>
                      {revisionSourceLabel(r.source) && (
                        <span className="ml-2 text-slate-400">· {revisionSourceLabel(r.source)}</span>
                      )}
                      {r.content_hash && (
                        <span className="ml-2 font-mono text-slate-400" title={r.content_hash}>
                          {shortHash(r.content_hash)}
                        </span>
                      )}
                      {r.change_summary && <div className="text-slate-500">{r.change_summary}</div>}
                      {r.snapshot_url && (
                        <a href={r.snapshot_url} target="_blank" rel="noreferrer" className="text-canopy-700 underline">
                          frozen copy ↗
                        </a>
                      )}
                    </li>
                  ))}
                </ol>
              )}
              <p className="mt-1 text-[11px] text-slate-400">
                Last checked {doc.last_checked_at ? doc.last_checked_at.slice(0, 10) : "never"}.
                {doc.source_updated_at && <> Edited in Claude {doc.source_updated_at.slice(0, 10)} (org sync).</>}
              </p>
            </section>

            {!retired && mayWrite && (
              <section className="space-y-2 rounded border border-slate-200 bg-slate-50 p-2">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <input
                    value={version}
                    onChange={(e) => setVersion(e.target.value)}
                    placeholder="Version you see (e.g. r15)"
                    className="w-40 rounded border border-slate-300 px-2 py-1"
                  />
                  <input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="What changed (optional)"
                    className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1"
                  />
                  <button
                    onClick={() => check.mutate(true)}
                    disabled={check.isPending}
                    className="rounded border border-canopy-500 px-2 py-1 font-medium text-canopy-700"
                  >
                    Record check
                  </button>
                  <button
                    onClick={() => check.mutate(false)}
                    disabled={check.isPending}
                    className="text-slate-400 hover:text-red-600"
                    title="The link no longer opens"
                  >
                    can't open it
                  </button>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  {!doc.personal && doc.review_status !== "in_review" && (
                    <button
                      onClick={() => review.mutate()}
                      className="rounded bg-sky-600 px-2 py-1 font-medium text-white"
                    >
                      Request review{doc.current_version ? ` of ${doc.current_version}` : ""}
                    </button>
                  )}
                  {!doc.personal && mayApprove && doc.review_status === "in_review" && (
                    <button
                      onClick={() => approve.mutate()}
                      className="rounded bg-emerald-600 px-2 py-1 font-medium text-white"
                      title="Approval is recorded with your name and the version"
                    >
                      Approve {doc.review_version ?? doc.current_version ?? ""}
                    </button>
                  )}
                  {!doc.personal && (
                    <button onClick={() => archive.mutate()} className="text-slate-400 hover:text-slate-600">
                      archive
                    </button>
                  )}
                </div>
                {!doc.personal && (
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <input
                      value={replaceUrl}
                      onChange={(e) => setReplaceUrl(e.target.value)}
                      placeholder="Replaced by… (link to the new doc)"
                      className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1"
                    />
                    <button
                      onClick={() => replace.mutate(doc)}
                      disabled={!classifyUrl(replaceUrl)?.https || replace.isPending}
                      className="rounded border border-slate-300 px-2 py-1 text-slate-600 disabled:opacity-50"
                    >
                      Supersede
                    </button>
                  </div>
                )}
              </section>
            )}
            {err && <p className="text-xs text-red-600">{docErrorMessage(err)}</p>}
          </div>
        )}
      </aside>
    </>
  );
}
