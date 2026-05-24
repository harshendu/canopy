import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { api } from "../api/client";
import type { ProjectHealth } from "../api/types";
import { HEALTH_OPTIONS, healthTone } from "../lib/health";
import TagEditor from "./TagEditor";

/** A compact, editable strip of delivery metadata (manual health + weekly status note + tags)
 *  for a project or initiative header. The human health sits alongside the computed risk. */
export default function DeliveryMetaBar({
  scope,
  id,
  health,
  statusNote,
  tags,
  mayWrite,
  onSaved,
}: {
  scope: "project" | "initiative";
  id: number;
  health: ProjectHealth | null;
  statusNote: string | null;
  tags: string[];
  mayWrite: boolean;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draftHealth, setDraftHealth] = useState<ProjectHealth | "">(health ?? "");
  const [draftNote, setDraftNote] = useState(statusNote ?? "");
  const [draftTags, setDraftTags] = useState<string[]>(tags);

  const base = scope === "project" ? "/projects" : "/initiatives";
  const tone = healthTone(health);

  const save = useMutation({
    mutationFn: () =>
      api.patch(`${base}/${id}`, {
        health: draftHealth || null,
        status_note: draftNote || null,
        tags: draftTags,
      }),
    onSuccess: () => {
      setEditing(false);
      onSaved();
    },
  });

  if (!editing) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${tone.badge}`}>{tone.label}</span>
        {statusNote && <span className="text-slate-600">{statusNote}</span>}
        {tags.map((t) => (
          <span key={t} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            {t}
          </span>
        ))}
        {mayWrite && (
          <button
            onClick={() => {
              setDraftHealth(health ?? "");
              setDraftNote(statusNote ?? "");
              setDraftTags(tags);
              setEditing(true);
            }}
            className="text-xs text-slate-400 hover:text-canopy-700"
          >
            edit status
          </button>
        )}
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
      className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-3 text-sm"
    >
      <select
        value={draftHealth}
        onChange={(e) => setDraftHealth(e.target.value as ProjectHealth | "")}
        className="rounded border border-slate-300 px-2 py-1 text-sm"
      >
        <option value="">Auto (computed)</option>
        {HEALTH_OPTIONS.map((h) => (
          <option key={h} value={h}>
            {healthTone(h).label}
          </option>
        ))}
      </select>
      <input
        value={draftNote}
        onChange={(e) => setDraftNote(e.target.value)}
        placeholder="Weekly status headline"
        className="grow rounded border border-slate-300 px-3 py-1 text-sm"
      />
      <TagEditor tags={draftTags} onChange={setDraftTags} />
      <button
        type="submit"
        disabled={save.isPending}
        className="rounded bg-canopy-700 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
      >
        {save.isPending ? "Saving…" : "Save"}
      </button>
      <button
        type="button"
        onClick={() => setEditing(false)}
        className="px-2 py-1 text-xs text-slate-500"
      >
        Cancel
      </button>
    </form>
  );
}
