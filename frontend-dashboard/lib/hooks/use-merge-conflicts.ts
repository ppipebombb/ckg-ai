"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clearMergeConflictCache,
  getMergeConflictSummary,
  type MergeConflictSummaryQuery,
} from "@/lib/api/merge-conflicts";

export const mergeConflictsKeys = {
  all: ["merge-conflicts"] as const,
  summaries: () => [...mergeConflictsKeys.all, "summary"] as const,
  summary: (q: MergeConflictSummaryQuery) =>
    [...mergeConflictsKeys.summaries(), q] as const,
};

export function useMergeConflictSummary(q: MergeConflictSummaryQuery) {
  return useQuery({
    queryKey: mergeConflictsKeys.summary(q),
    queryFn: () => getMergeConflictSummary(q),
    // Keep previous rows only while the puskesmas scope is unchanged (smooth
    // `top` changes). On a puskesmas switch drop the placeholder so the page
    // shows the loading state instead of the prior scope's stale rows.
    placeholderData: (prev, prevQuery) => {
      const prevQ = prevQuery?.queryKey?.[2] as
        | MergeConflictSummaryQuery
        | undefined;
      return prevQ?.puskesmas_id === q.puskesmas_id ? prev : undefined;
    },
    // While the backend recomputes in the background, poll until data lands.
    refetchInterval: (query) => (query.state.data?.computing ? 4000 : false),
  });
}

export function useClearMergeConflictCache() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (puskesmasId?: string) => clearMergeConflictCache(puskesmasId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: mergeConflictsKeys.summaries() });
    },
  });
}
