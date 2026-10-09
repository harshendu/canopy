import type { Initiative, InitiativeLead, LeadRole } from "../api/types";

/**
 * Pure helpers for ownership-scoped visibility (USER_FLOWS §R6): split the initiative list into
 * the ones the current user leads (editable) and the rest (read-only), and render a lead team.
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

export function leadsFor(leads: InitiativeLead[] | undefined, initiativeId: number): InitiativeLead[] {
  return (leads ?? []).filter((l) => l.initiative_id === initiativeId);
}

const ROLE_LABEL: Record<LeadRole, string> = {
  technical: "Tech",
  product: "Product",
  design: "UX",
};

/** "Priya Raman (Tech) · Daniel Reyes (Product) · Mei Nakamura (UX)" — or "" with no seats. */
export function leadTeamLabel(leads: InitiativeLead[]): string {
  return leads.map((l) => `${l.engineer_name} (${ROLE_LABEL[l.lead_role]})`).join(" · ");
}

export function roleLabel(role: LeadRole): string {
  return ROLE_LABEL[role];
}
