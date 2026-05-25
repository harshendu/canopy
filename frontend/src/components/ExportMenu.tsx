import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { api, downloadExport } from "../api/client";
import type { Connection, ExportToDriveResult } from "../api/types";
import { useCurrentUser } from "../lib/useCurrentUser";
import { isPlanner } from "../lib/permissions";

type Scope = "project" | "initiative" | "portfolio";
type Fmt = "pdf" | "csv";

function basePath(scope: Scope, id?: number): string {
  if (scope === "portfolio") return "/portfolio/export";
  if (scope === "initiative") return `/initiatives/${id}/export`;
  return `/projects/${id}/export`;
}

export default function ExportMenu({ scope, id }: { scope: Scope; id?: number }) {
  const [open, setOpen] = useState(false);
  const [connId, setConnId] = useState<number | "">("");
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<ExportToDriveResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<Connection[]>(`/connectors/connections`),
    enabled: open,
  });
  const { data: me } = useCurrentUser();
  // Save-to-Drive is an external write: planner role + the provider's writes set to `direct`.
  const mayWriteDrive = isPlanner(me?.role);
  const driveConns = (connections.data ?? []).filter(
    (c) => c.provider === "gdrive" && c.active && c.authorized,
  );
  const base = basePath(scope, id);
  const stem = scope === "portfolio" ? "portfolio" : `${scope}-${id}`;
  const resolvedConn = connId === "" && driveConns.length === 1 ? driveConns[0].id : connId;
  const resolvedConnObj = driveConns.find((c) => c.id === resolvedConn);
  const writeDirect = resolvedConnObj?.write_strategy === "direct";
  const canDrive = mayWriteDrive && driveConns.length > 0 && resolvedConn !== "" && writeDirect;

  const download = async (fmt: Fmt) => {
    setBusy(`dl-${fmt}`);
    setError(null);
    try {
      await downloadExport(`${base}?fmt=${fmt}`, `${stem}-snapshot.${fmt}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed");
    } finally {
      setBusy(null);
    }
  };

  const toDrive = useMutation({
    mutationFn: (fmt: Fmt) =>
      api.post<ExportToDriveResult>(`${base}/to-drive`, { connection_id: resolvedConn, fmt }),
    onSuccess: (res) => {
      setResult(res);
      setError(null);
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Save to Drive failed"),
  });

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="rounded border border-canopy-500 px-4 py-2 text-sm font-medium text-canopy-700"
      >
        Export ▾
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-72 space-y-3 rounded-lg border border-slate-200 bg-white p-3 text-sm shadow-lg">
          <div>
            <div className="mb-1 font-semibold">Download snapshot</div>
            <div className="flex gap-2">
              <button
                onClick={() => download("pdf")}
                disabled={busy != null}
                className="rounded bg-canopy-700 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
              >
                {busy === "dl-pdf" ? "…" : "PDF"}
              </button>
              <button
                onClick={() => download("csv")}
                disabled={busy != null}
                className="rounded bg-canopy-700 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
              >
                {busy === "dl-csv" ? "…" : "CSV"}
              </button>
            </div>
          </div>

          <div className="border-t border-slate-100 pt-2">
            <div className="mb-1 font-semibold">Save to Google Drive</div>
            {!mayWriteDrive ? (
              <p className="text-xs text-slate-400">
                Saving to Drive needs a planner role. You can still download the snapshot above.
              </p>
            ) : driveConns.length === 0 ? (
              <p className="text-xs text-slate-400">No authorized Google Drive connection.</p>
            ) : (
              <div className="space-y-2">
                {driveConns.length > 1 && (
                  <select
                    value={connId}
                    onChange={(e) =>
                      setConnId(e.target.value === "" ? "" : Number(e.target.value))
                    }
                    className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
                  >
                    <option value="">Pick a Drive connection…</option>
                    {driveConns.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                )}
                <div className="flex gap-2">
                  <button
                    onClick={() => toDrive.mutate("pdf")}
                    disabled={!canDrive || toDrive.isPending}
                    className="rounded border border-canopy-500 px-3 py-1 text-xs text-canopy-700 disabled:opacity-50"
                  >
                    Save PDF
                  </button>
                  <button
                    onClick={() => toDrive.mutate("csv")}
                    disabled={!canDrive || toDrive.isPending}
                    className="rounded border border-canopy-500 px-3 py-1 text-xs text-canopy-700 disabled:opacity-50"
                  >
                    Save CSV
                  </button>
                </div>
                {resolvedConn !== "" && !writeDirect && (
                  <p className="text-xs text-amber-700">
                    Drive writes are {resolvedConnObj?.write_strategy}-managed — saving from
                    canopy is unavailable for this connection.
                  </p>
                )}
              </div>
            )}
          </div>

          {result && (
            <p className="text-xs text-slate-500">
              Saved {result.name}
              {result.link && (
                <>
                  {" · "}
                  <a
                    href={result.link}
                    target="_blank"
                    rel="noreferrer"
                    className="text-canopy-700 underline"
                  >
                    open
                  </a>
                </>
              )}
            </p>
          )}
          {error && <p className="text-xs text-red-600">{error}</p>}
        </div>
      )}
    </div>
  );
}
