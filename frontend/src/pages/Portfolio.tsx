import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api/client";
import type { PortfolioResponse } from "../api/types";
import { riskTone } from "../lib/risk";
import { healthTone } from "../lib/health";
import ExportMenu from "../components/ExportMenu";
import { PageHeader } from "../components/PageHeader";
import { PreviewLink } from "../components/PreviewLink";

export default function Portfolio() {
  const { data, isLoading } = useQuery({
    queryKey: ["portfolio"],
    queryFn: () => api.get<PortfolioResponse>("/projects/portfolio"),
  });
  const projects = data?.projects ?? [];
  const chartData = projects.map((p) => ({ name: p.key, percent: p.avg_percent_complete }));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Portfolio"
        subtitle="Every project at a glance — completion, risk, and drift. Open one for the full cockpit."
        actions={<ExportMenu scope="portfolio" />}
      />

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : projects.length === 0 ? (
        <p className="text-sm text-slate-400">No projects yet.</p>
      ) : (
        <>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="mb-3 text-sm font-semibold text-slate-600">
              Average completion by project
            </h2>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="name" fontSize={12} />
                <YAxis domain={[0, 100]} fontSize={12} unit="%" />
                <Tooltip />
                <Bar dataKey="percent" fill="#2f855a" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <PreviewLink
                key={p.id}
                target={{ kind: "project", id: p.id }}
                className="block rounded-lg border border-slate-200 bg-white p-4 hover:border-canopy-500"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs text-slate-400">{p.key}</span>
                  <div className="flex flex-wrap items-center justify-end gap-1">
                    {p.health && (
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${healthTone(p.health).badge}`}
                      >
                        {healthTone(p.health).label}
                      </span>
                    )}
                    {p.critical_tasks > 0 && (
                      <span className="rounded bg-red-100 px-2 py-0.5 text-xs text-red-700">
                        {p.critical_tasks} critical
                      </span>
                    )}
                    {p.open_risks > 0 && (
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                        {p.open_risks} risk{p.open_risks === 1 ? "" : "s"}
                      </span>
                    )}
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${riskTone(p.risk_level).badge}`}
                    >
                      risk {p.risk_score}
                    </span>
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${riskTone(p.drift_level).badge}`}
                    >
                      drift {p.drift_score}
                    </span>
                  </div>
                </div>
                <div className="mt-1 font-medium">{p.name}</div>
                {p.status_note && (
                  <div className="mt-1 text-xs text-slate-500">{p.status_note}</div>
                )}
                {p.tags.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {p.tags.map((t) => (
                      <span
                        key={t}
                        className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}
                <div className="mt-3 h-2 w-full rounded bg-slate-100">
                  <div
                    className="h-2 rounded bg-canopy-500"
                    style={{ width: `${Math.min(p.avg_percent_complete, 100)}%` }}
                  />
                </div>
                <div className="mt-2 flex justify-between text-xs text-slate-500">
                  <span>
                    {p.completed_tasks}/{p.total_tasks} tasks
                  </span>
                  <span>{p.project_end ? `ends ${p.project_end}` : "unscheduled"}</span>
                </div>
              </PreviewLink>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
