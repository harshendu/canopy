import { Link } from "react-router-dom";
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

export default function Portfolio() {
  const { data, isLoading } = useQuery({
    queryKey: ["portfolio"],
    queryFn: () => api.get<PortfolioResponse>("/projects/portfolio"),
  });
  const projects = data?.projects ?? [];
  const chartData = projects.map((p) => ({ name: p.key, percent: p.avg_percent_complete }));

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Portfolio</h1>

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
              <Link
                key={p.id}
                to={`/projects/${p.id}`}
                className="block rounded-lg border border-slate-200 bg-white p-4 hover:border-canopy-500"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs text-slate-400">{p.key}</span>
                  <div className="flex items-center gap-1">
                    {p.critical_tasks > 0 && (
                      <span className="rounded bg-red-100 px-2 py-0.5 text-xs text-red-700">
                        {p.critical_tasks} critical
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
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
