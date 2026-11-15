import { useState } from "react";

import type { DocLinkEntity, DocRelation } from "../api/types";
import LinkedDocs from "./LinkedDocs";

/** A compact "docs" toggle for a row in a list (a milestone, an outcome, a risk, a retro): the
 *  linked design docs load only when opened, so a long list stays one query. */
export default function DocsToggle({
  entityType,
  entityId,
  projectId,
  initiativeId,
  mayLink,
  defaultRelation = "reference",
  label = "docs",
}: {
  entityType: DocLinkEntity;
  entityId: number;
  projectId?: number;
  initiativeId?: number;
  mayLink: boolean;
  defaultRelation?: DocRelation;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="w-full">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-canopy-700 hover:underline"
        aria-expanded={open}
      >
        {open ? `hide ${label}` : label}
      </button>
      {open && (
        <div className="mt-1 rounded border border-slate-100 bg-slate-50 p-2">
          <LinkedDocs
            entityType={entityType}
            entityId={entityId}
            projectId={projectId}
            initiativeId={initiativeId}
            mayLink={mayLink}
            defaultRelation={defaultRelation}
            title="Design docs"
          />
        </div>
      )}
    </div>
  );
}
