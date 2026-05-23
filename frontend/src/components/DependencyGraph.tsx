import { useMemo } from "react";
import { ReactFlow, Background, Controls, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { GanttResponse } from "../api/types";

const CRITICAL = "#dc2626";

export default function DependencyGraph({ data }: { data: GanttResponse }) {
  const { nodes, edges } = useMemo(() => {
    const tasks = data.tasks;
    const successors = new Map<number, number[]>();
    const indegree = new Map<number, number>();
    tasks.forEach((t) => indegree.set(t.id, 0));
    data.links.forEach((l) => {
      successors.set(l.source, [...(successors.get(l.source) ?? []), l.target]);
      indegree.set(l.target, (indegree.get(l.target) ?? 0) + 1);
    });

    // Kahn topological levels for a left-to-right layered layout.
    const level = new Map<number, number>();
    const remaining = new Map(indegree);
    const queue = tasks.filter((t) => (indegree.get(t.id) ?? 0) === 0).map((t) => t.id);
    queue.forEach((id) => level.set(id, 0));
    for (let i = 0; i < queue.length; i++) {
      const id = queue[i];
      const lv = level.get(id) ?? 0;
      for (const s of successors.get(id) ?? []) {
        level.set(s, Math.max(level.get(s) ?? 0, lv + 1));
        remaining.set(s, (remaining.get(s) ?? 0) - 1);
        if ((remaining.get(s) ?? 0) === 0) queue.push(s);
      }
    }

    const perLevel = new Map<number, number>();
    const nodes: Node[] = tasks.map((t) => {
      const lv = level.get(t.id) ?? 0;
      const idx = perLevel.get(lv) ?? 0;
      perLevel.set(lv, idx + 1);
      return {
        id: String(t.id),
        position: { x: lv * 230, y: idx * 90 },
        data: { label: t.text },
        style: {
          borderRadius: 8,
          padding: 6,
          fontSize: 12,
          border: t.is_critical ? `2px solid ${CRITICAL}` : "1px solid #cbd5e1",
        },
      };
    });

    const critical = new Set(tasks.filter((t) => t.is_critical).map((t) => t.id));
    const edges: Edge[] = data.links.map((l) => {
      const onPath = critical.has(l.source) && critical.has(l.target);
      return {
        id: String(l.id),
        source: String(l.source),
        target: String(l.target),
        animated: onPath,
        style: onPath ? { stroke: CRITICAL } : undefined,
      };
    });

    return { nodes, edges };
  }, [data]);

  return (
    <div className="h-[520px] rounded-lg border border-slate-200 bg-white">
      <ReactFlow nodes={nodes} edges={edges} fitView>
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}
