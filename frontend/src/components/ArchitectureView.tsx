import { useMemo, useState } from "react";
import { ReactFlow, Background, Controls, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { ADR, Component, ComponentLink } from "../api/types";

const KIND_COLORS: Record<string, string> = {
  service: "#2f855a",
  module: "#2563eb",
  datastore: "#b45309",
  external: "#6b7280",
  ui: "#7c3aed",
};
const KINDS = ["service", "module", "datastore", "external", "ui"];
const LINK_KINDS = ["depends_on", "calls", "publishes_to", "reads_from"];

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
        context: adrContext || null,
        decision: adrDecision || null,
      }),
    onSuccess: () => {
      setAdrTitle("");
      setAdrContext("");
      setAdrDecision("");
      qc.invalidateQueries({ queryKey: ["adrs", projectId] });
    },
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
          <button className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white">
            Add ADR
          </button>
        </form>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 font-semibold">Decisions</h2>
          <ul className="space-y-2 text-sm">
            {(adrs.data ?? []).map((a) => (
              <li key={a.id} className="flex items-center justify-between">
                <span>
                  <span className="font-mono text-xs text-slate-400">
                    ADR-{String(a.number).padStart(4, "0")}
                  </span>{" "}
                  {a.title}
                </span>
                <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                  {a.status}
                </span>
              </li>
            ))}
            {adrs.data?.length === 0 && (
              <li className="text-slate-400">No decisions recorded yet.</li>
            )}
          </ul>
        </div>
      </div>
    </div>
  );
}
