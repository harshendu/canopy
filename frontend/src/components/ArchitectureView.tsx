import { useMemo, useState } from "react";
import { ReactFlow, Background, Controls, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { ADR, ADRStatus, Component, ComponentLink, Connection } from "../api/types";

const KIND_COLORS: Record<string, string> = {
  service: "#2f855a",
  module: "#2563eb",
  datastore: "#b45309",
  external: "#6b7280",
  ui: "#7c3aed",
};
const KINDS = ["service", "module", "datastore", "external", "ui"];
const LINK_KINDS = ["depends_on", "calls", "publishes_to", "reads_from"];
const ADR_STATUSES: ADRStatus[] = ["proposed", "accepted", "superseded", "deprecated"];

export default function ArchitectureView({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const [compName, setCompName] = useState("");
  const [compKind, setCompKind] = useState("service");
  const [src, setSrc] = useState<number | "">("");
  const [dst, setDst] = useState<number | "">("");
  const [linkKind, setLinkKind] = useState("depends_on");
  const [adrTitle, setAdrTitle] = useState("");
  const [adrContext, setAdrContext] = useState("");
  const [adrDecision, setAdrDecision] = useState("");
  const [adrStatus, setAdrStatus] = useState<ADRStatus>("proposed");
  const [adrSupersedes, setAdrSupersedes] = useState<number | "">("");
  const [adrComponentIds, setAdrComponentIds] = useState<number[]>([]);
  const [importConnId, setImportConnId] = useState<number | "">("");
  const [importRef, setImportRef] = useState("");

  const components = useQuery({
    queryKey: ["components", projectId],
    queryFn: () => api.get<Component[]>(`/architecture/components?project_id=${projectId}`),
  });
  const links = useQuery({
    queryKey: ["component-links", projectId],
    queryFn: () =>
      api.get<ComponentLink[]>(`/architecture/component-links?project_id=${projectId}`),
  });
  const adrs = useQuery({
    queryKey: ["adrs", projectId],
    queryFn: () => api.get<ADR[]>(`/architecture/adrs?project_id=${projectId}`),
  });
  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<Connection[]>("/connectors/connections"),
  });
  const docConnections = (connections.data ?? []).filter(
    (c) => c.provider === "github" || c.provider === "gdrive",
  );

  const importAdr = useMutation({
    mutationFn: () => {
      const conn = docConnections.find((c) => c.id === importConnId);
      return api.post("/architecture/adrs/import", {
        project_id: projectId,
        provider: conn?.provider,
        connection_id: importConnId,
        ref: importRef,
      });
    },
    onSuccess: () => {
      setImportRef("");
      qc.invalidateQueries({ queryKey: ["adrs", projectId] });
    },
  });

  const addComponent = useMutation({
    mutationFn: () =>
      api.post("/architecture/components", {
        project_id: projectId,
        name: compName,
        kind: compKind,
      }),
    onSuccess: () => {
      setCompName("");
      qc.invalidateQueries({ queryKey: ["components", projectId] });
    },
  });
  const addLink = useMutation({
    mutationFn: () =>
      api.post("/architecture/component-links", {
        source_id: src,
        target_id: dst,
        kind: linkKind,
      }),
    onSuccess: () => {
      setSrc("");
      setDst("");
      qc.invalidateQueries({ queryKey: ["component-links", projectId] });
    },
  });
  const addAdr = useMutation({
    mutationFn: () =>
      api.post("/architecture/adrs", {
        project_id: projectId,
        title: adrTitle,
        status: adrStatus,
        context: adrContext || null,
        decision: adrDecision || null,
        supersedes_id: adrSupersedes || null,
        component_ids: adrComponentIds,
      }),
    onSuccess: () => {
      setAdrTitle("");
      setAdrContext("");
      setAdrDecision("");
      setAdrStatus("proposed");
      setAdrSupersedes("");
      setAdrComponentIds([]);
      qc.invalidateQueries({ queryKey: ["adrs", projectId] });
    },
  });

  const updateAdrStatus = useMutation({
    mutationFn: (vars: { id: number; status: string }) =>
      api.patch(`/architecture/adrs/${vars.id}`, { status: vars.status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["adrs", projectId] }),
  });

  const { nodes, edges } = useMemo(() => {
    const comps = components.data ?? [];
    const nodes: Node[] = comps.map((c, i) => ({
      id: String(c.id),
      position: { x: (i % 4) * 220, y: Math.floor(i / 4) * 130 },
      data: { label: c.name },
      style: {
        borderRadius: 8,
        padding: 6,
        fontSize: 12,
        border: `2px solid ${KIND_COLORS[c.kind] ?? "#cbd5e1"}`,
      },
    }));
    const edges: Edge[] = (links.data ?? []).map((l) => ({
      id: String(l.id),
      source: String(l.source_id),
      target: String(l.target_id),
      label: l.kind,
    }));
    return { nodes, edges };
  }, [components.data, links.data]);

  const comps = components.data ?? [];
  const adrList = adrs.data ?? [];
  const componentName = (cid: number) => comps.find((c) => c.id === cid)?.name ?? `#${cid}`;
  const adrNumber = (aid: number) => adrList.find((a) => a.id === aid)?.number;

  const toggleComponent = (cid: number) =>
    setAdrComponentIds((ids) =>
      ids.includes(cid) ? ids.filter((x) => x !== cid) : [...ids, cid],
    );

  return (
    <div className="space-y-5">
      <div className="h-[440px] rounded-lg border border-slate-200 bg-white">
        {comps.length > 0 ? (
          <ReactFlow nodes={nodes} edges={edges} fitView>
            <Background />
            <Controls />
          </ReactFlow>
        ) : (
          <p className="p-4 text-sm text-slate-500">
            No components yet — add one below to start the system map.
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (compName) addComponent.mutate();
          }}
          className="space-y-2 rounded-lg border border-slate-200 bg-white p-4"
        >
          <h2 className="font-semibold">Add component</h2>
          <div className="flex gap-2">
            <input
              value={compName}
              onChange={(e) => setCompName(e.target.value)}
              placeholder="Component name"
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <select
              value={compKind}
              onChange={(e) => setCompKind(e.target.value)}
              className="rounded border border-slate-300 px-3 py-2 text-sm"
            >
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
            <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
              Add
            </button>
          </div>
        </form>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (src && dst && src !== dst) addLink.mutate();
          }}
          className="space-y-2 rounded-lg border border-slate-200 bg-white p-4"
        >
          <h2 className="font-semibold">Add relationship</h2>
          <div className="flex gap-2">
            <select
              value={src}
              onChange={(e) => setSrc(Number(e.target.value))}
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">From…</option>
              {comps.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <select
              value={dst}
              onChange={(e) => setDst(Number(e.target.value))}
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">To…</option>
              {comps.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <select
              value={linkKind}
              onChange={(e) => setLinkKind(e.target.value)}
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            >
              {LINK_KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
            <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
              Link
            </button>
          </div>
        </form>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (adrTitle) addAdr.mutate();
          }}
          className="space-y-2 rounded-lg border border-slate-200 bg-white p-4"
        >
          <h2 className="font-semibold">Record an ADR</h2>
          <input
            value={adrTitle}
            onChange={(e) => setAdrTitle(e.target.value)}
            placeholder="Decision title"
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <textarea
            value={adrContext}
            onChange={(e) => setAdrContext(e.target.value)}
            placeholder="Context / forces"
            rows={2}
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <textarea
            value={adrDecision}
            onChange={(e) => setAdrDecision(e.target.value)}
            placeholder="Decision"
            rows={2}
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <div className="flex gap-2">
            <select
              value={adrStatus}
              onChange={(e) => setAdrStatus(e.target.value as ADRStatus)}
              className="rounded border border-slate-300 px-3 py-2 text-sm"
            >
              {ADR_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select
              value={adrSupersedes}
              onChange={(e) => setAdrSupersedes(e.target.value ? Number(e.target.value) : "")}
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">Supersedes… (none)</option>
              {adrList.map((a) => (
                <option key={a.id} value={a.id}>
                  ADR-{String(a.number).padStart(4, "0")} {a.title}
                </option>
              ))}
            </select>
          </div>
          {comps.length > 0 && (
            <div className="flex flex-wrap gap-2 text-xs text-slate-600">
              <span className="text-slate-400">Affects:</span>
              {comps.map((c) => (
                <label key={c.id} className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={adrComponentIds.includes(c.id)}
                    onChange={() => toggleComponent(c.id)}
                  />
                  {c.name}
                </label>
              ))}
            </div>
          )}
          <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
            Add ADR
          </button>

          <div className="mt-2 border-t border-slate-100 pt-2">
            <div className="mb-1 text-xs font-medium text-slate-400">Or import from a doc</div>
            <div className="flex gap-2">
              <select
                value={importConnId}
                onChange={(e) => setImportConnId(e.target.value ? Number(e.target.value) : "")}
                className="rounded border border-slate-300 px-2 py-1 text-sm"
              >
                <option value="">Source…</option>
                {docConnections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.provider}: {c.name}
                  </option>
                ))}
              </select>
              <input
                value={importRef}
                onChange={(e) => setImportRef(e.target.value)}
                placeholder="path/to/adr.md or Drive file id"
                className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
              />
              <button
                type="button"
                onClick={() => importConnId && importRef && importAdr.mutate()}
                disabled={importAdr.isPending}
                className="rounded border border-slate-300 px-3 py-1 text-sm text-slate-600 disabled:opacity-50"
              >
                Import
              </button>
            </div>
          </div>
        </form>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 font-semibold">Decisions</h2>
          <ul className="space-y-3 text-sm">
            {adrList.map((a) => (
              <li key={a.id} className="space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span>
                    <span className="font-mono text-xs text-slate-400">
                      ADR-{String(a.number).padStart(4, "0")}
                    </span>{" "}
                    {a.title}
                  </span>
                  <select
                    value={a.status}
                    onChange={(e) => updateAdrStatus.mutate({ id: a.id, status: e.target.value })}
                    className="rounded border border-slate-200 px-1 py-0.5 text-xs text-slate-600"
                  >
                    {ADR_STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </div>
                {a.supersedes_id && adrNumber(a.supersedes_id) && (
                  <div className="text-xs text-slate-400">
                    supersedes ADR-{String(adrNumber(a.supersedes_id)).padStart(4, "0")}
                  </div>
                )}
                {a.component_ids.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {a.component_ids.map((cid) => (
                      <span
                        key={cid}
                        className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500"
                      >
                        {componentName(cid)}
                      </span>
                    ))}
                  </div>
                )}
              </li>
            ))}
            {adrList.length === 0 && <li className="text-slate-400">No decisions recorded yet.</li>}
          </ul>
        </div>
      </div>
    </div>
  );
}
