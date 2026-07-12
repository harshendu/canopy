import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { FeatureMap } from "../api/types";

const ALL_ON: Record<string, boolean> = {};

/**
 * The effective feature map (GET /features) as a React Query — for the rare caller that
 * must know whether the map has actually loaded (e.g. the persona landing redirect, which
 * would otherwise route to a gated-off surface during the first render).
 */
export function useFeaturesQuery(enabled = true) {
  return useQuery({
    queryKey: ["features"],
    queryFn: () => api.get<FeatureMap>("/features"),
    enabled,
    staleTime: 60 * 1000,
  });
}

/**
 * The effective feature map every surface checks before rendering gated navigation/tabs.
 * Admin toggles publish an SSE event, which invalidates this cache — so a flip shows up
 * everywhere without a reload. While loading, everything reads as ON (the common case)
 * to avoid a nav flash.
 */
export function useFeatures(enabled = true): Record<string, boolean> {
  const { data } = useFeaturesQuery(enabled);
  return data?.features ?? ALL_ON;
}

/** Whether one feature gate is effectively on (unknown/unloaded keys default on). */
export function featureOn(features: Record<string, boolean>, key: string): boolean {
  return features[key] !== false;
}
