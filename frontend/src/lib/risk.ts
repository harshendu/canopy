import type { RiskLevel } from "../api/types";

export interface RiskTone {
  label: string;
  badge: string; // tailwind classes for a small badge
  bar: string; // tailwind bg for a progress bar
}

export const RISK_TONES: Record<RiskLevel, RiskTone> = {
  low: { label: "Low", badge: "bg-emerald-100 text-emerald-700", bar: "bg-emerald-500" },
  moderate: { label: "Moderate", badge: "bg-amber-100 text-amber-700", bar: "bg-amber-500" },
  high: { label: "High", badge: "bg-orange-100 text-orange-700", bar: "bg-orange-500" },
  critical: { label: "Critical", badge: "bg-red-100 text-red-700", bar: "bg-red-600" },
};

const FALLBACK: RiskTone = {
  label: "Unknown",
  badge: "bg-slate-100 text-slate-600",
  bar: "bg-slate-400",
};

export function riskTone(level: string): RiskTone {
  return RISK_TONES[level as RiskLevel] ?? FALLBACK;
}

/** Tailwind bg for an individual 0-100 indicator/family score (severity ramp). */
export function scoreBar(score: number): string {
  if (score >= 70) return "bg-red-600";
  if (score >= 45) return "bg-orange-500";
  if (score >= 20) return "bg-amber-500";
  return "bg-emerald-500";
}
