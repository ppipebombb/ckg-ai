"use client";

import { useQuery } from "@tanstack/react-query";
import { getDmCharts } from "@/lib/api/dm-charts";

export const dmChartsKeys = {
  all: ["dm-charts"] as const,
  one: (puskesmasId: string) => [...dmChartsKeys.all, puskesmasId] as const,
};

/**
 * The 2-chart DM dashboard payload for one puskesmas (rolling cross-year window).
 * Gated on a selected puskesmas; polls every 4s while the backend cache is still
 * warming (`computing`), then caches the warm result for 5 min.
 */
export function useDmCharts(puskesmasId: string | undefined) {
  return useQuery({
    queryKey: dmChartsKeys.one(puskesmasId ?? ""),
    queryFn: () => getDmCharts(puskesmasId!),
    enabled: !!puskesmasId,
    staleTime: 5 * 60_000,
    refetchInterval: (query) => (query.state.data?.computing ? 4000 : false),
  });
}
