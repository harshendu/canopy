import type { ProjectHealth } from "../api/types";

export interface HealthTone {
  label: string;
  badge: string; // tailwind classes for a small badge
}

export const HEALTH_TONES: Record<ProjectHealth, HealthTone> = {
  on_track: { label: "On track", badge: "bg-emerald-100 text-emerald-700" },
  at_risk: { label: "At risk", badge: "bg-amber-100 text-amber-700" },
  off_track: { label: "Off track", badge: "bg-red-100 text-red-700" },
};

const FALLBACK: HealthTone = { label: "Auto", badge: "bg-slate-100 text-slate-500" };

export function healthTone(health: ProjectHealth | null | undefined): HealthTone {
  if (health == null) return FALLBACK;
  return HEALTH_TONES[health] ?? FALLBACK;
}

export const HEALTH_OPTIONS: ProjectHealth[] = ["on_track", "at_risk", "off_track"];
