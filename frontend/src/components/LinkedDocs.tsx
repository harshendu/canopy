import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  DesignDoc,
  DocLink,
  DocLinkEntity,
  DocRegisterResult,
  DocRelation,
  DocVisibility,
  EntityDoc,
} from "../api/types";
import {
  RELATION_HINT,
  RELATION_LABEL,
  VISIBILITY_LABEL,
  behindPin,
  classifyUrl,
  docErrorMessage,
  docTitle,
  formatLabel,
  needsSharing,
  providerLabel,
  statusLabel,
  STATUS_TONE,
} from "../lib/docs";

const SCOPE_TYPES: DocLinkEntity[] = ["project", "initiative", "task"];
const RELATIONS: DocRelation[] = ["basis", "gate", "reference"];
const SHARE_OPTIONS: DocVisibility[] = ["org", "users", "public", "owner"];

interface Row {
  doc: DesignDoc;
  link: DocLink | null; // null = the doc is homed here
}

/** The design docs attached to one entity (an ADR, a spec, a task, a milestone…): relation,
 *  pinned version vs now, and — for those who may — link an existing doc or paste a new one.
 *  Canopy links; the doc opens in its own app with the viewer's own access. */
export default function LinkedDocs({
  entityType,
  entityId,
  projectId,
  mayLink,
  legacyUrl,
  title = "Design docs",
  defaultRelation = "reference",
}: {
  entityType: DocLinkEntity;
  entityId: number;
  /** The project whose docs the picker offers (and where a pasted doc is filed). */
  projectId?: number;
  mayLink: boolean;
  /** A pre-design-doc link field (an ADR's RFC URL, a spec's source URL), shown until a doc
   *  covers it. */
  legacyUrl?: string | null;
  title?: string;
  defaultRelation?: DocRelation;
}) {
  const qc = useQueryClient();
  const scoped = SCOPE_TYPES.includes(entityType);
  const key = ["entity-docs", entityType, entityId];
  const rows = useQuery({
    queryKey: key,
    queryFn: async (): Promise<Row[]> => {
      if (scoped) {
        const docs = await api.get<DesignDoc[]>(
          `/docs?scope_level=${entityType}&scope_id=${entityId}`,
        );
        return docs.map((doc) => ({
          doc,
          link: doc.links.find((l) => l.entity_type === entityType && l.entity_id === entityId) ?? null,
        }));
      }
      const linked = await api.get<EntityDoc[]>(
        `/docs/links?entity_type=${entityType}&entity_id=${entityId}`,
      );
      return linked.map((e) => ({ doc: e.doc, link: e.link }));
    },
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: key });
    void qc.invalidateQueries({ queryKey: ["docs"] });
  };

  const unlink = useMutation({
    mutationFn: (linkId: number) => api.del(`/docs/links/${linkId}`),
    onSuccess: invalidate,
  });

  const items = rows.data ?? [];
  const legacy =
    legacyUrl && !items.some((r) => r.doc.url.split("#")[0] === legacyUrl.split("#")[0])
      ? legacyUrl
      : null;

  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</div>
      {rows.isLoading && <p className="text-xs text-slate-400">Loading…</p>}
      {!rows.isLoading && items.length === 0 && !legacy && (
        <p className="text-xs text-slate-400">No docs linked yet.</p>
      )}
      <ul className="space-y-1">
        {items.map(({ doc, link }) => (
          <li key={`${doc.id}:${link?.id ?? "home"}`} className="flex flex-wrap items-center gap-1.5 text-sm">
            <a
              href={doc.url}
              target="_blank"
              rel="noreferrer"
              className="max-w-[18rem] truncate text-canopy-700 hover:underline"
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
            {link ? (
              <span
                className="rounded bg-violet-50 px-1 py-0.5 text-[10px] text-violet-700"
                title={RELATION_HINT[link.relation]}
              >
                {RELATION_LABEL[link.relation]}
                {link.pinned_version ? ` @ ${link.pinned_version}` : ""}
              </span>
            ) : (
              <span className="rounded bg-slate-50 px-1 py-0.5 text-[10px] text-slate-400">filed here</span>
            )}
            {link && link.relation === "basis" && behindPin(link.pinned_version, doc.current_version) && (
              <span className="rounded bg-amber-100 px-1 py-0.5 text-[10px] text-amber-800">
                doc now {doc.current_version} — re-check
              </span>
            )}
            {doc.personal && (
              <span className="rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-500">only you</span>
            )}
            {mayLink && link && (
              <button
                onClick={() => unlink.mutate(link.id)}
                className="ml-auto text-xs text-slate-400 hover:text-red-600"
              >
                unlink
              </button>
            )}
          </li>
        ))}
        {legacy && (
          <li className="flex items-center gap-1.5 text-sm">
            <a href={legacy} target="_blank" rel="noreferrer" className="truncate text-canopy-700 hover:underline">
              {legacy}
            </a>
            <span className="rounded bg-slate-50 px-1 py-0.5 text-[10px] text-slate-400">link field</span>
          </li>
        )}
      </ul>
      {unlink.isError && <p className="text-xs text-red-600">{docErrorMessage(unlink.error)}</p>}
      {mayLink && (
        <LinkPicker
          entityType={entityType}
          entityId={entityId}
          projectId={projectId}
          linkedIds={items.map((r) => r.doc.id)}
          defaultRelation={defaultRelation}
          onDone={invalidate}
        />
      )}
    </div>
  );
}

function LinkPicker({
  entityType,
  entityId,
  projectId,
  linkedIds,
  defaultRelation,
  onDone,
}: {
  entityType: DocLinkEntity;
  entityId: number;
  projectId?: number;
  linkedIds: number[];
  defaultRelation: DocRelation;
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [docId, setDocId] = useState<number | "">("");
  const [relation, setRelation] = useState<DocRelation>(defaultRelation);
  const [url, setUrl] = useState("");
  const [visibility, setVisibility] = useState<DocVisibility>("org");

  const candidates = useQuery({
    queryKey: ["docs", "project", projectId],
    queryFn: () => api.get<DesignDoc[]>(`/docs?scope_level=project&scope_id=${projectId}`),
    enabled: open && projectId != null,
  });

  const link = useMutation({
    mutationFn: () =>
      api.post(`/docs/${docId}/links`, { entity_type: entityType, entity_id: entityId, relation }),
    onSuccess: () => {
      setDocId("");
      onDone();
    },
  });
  const paste = useMutation({
    mutationFn: () =>
      api.post<DocRegisterResult>("/docs/register", {
        url,
        visibility,
        scope_level: "project",
        scope_id: projectId,
        links: [{ entity_type: entityType, entity_id: entityId, relation }],
      }),
    onSuccess: () => {
      setUrl("");
      onDone();
    },
  });

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="text-xs font-medium text-canopy-700 hover:underline">
        + Link a doc
      </button>
    );
  }
  const hint = classifyUrl(url);
  const options = (candidates.data ?? []).filter((d) => !linkedIds.includes(d.id));
  const err = link.error ?? paste.error;
  return (
    <div className="space-y-2 rounded border border-slate-200 bg-slate-50 p-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={relation}
          onChange={(e) => setRelation(e.target.value as DocRelation)}
          className="rounded border border-slate-300 px-1 py-1"
          title={RELATION_HINT[relation]}
        >
          {RELATIONS.map((r) => (
            <option key={r} value={r}>
              {RELATION_LABEL[r]}
            </option>
          ))}
        </select>
        {projectId != null && (
          <>
            <select
              value={docId}
              onChange={(e) => setDocId(e.target.value ? Number(e.target.value) : "")}
              className="min-w-0 flex-1 rounded border border-slate-300 px-1 py-1"
            >
              <option value="">Pick a project doc…</option>
              {options.map((d) => (
                <option key={d.id} value={d.id}>
                  {docTitle(d)} ({d.kind_label})
                </option>
              ))}
            </select>
            <button
              disabled={docId === "" || link.isPending}
              onClick={() => link.mutate()}
              className="rounded bg-canopy-500 px-2 py-1 font-medium text-white disabled:opacity-50"
            >
              Link
            </button>
          </>
        )}
        <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-600">
          cancel
        </button>
      </div>
      {projectId != null && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="…or paste a link (a Claude doc or artifact, Drive, Figma, repo)"
            className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1"
          />
          {hint && <span className="text-slate-400">{providerLabel(hint.provider)}</span>}
          {hint?.provider === "claude" && (
            <select
              value={visibility}
              onChange={(e) => setVisibility(e.target.value as DocVisibility)}
              className="rounded border border-slate-300 px-1 py-1"
              title="Who can open it in Claude? A doc must be shared before it backs shared work."
            >
              {SHARE_OPTIONS.map((v) => (
                <option key={v} value={v}>
                  {VISIBILITY_LABEL[v]}
                </option>
              ))}
            </select>
          )}
          <button
            disabled={!hint || !hint.https || paste.isPending || needsSharing(hint.provider, visibility)}
            onClick={() => paste.mutate()}
            className="rounded border border-canopy-500 px-2 py-1 font-medium text-canopy-700 disabled:opacity-50"
          >
            Add + link
          </button>
        </div>
      )}
      {hint?.provider === "claude" && needsSharing(hint.provider, visibility) && (
        <p className="text-amber-700">
          Share it in Claude first (organization or named people) — private docs stay in your own My docs.
        </p>
      )}
      {err && <p className="text-red-600">{docErrorMessage(err)}</p>}
    </div>
  );
}
