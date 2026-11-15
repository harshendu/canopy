import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  ArtifactSuggestion,
  ArtifactSuggestions,
  ArtifactSyncStatus,
  DesignDoc,
  DocRegisterResult,
  DocVisibility,
  Project,
} from "../api/types";
import {
  VISIBILITY_LABEL,
  artifactTypeLabel,
  classifyUrl,
  docErrorMessage,
  docTitle,
  formatLabel,
  isSharedVisibility,
  providerLabel,
  slugify,
  suggestionTitle,
} from "../lib/docs";
import { useCurrentUser } from "../lib/useCurrentUser";

const PROMOTE_VISIBILITY: DocVisibility[] = ["org", "users", "public"];

/** Personal design docs (USER_FLOWS §V6): docs you track for yourself only — no sharing
 *  needed, nobody else sees them in canopy. Promote one to file it under a project once it is
 *  shared in Claude. */
export default function MyDocs() {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [promoting, setPromoting] = useState<number | null>(null);
  const docs = useQuery({
    queryKey: ["docs", "personal"],
    queryFn: () => api.get<DesignDoc[]>("/docs?personal=true"),
  });
  const invalidate = () => void qc.invalidateQueries({ queryKey: ["docs"] });
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/docs/${id}`),
    onSuccess: invalidate,
  });
  const items = docs.data ?? [];
  const { data: me } = useCurrentUser();
  const setStore = useMutation({
    mutationFn: (store: "repo" | "drive" | null) =>
      api.patch("/auth/me/preferences", { doc_snapshot_store: store }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["me"] }),
  });

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-semibold">
          My docs <span className="text-xs font-normal text-slate-400">(only you see these)</span>
        </h2>
        <button
          onClick={() => setAdding((v) => !v)}
          className="rounded border border-canopy-500 px-2 py-0.5 text-xs font-medium text-canopy-700"
        >
          {adding ? "Cancel" : "Track a doc"}
        </button>
      </div>
      {adding && (
        <AddPersonalDoc
          onDone={() => {
            setAdding(false);
            invalidate();
          }}
        />
      )}
      <label className="mb-2 flex items-center gap-2 text-xs text-slate-500">
        Frozen copies of approved docs go to
        <select
          value={me?.doc_snapshot_store ?? ""}
          onChange={(e) => setStore.mutate((e.target.value || null) as "repo" | "drive" | null)}
          className="rounded border border-slate-300 px-1 py-0.5"
          title="When a decision is made on a doc, a Claude session saves a copy of that version here"
        >
          <option value="">ask each time</option>
          <option value="repo">the repo (a pull request)</option>
          <option value="drive">Google Drive</option>
        </select>
      </label>
      <ClaudeSuggestions onTracked={invalidate} />
      {items.length === 0 ? (
        <p className="text-sm text-slate-400">
          Nothing tracked privately. Claude sessions can add docs here as you work.
        </p>
      ) : (
        <ul className="space-y-1 text-sm">
          {items.map((d) => (
            <li key={d.id} className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <a
                  href={d.url}
                  target="_blank"
                  rel="noreferrer"
                  className="max-w-[18rem] truncate text-canopy-700 hover:underline"
                >
                  {docTitle(d)}
                </a>
                <span className="rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-500">
                  {d.kind_label} · {providerLabel(d.provider)} · {formatLabel(d.format)}
                </span>
                <button
                  onClick={() => setPromoting(promoting === d.id ? null : d.id)}
                  className="ml-auto text-xs text-canopy-700 hover:underline"
                >
                  share with the team
                </button>
                <button
                  onClick={() => remove.mutate(d.id)}
                  className="text-xs text-slate-400 hover:text-red-600"
                >
                  remove
                </button>
              </div>
              {promoting === d.id && (
                <PromoteForm
                  doc={d}
                  onDone={() => {
                    setPromoting(null);
                    invalidate();
                  }}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AddPersonalDoc({ onDone }: { onDone: () => void }) {
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("other");
  const hint = url.trim() ? classifyUrl(url) : null;
  const add = useMutation({
    mutationFn: () =>
      api.post<DocRegisterResult>("/docs/register", {
        url: url.trim(),
        title: title || null,
        kind: slugify(kind),
        personal: true,
        visibility: hint?.provider === "claude" ? "owner" : "unknown",
      }),
    onSuccess: onDone,
  });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (hint?.https) add.mutate();
      }}
      className="mb-3 flex flex-wrap items-center gap-2 text-sm"
    >
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://claude.ai/artifact/…"
        className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1"
        aria-label="Document link"
      />
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title"
        className="w-36 rounded border border-slate-300 px-2 py-1"
      />
      <input
        value={kind}
        onChange={(e) => setKind(e.target.value)}
        placeholder="Kind"
        className="w-28 rounded border border-slate-300 px-2 py-1"
        aria-label="Kind"
      />
      <button
        disabled={!hint?.https || add.isPending}
        className="rounded bg-canopy-500 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
      >
        Track
      </button>
      {add.isError && <p className="w-full text-xs text-red-600">{docErrorMessage(add.error)}</p>}
    </form>
  );
}

function PromoteForm({ doc, onDone }: { doc: DesignDoc; onDone: () => void }) {
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<Project[]>("/projects"),
  });
  const [projectId, setProjectId] = useState<number | "">("");
  const [visibility, setVisibility] = useState<DocVisibility>(
    isSharedVisibility(doc.visibility) ? (doc.visibility as DocVisibility) : "org",
  );
  const promote = useMutation({
    mutationFn: () =>
      api.post(`/docs/${doc.id}/promote`, {
        scope_level: "project",
        scope_id: projectId,
        visibility: doc.provider === "claude" ? visibility : undefined,
      }),
    onSuccess: onDone,
  });
  return (
    <div className="ml-2 space-y-1 rounded border border-slate-200 bg-slate-50 p-2 text-xs">
      {doc.provider === "claude" && (
        <p className="text-slate-500">
          First share it in Claude (Share → your organization or named people), then say who can
          open it here.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={projectId}
          onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : "")}
          className="rounded border border-slate-300 px-1 py-1"
        >
          <option value="">File under project…</option>
          {(projects.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.key} — {p.name}
            </option>
          ))}
        </select>
        {doc.provider === "claude" && (
          <select
            value={visibility}
            onChange={(e) => setVisibility(e.target.value as DocVisibility)}
            className="rounded border border-slate-300 px-1 py-1"
          >
            {PROMOTE_VISIBILITY.map((v) => (
              <option key={v} value={v}>
                Shared with: {VISIBILITY_LABEL[v]}
              </option>
            ))}
          </select>
        )}
        <button
          disabled={projectId === "" || promote.isPending}
          onClick={() => promote.mutate()}
          className="rounded bg-canopy-500 px-2 py-1 font-medium text-white disabled:opacity-50"
        >
          Share
        </button>
      </div>
      {promote.isError && <p className="text-red-600">{docErrorMessage(promote.error)}</p>}
    </div>
  );
}

/** Your own Claude artifacts nobody tracks yet (USER_FLOWS §V11) — only when an admin turned on
 *  the organization artifact sync. Listed live on request (metadata only, never stored); nothing
 *  is tracked until you pick it and paste its link. */
function ClaudeSuggestions({ onTracked }: { onTracked: () => void }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [tracking, setTracking] = useState<string | null>(null);
  // own query roots: a `docs` event must not re-list the organization
  const status = useQuery({
    queryKey: ["artifact-sync"],
    queryFn: () => api.get<ArtifactSyncStatus>("/docs/artifact-sync"),
    staleTime: 5 * 60 * 1000,
  });
  const suggestions = useQuery({
    queryKey: ["artifact-suggestions"],
    queryFn: () => api.get<ArtifactSuggestions>("/docs/suggestions"),
    enabled: open,
    staleTime: 60 * 1000,
  });
  if (!status.data?.available) return null;
  const items = suggestions.data?.items ?? [];
  return (
    <div className="mb-3 rounded border border-slate-200 bg-slate-50 p-2 text-xs">
      <div className="flex items-center justify-between">
        <span className="font-medium text-slate-600">From Claude</span>
        <button onClick={() => setOpen((v) => !v)} className="text-canopy-700 hover:underline">
          {open ? "Hide" : "Find my untracked artifacts"}
        </button>
      </div>
      {open && (
        <div className="mt-2 space-y-1">
          {suggestions.isLoading && <p className="text-slate-400">Listing your artifacts…</p>}
          {suggestions.isError && <p className="text-red-600">{docErrorMessage(suggestions.error)}</p>}
          {suggestions.data && items.length === 0 && (
            <p className="text-slate-400">Every artifact of yours is tracked already.</p>
          )}
          {suggestions.data && !suggestions.data.complete && (
            <p className="text-amber-700">The list was cut short — some artifacts may be missing.</p>
          )}
          <ul className="space-y-1">
            {items.map((a) => (
              <li key={a.artifact_id} className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="max-w-[16rem] truncate text-slate-700">{suggestionTitle(a)}</span>
                  <span className="rounded bg-white px-1 py-0.5 text-[10px] text-slate-500">
                    {artifactTypeLabel(a.artifact_type)} · {VISIBILITY_LABEL[a.visibility as DocVisibility] ?? a.visibility}
                    {a.updated_at && <> · edited {a.updated_at.slice(0, 10)}</>}
                  </span>
                  <button
                    onClick={() => setTracking(tracking === a.artifact_id ? null : a.artifact_id)}
                    className="ml-auto text-canopy-700 hover:underline"
                  >
                    {tracking === a.artifact_id ? "Cancel" : "Track…"}
                  </button>
                </div>
                {tracking === a.artifact_id && (
                  <TrackSuggestion
                    artifact={a}
                    onDone={() => {
                      setTracking(null);
                      void qc.invalidateQueries({ queryKey: ["artifact-suggestions"] });
                      onTracked();
                    }}
                  />
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function TrackSuggestion({ artifact, onDone }: { artifact: ArtifactSuggestion; onDone: () => void }) {
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState(artifact.artifact_type === "claude_docs" ? "design" : "other");
  const hint = url.trim() ? classifyUrl(url) : null;
  const isClaude = hint?.provider === "claude" && hint.https;
  const track = useMutation({
    mutationFn: () =>
      api.post<DocRegisterResult>("/docs/register", {
        url: url.trim(),
        kind: slugify(kind),
        personal: true,
        source_artifact_id: artifact.artifact_id,
      }),
    onSuccess: onDone,
  });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (isClaude) track.mutate();
      }}
      className="ml-2 flex flex-wrap items-center gap-2"
    >
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="Its link (Share → Copy link)"
        className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1"
        aria-label="Artifact link"
      />
      <input
        value={kind}
        onChange={(e) => setKind(e.target.value)}
        className="w-24 rounded border border-slate-300 px-2 py-1"
        aria-label="Kind"
      />
      <button
        disabled={!isClaude || track.isPending}
        className="rounded bg-canopy-500 px-2 py-1 font-medium text-white disabled:opacity-50"
      >
        Track
      </button>
      {url.trim() !== "" && !isClaude && <p className="w-full text-slate-500">Paste its claude.ai link.</p>}
      {track.isError && <p className="w-full text-red-600">{docErrorMessage(track.error)}</p>}
    </form>
  );
}
