"use client";

import { useQuery } from "@tanstack/react-query";
import { getHipertensiCharts } from "@/lib/api/hipertensi-charts";

export const hipertensiChartsKeys = {
  all: ["hipertensi-charts"] as const,
  one: (puskesmasId: string) => [...hipertensiChartsKeys.all, puskesmasId] as const,
};

/**
 * The 6-chart dashboard payload for one puskesmas (rolling cross-year window).
 * Gated on a selected puskesmas; polls every 4s while the backend cache is still
 * warming (`computing`), then caches the warm result for 5 min.
 */
export function useHipertensiCharts(puskesmasId: string | undefined) {
  return useQuery({
    queryKey: hipertensiChartsKeys.one(puskesmasId ?? ""),
    queryFn: () => getHipertensiCharts(puskesmasId!),
    enabled: !!puskesmasId,
    staleTime: 5 * 60_000,
    refetchInterval: (query) => (query.state.data?.computing ? 4000 : false),
  });
}
