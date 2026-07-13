import { Link, useNavigate } from "react-router-dom";
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
import { portfolioAttention } from "../lib/attention";
import ExportMenu from "../components/ExportMenu";
import { PageHeader } from "../components/PageHeader";
import { PreviewLink } from "../components/PreviewLink";
import { QueryError } from "../components/QueryError";
import { Icon } from "../components/icons";

export default function Portfolio() {
  const navigate = useNavigate();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["portfolio"],
    queryFn: () => api.get<PortfolioResponse>("/projects/portfolio"),
  });
  const projects = data?.projects ?? [];
  const chartData = projects.map((p) => ({ name: p.key, percent: p.avg_percent_complete }));
  const attention = portfolioAttention(projects);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Portfolio"
        subtitle="What needs you across every project, then completion, risk, and drift at a glance."
        actions={<ExportMenu scope="portfolio" />}
      />

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : isError ? (
        <QueryError
          error={error}
          onRetry={() => void refetch()}
          label="Couldn’t load the portfolio"
        />
      ) : projects.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
          No projects yet. Projects are where you plan and schedule work.{" "}
          <Link to="/projects" className="font-medium text-emerald-700 hover:underline">
            Create your first project →
          </Link>
        </div>
      ) : (
        <>
          {/* Cross-project "needs attention" — green is silent, so this only renders a list when
              there's something to see (§ portfolioAttention). Each row deep-links straight into
              the workspace that owns it, mirroring the per-project Overview's exception list. */}
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="mb-2 flex items-center gap-2">
              <Icon name="alerts" size={16} />
              <h2 className="font-semibold">Needs attention</h2>
              {attention.length > 0 && (
                <span className="rounded-full bg-amber-500 px-1.5 text-xs font-semibold text-white">
                  {attention.length}
                </span>
              )}
            </div>
            {attention.length === 0 ? (
              <p className="flex items-center gap-1.5 text-sm text-slate-500">
                <span className="h-2 w-2 rounded-full bg-emerald-500" />
                Every project is on track — no open exceptions.
              </p>
            ) : (
              <ul className="space-y-1">
                {attention.map((a, i) => (
                  <li key={`${a.projectId}-${a.tab}-${i}`}>
                    <button
                      onClick={() => navigate(`/projects/${a.projectId}?tab=${a.tab}`)}
                      className="flex w-full items-start gap-2 rounded px-2 py-1 text-left text-sm hover:bg-slate-50"
                    >
                      <span
                        className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                          a.severity === "error" ? "bg-red-500" : "bg-amber-500"
                        }`}
                      />
                      <span className="flex-1 text-slate-700">
                        <span className="mr-1.5 font-mono text-xs text-slate-400">
                          {a.projectKey}
                        </span>
                        {a.message}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

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
