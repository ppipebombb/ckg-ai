"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clearHipertensiChartsCache,
  getHipertensiCharts,
} from "@/lib/api/hipertensi-charts";

export const hipertensiChartsKeys = {
  all: ["hipertensi-charts"] as const,
  one: (puskesmasId: string) => [...hipertensiChartsKeys.all, puskesmasId] as const,
};

/** The 6-chart dashboard payload for one puskesmas; polls while the backend
 * cache is still warming (`computing`), then caches the warm result. */
export function useHipertensiCharts(puskesmasId: string | undefined) {
  return useQuery({
    queryKey: hipertensiChartsKeys.one(puskesmasId ?? ""),
    queryFn: () => getHipertensiCharts(puskesmasId!),
    enabled: !!puskesmasId,
    staleTime: 5 * 60_000,
    refetchInterval: (query) => (query.state.data?.computing ? 4000 : false),
  });
}

/** Admin-only: clear the charts Redis cache and re-warm. On success the query is
 * invalidated; its `refetchInterval` + `computing` flag drive the refresh. */
export function useClearHipertensiChartsCache() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (puskesmasId: string) => clearHipertensiChartsCache(puskesmasId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: hipertensiChartsKeys.all });
    },
  });
}
