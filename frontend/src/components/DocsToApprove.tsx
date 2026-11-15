import { useMutation } from "@tanstack/react-query";

import { api } from "../api/client";
import type { DocReference } from "../api/types";
import { docErrorMessage, docTitle, providerLabel } from "../lib/docs";

/** Design docs in review that this person signs off (a planner on their home, §V8). Approval is
 *  a human act recorded with their name and the version. */
export default function DocsToApprove({
  docs,
  onChange,
}: {
  docs: DocReference[];
  onChange: () => void;
}) {
  const approve = useMutation({
    mutationFn: (id: number) => api.post(`/docs/${id}/approve`, {}),
    onSuccess: onChange,
  });
  return (
    <div className="rounded-lg border border-sky-200 bg-sky-50 p-4">
      <h2 className="mb-2 font-semibold">
        Design docs to approve{" "}
        <span className="text-xs font-normal text-slate-500">(read the version, then sign it off)</span>
      </h2>
      <ul className="space-y-1 text-sm">
        {docs.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center gap-2">
            <a href={d.url} target="_blank" rel="noreferrer" className="text-canopy-700 hover:underline">
              {docTitle(d)}
            </a>
            <span className="text-xs text-slate-500">
              {providerLabel(d.provider)}
              {d.review_version ? ` · ${d.review_version}` : ""}
            </span>
            <button
              onClick={() => approve.mutate(d.id)}
              disabled={approve.isPending}
              className="ml-auto rounded bg-emerald-600 px-2 py-0.5 text-xs font-medium text-white"
            >
              Approve{d.review_version ? ` ${d.review_version}` : ""}
            </button>
          </li>
        ))}
      </ul>
      {approve.isError && <p className="mt-1 text-xs text-red-600">{docErrorMessage(approve.error)}</p>}
    </div>
  );
}
