import type { Initiative, InitiativeLead, LeadRole, Project, Team, TeamMember } from "../api/types";

/**
 * Pure helpers for the org model and ownership-scoped visibility (USER_FLOWS §R6): teams own
 * products/platforms and hold pods; an initiative has one or more owners and spans the pods of
 * its projects; each project has a single owner.
 */

export interface GroupedInitiatives {
  led: Initiative[];
  others: Initiative[];
}

export function groupByOwnership(
  initiatives: Initiative[],
  ledIds: number[] | undefined,
): GroupedInitiatives {
  const led = new Set(ledIds ?? []);
  return {
    led: initiatives.filter((i) => led.has(i.id)),
    others: initiatives.filter((i) => !led.has(i.id)),
  };
}

export interface TeamGroup {
  team: Team | null; // null = initiatives without a team
  initiatives: Initiative[];
}

/** Group initiatives under their team (team order preserved; teamless last). */
export function groupByTeam(initiatives: Initiative[], teams: Team[]): TeamGroup[] {
  const groups: TeamGroup[] = teams.map((team) => ({
    team,
    initiatives: initiatives.filter((i) => i.team_id === team.id),
  }));
  const known = new Set(teams.map((t) => t.id));
  const rest = initiatives.filter((i) => i.team_id == null || !known.has(i.team_id));
  if (rest.length > 0) groups.push({ team: null, initiatives: rest });
  return groups.filter((g) => g.initiatives.length > 0);
}

/** Pod names an initiative spans, derived from its projects' pods. */
export function podsForInitiative(
  initiativeId: number,
  projects: Project[],
  teams: Team[],
): string[] {
  const podName = new Map<number, string>();
  for (const t of teams) for (const p of t.pods) podName.set(p.id, p.name);
  const names = new Set<string>();
  for (const p of projects) {
    if (p.initiative_id === initiativeId && p.pod_id != null) {
      const n = podName.get(p.pod_id);
      if (n) names.add(n);
    }
  }
  return [...names].sort();
}

export function leadsFor(leads: InitiativeLead[] | undefined, initiativeId: number): InitiativeLead[] {
  return (leads ?? []).filter((l) => l.initiative_id === initiativeId);
}

const ROLE_LABEL: Record<LeadRole, string> = {
  technical: "Tech",
  product: "Product",
  design: "UX",
  manager: "Manager",
};

/** "Priya Raman (Tech) · Daniel Reyes (Product) · Jonah Fields (Manager)" — or "". */
export function leadTeamLabel(leads: InitiativeLead[]): string {
  return leads.map((l) => `${l.engineer_name} (${ROLE_LABEL[l.lead_role]})`).join(" · ");
}

export function roleLabel(role: LeadRole): string {
  return ROLE_LABEL[role];
}

/** "Director: Samir Kapoor · Manager: Jonah Fields" for a team's seats. */
export function teamSeatsLabel(members: TeamMember[]): string {
  const by = (role: TeamMember["role"]) =>
    members.filter((m) => m.role === role).map((m) => m.engineer_name);
  const parts: string[] = [];
  const directors = by("director");
  const managers = by("manager");
  if (directors.length) parts.push(`Director: ${directors.join(", ")}`);
  if (managers.length) parts.push(`Manager: ${managers.join(", ")}`);
  return parts.join(" · ");
}
