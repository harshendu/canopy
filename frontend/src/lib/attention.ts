import type { ProjectSummary } from "../api/types";

/**
 * Cross-project "what needs me" — derived purely from the portfolio summaries (no N+1 alert
 * fetches). Green is silent: only projects with a real exception appear. Errors sort before
 * warnings. Each item deep-links into the workspace that owns it.
 */
export interface AttentionItem {
  projectId: number;
  projectKey: string;
  severity: "error" | "warning";
  message: string;
  tab: string; // ?tab= leaf to open in the project cockpit
}

const ELEVATED = new Set(["high", "critical"]);

export function portfolioAttention(projects: ProjectSummary[]): AttentionItem[] {
  const items: AttentionItem[] = [];
  const push = (
    p: ProjectSummary,
    severity: "error" | "warning",
    message: string,
    tab: string,
  ) => items.push({ projectId: p.id, projectKey: p.key, severity, message, tab });

  for (const p of projects) {
    if (p.health === "off_track") {
      push(p, "error", `${p.name} is marked off track`, "overview");
    }
    // ISO date strings compare lexicographically, so a plain `>` is a valid date comparison.
    if (p.project_end && p.target_date && p.project_end > p.target_date) {
      push(
        p,
        "error",
        `${p.name} is behind target — CPM ends ${p.project_end}, target ${p.target_date}`,
        "gantt",
      );
    }
    if (ELEVATED.has(p.risk_level)) {
      push(
        p,
        p.risk_level === "critical" ? "error" : "warning",
        `${p.name} risk is ${p.risk_level} (${p.risk_score}/100)`,
        "risk",
      );
    }
    if (ELEVATED.has(p.drift_level)) {
      push(p, "warning", `${p.name} architecture drift is ${p.drift_level}`, "drift");
    }
    // Deliberately NOT "open_risks > 0" — a project routinely carrying tracked RAID risk is
    // normal state, not an exception (the register is a ledger, not an alarm; overdue-ness is the
    // real signal, and ProjectSummary doesn't carry a target-date breakdown to compute that here).
    // Flagging every open risk would show almost every project, every time, and defeat "green is
    // silent" — the whole point of this band.
  }
  return items.sort((a, b) =>
    a.severity === b.severity ? 0 : a.severity === "error" ? -1 : 1,
  );
}
