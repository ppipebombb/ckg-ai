"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  clearGdpSourceQualityCache,
  getGdpSourceQuality,
  getVisitSummary,
} from "@/lib/api/reports";

export const reportKeys = {
  all: ["reports"] as const,
  visitSummary: (puskesmasId: string | undefined) =>
    [...reportKeys.all, "visit-summary", puskesmasId ?? "all"] as const,
  gdpSourceQuality: (puskesmasId: string | undefined) =>
    [...reportKeys.all, "gdp-source-quality", puskesmasId ?? "all"] as const,
};

export function useVisitSummary(puskesmasId: string | undefined) {
  return useQuery({
    queryKey: reportKeys.visitSummary(puskesmasId),
    queryFn: () => getVisitSummary(puskesmasId),
    placeholderData: keepPreviousData,
  });
}

export function useGdpSourceQuality(puskesmasId: string | undefined) {
  return useQuery({
    queryKey: reportKeys.gdpSourceQuality(puskesmasId),
    queryFn: () => getGdpSourceQuality(puskesmasId),
    placeholderData: keepPreviousData,
    // While the backend recomputes in the background, poll until data lands.
    refetchInterval: (query) => (query.state.data?.computing ? 4000 : false),
  });
}

export function useClearGdpSourceQualityCache() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ puskesmasId }: { puskesmasId?: string }) =>
      clearGdpSourceQualityCache(puskesmasId),
    onSuccess: (_, { puskesmasId }) => {
      qc.invalidateQueries({ queryKey: reportKeys.gdpSourceQuality(puskesmasId) });
    },
  });
}
