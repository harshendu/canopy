// Pure 3-point (PERT) estimate helpers, mirrored from the backend so the detail panel can
// render the expected value + uncertainty band without an extra round-trip.

export function pertMean(optimistic: number, likely: number, pessimistic: number): number {
  return (optimistic + 4 * likely + pessimistic) / 6;
}

export function estimateSpread(optimistic: number, pessimistic: number): number {
  return pessimistic - optimistic;
}

/** A coarse confidence label from the spread relative to the most-likely estimate. */
export function spreadConfidence(
  optimistic: number,
  likely: number,
  pessimistic: number,
): "tight" | "moderate" | "wide" {
  const spread = estimateSpread(optimistic, pessimistic);
  if (likely <= 0) return spread > 0 ? "wide" : "tight";
  if (spread >= likely) return "wide";
  if (spread >= likely / 2) return "moderate";
  return "tight";
}

/** Tailwind classes for a spread-confidence badge. */
export function spreadTone(confidence: "tight" | "moderate" | "wide"): string {
  if (confidence === "wide") return "bg-orange-100 text-orange-700";
  if (confidence === "moderate") return "bg-amber-100 text-amber-700";
  return "bg-emerald-100 text-emerald-700";
}
