import { useEffect, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { InitiativeRollup, Project, ScenarioDetail } from "../api/types";
import { healthTone } from "../lib/health";
import { riskTone } from "../lib/risk";
import { usePreview } from "../lib/preview";
import { targetKindLabel, targetPath, type PreviewTarget } from "../lib/previewTarget";
import { featureOn, useFeatures } from "../lib/useFeatures";
import { Icon, type IconName } from "./icons";

const PROJECT_TAB_LABEL: Record<string, string> = {
  gantt: "Gantt",
  board: "Board",
  decisions: "Decisions",
  risk: "Risk",
  docs: "Docs",
  deps: "Dependencies",
  specs: "Specs",
};

/**
 * The shared right-side drawer that peeks an entity (project / initiative / scenario) before
 * the user commits to opening its full page. Mounted once by the app shell; driven by the
 * `usePreview` context. Backdrop-click, the ✕, and Escape all dismiss it; "Open" navigates.
 */
export default function PreviewPanel() {
  const { target, closePreview } = usePreview();
  const navigate = useNavigate();

  useEffect(() => {
    if (!target) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closePreview();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [target, closePreview]);

  if (!target) return null;

  const open = (path?: string) => {
    navigate(path ?? targetPath(target));
    closePreview();
  };

  return (
    <>
      <div
        className="animate-fade-in fixed inset-0 z-40 bg-black/20"
        onClick={closePreview}
        aria-hidden
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={`${targetKindLabel(target)} preview`}
        className="animate-slide-in-right fixed right-0 top-0 z-50 flex h-full w-[420px] max-w-full flex-col border-l border-slate-200 bg-white shadow-xl"
      >
        {target.kind === "project" && (
          <ProjectPreview id={target.id} tab={target.tab} onOpen={open} onClose={closePreview} />
        )}
        {target.kind === "initiative" && (
          <InitiativePreview id={target.id} onOpen={open} onClose={closePreview} />
        )}
        {target.kind === "scenario" && (
          <ScenarioPreview target={target} onOpen={open} onClose={closePreview} />
        )}
      </aside>
    </>
  );
}

function PreviewShell({
  eyebrow,
  title,
  badges,
  onClose,
  onOpen,
  openLabel = "Open full view",
  quickLinks,
  children,
}: {
  eyebrow: string;
  title: string;
  badges?: ReactNode;
  onClose: () => void;
  onOpen: (path?: string) => void;
  openLabel?: string;
  quickLinks?: ReactNode;
  children: ReactNode;
}) {
  return (
    <>
      <header className="flex items-start justify-between gap-2 border-b border-slate-100 p-4">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wide text-slate-400">{eyebrow}</div>
          <h2 className="truncate text-lg font-semibold" title={title}>
            {title}
          </h2>
          {badges && <div className="mt-1 flex flex-wrap items-center gap-1">{badges}</div>}
        </div>
        <button
          onClick={onClose}
          aria-label="Close preview"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-700"
        >
          <Icon name="close" size={16} />
        </button>
      </header>
      <div className="flex-1 space-y-4 overflow-y-auto p-4">{children}</div>
      <footer className="space-y-3 border-t border-slate-100 p-4">
        {quickLinks}
        <button
          onClick={() => onOpen()}
          className="flex w-full items-center justify-center gap-1.5 rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white hover:bg-canopy-700"
        >
          {openLabel}
          <Icon name="arrow-right" size={16} />
        </button>
      </footer>
    </>
  );
}

function QuickLinks({
  links,
  onOpen,
}: {
  links: { path: string; label: string; icon: IconName }[];
  onOpen: (path: string) => void;
}) {
  if (links.length === 0) return null;
  return (
    <div>
      <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">
        Jump to
      </div>
      <div className="flex flex-wrap gap-1.5">
        {links.map((l) => (
          <button
            key={l.path}
            onClick={() => onOpen(l.path)}
            className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-600 hover:border-canopy-500 hover:text-canopy-700"
          >
            <Icon name={l.icon} size={13} />
            {l.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-0.5 text-sm text-slate-700">{value}</div>
    </div>
  );
}

function Loading() {
  return <p className="text-sm text-slate-400">Loading preview…</p>;
}

function ProjectPreview({
  id,
  tab,
  onOpen,
  onClose,
}: {
  id: number;
  tab?: string;
  onOpen: (path?: string) => void;
  onClose: () => void;
}) {
  const features = useFeatures();
  const q = useQuery({
    queryKey: ["preview", "project", id],
    queryFn: () => api.get<Project>(`/projects/${id}`),
  });
  const p = q.data;

  const allTabs: { tab?: string; label: string; icon: IconName; on: boolean }[] = [
    { tab: undefined, label: "Gantt", icon: "gantt", on: true },
    { tab: "board", label: "Board", icon: "board", on: featureOn(features, "tracking.board") },
    { tab: "decisions", label: "Decisions", icon: "decisions", on: featureOn(features, "architecture") },
    { tab: "risk", label: "Risk", icon: "risk", on: featureOn(features, "governance.risk") },
    { tab: "docs", label: "Docs", icon: "docs", on: featureOn(features, "governance.docs") },
  ];
  const links = allTabs
    .filter((t) => t.on && t.tab !== tab)
    .map((t) => ({ path: `/projects/${id}${t.tab ? `?tab=${t.tab}` : ""}`, label: t.label, icon: t.icon }));

  const openLabel = tab && PROJECT_TAB_LABEL[tab] ? `Open ${PROJECT_TAB_LABEL[tab]}` : "Open project";
  const health = healthTone(p?.health);

  return (
    <PreviewShell
      eyebrow="Project"
      title={p?.name ?? `Project #${id}`}
      badges={
        p && (
          <>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">
              {p.key}
            </span>
            <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${health.badge}`}>
              {health.label}
            </span>
            {tab && PROJECT_TAB_LABEL[tab] && (
              <span className="rounded bg-canopy-50 px-1.5 py-0.5 text-xs text-canopy-700">
                → {PROJECT_TAB_LABEL[tab]}
              </span>
            )}
          </>
        )
      }
      onClose={onClose}
      onOpen={onOpen}
      openLabel={openLabel}
      quickLinks={<QuickLinks links={links} onOpen={onOpen} />}
    >
      {!p ? (
        <Loading />
      ) : (
        <>
          {p.status_note && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
              {p.status_note}
            </div>
          )}
          {p.description && <Fact label="About" value={p.description} />}
          <div className="grid grid-cols-2 gap-3">
            <Fact label="Start" value={p.start_date ?? "—"} />
            <Fact label="Target" value={p.target_date ?? "—"} />
          </div>
          {p.tags.length > 0 && (
            <Fact
              label="Tags"
              value={
                <div className="flex flex-wrap gap-1">
                  {p.tags.map((t) => (
                    <span key={t} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                      {t}
                    </span>
                  ))}
                </div>
              }
            />
          )}
        </>
      )}
    </PreviewShell>
  );
}

function InitiativePreview({
  id,
  onOpen,
  onClose,
}: {
  id: number;
  onOpen: (path?: string) => void;
  onClose: () => void;
}) {
  const q = useQuery({
    queryKey: ["preview", "initiative", id],
    queryFn: () => api.get<InitiativeRollup>(`/initiatives/${id}/rollup`),
  });
  const r = q.data;
  const risk = riskTone(r?.risk_level ?? "");
  const drift = riskTone(r?.drift_level ?? "");

  return (
    <PreviewShell
      eyebrow="Initiative"
      title={r?.initiative.name ?? `Initiative #${id}`}
      badges={
        r && (
          <>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">
              {r.initiative.key}
            </span>
            {r.on_track != null && (
              <span
                className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                  r.on_track ? "bg-canopy-100 text-canopy-700" : "bg-red-100 text-red-700"
                }`}
              >
                {r.on_track ? "on track" : "behind target"}
              </span>
            )}
          </>
        )
      }
      onClose={onClose}
      onOpen={onOpen}
      openLabel="Open initiative"
      quickLinks={
        <QuickLinks
          links={[
            { path: `/initiatives/${id}/scenarios`, label: "Scenarios", icon: "scenarios" },
          ]}
          onOpen={onOpen}
        />
      }
    >
      {!r ? (
        <Loading />
      ) : (
        <>
          {r.initiative.outcome_statement && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
              {r.initiative.outcome_statement}
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <Fact
              label="Progress"
              value={`${r.avg_percent_complete}% · ${r.completed_tasks}/${r.total_tasks} tasks`}
            />
            <Fact label="Open decisions" value={String(r.open_decisions)} />
            <Fact
              label="Risk"
              value={
                <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${risk.badge}`}>
                  {r.risk_score} · {r.risk_level}
                </span>
              }
            />
            <Fact
              label="Drift"
              value={
                <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${drift.badge}`}>
                  {r.drift_score} · {r.drift_level}
                </span>
              }
            />
            <Fact label="Latest end (CPM)" value={r.project_end ?? "—"} />
            <Fact label="Target" value={r.initiative.target_date ?? "—"} />
          </div>
          <Fact
            label={`Sub-projects (${r.projects.length})`}
            value={
              r.projects.length === 0 ? (
                "None linked yet"
              ) : (
                <ul className="mt-1 space-y-1">
                  {r.projects.slice(0, 5).map((sp) => (
                    <li key={sp.id} className="flex items-center gap-2 text-sm">
                      <span className="font-mono text-xs text-slate-400">{sp.key}</span>
                      <span className="truncate">{sp.name}</span>
                      <span className="ml-auto shrink-0 text-xs text-slate-400">
                        {sp.avg_percent_complete}%
                      </span>
                    </li>
                  ))}
                  {r.projects.length > 5 && (
                    <li className="text-xs text-slate-400">+{r.projects.length - 5} more</li>
                  )}
                </ul>
              )
            }
          />
        </>
      )}
    </PreviewShell>
  );
}

function ScenarioPreview({
  target,
  onOpen,
  onClose,
}: {
  target: Extract<PreviewTarget, { kind: "scenario" }>;
  onOpen: (path?: string) => void;
  onClose: () => void;
}) {
  const q = useQuery({
    queryKey: ["preview", "scenario", target.id],
    queryFn: () => api.get<ScenarioDetail>(`/scenarios/${target.id}`),
  });
  const s = q.data;

  return (
    <PreviewShell
      eyebrow="Scenario"
      title={s?.title ?? `Scenario #${target.id}`}
      badges={
        s && (
          <span
            className={`rounded px-1.5 py-0.5 text-xs font-medium ${
              s.status === "applied"
                ? "bg-canopy-100 text-canopy-700"
                : "bg-slate-100 text-slate-600"
            }`}
          >
            {s.status}
          </span>
        )
      }
      onClose={onClose}
      onOpen={onOpen}
      openLabel="Open scenario"
    >
      {!s ? (
        <Loading />
      ) : (
        <>
          {s.description && <Fact label="About" value={s.description} />}
          <Fact label="Captured" value={s.base_captured_at.slice(0, 10)} />
          <div className="grid grid-cols-3 gap-3">
            <Fact label="Tasks" value={String(s.counts.tasks)} />
            <Fact label="Deps" value={String(s.counts.dependencies)} />
            <Fact label="Milestones" value={String(s.counts.milestones)} />
            <Fact label="Projects" value={String(s.counts.projects)} />
            <Fact label="Allocations" value={String(s.counts.allocations)} />
            <Fact label="Availability" value={String(s.counts.availability)} />
          </div>
        </>
      )}
    </PreviewShell>
  );
}
