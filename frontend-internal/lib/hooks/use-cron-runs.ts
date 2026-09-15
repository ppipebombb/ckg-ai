"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  cancelCronRun,
  getCronRun,
  getCronRunSyncSummary,
  listCronRuns,
  retryCronRun,
  type CronRunListQuery,
} from "@/lib/api/cron";
import type { CronRun, Page } from "@/lib/api/types";

export const cronRunKeys = {
  all: ["cron-runs"] as const,
  lists: () => [...cronRunKeys.all, "list"] as const,
  list: (q: CronRunListQuery) => [...cronRunKeys.lists(), q] as const,
  detail: (runId: string) => [...cronRunKeys.all, "detail", runId] as const,
  syncSummary: (runId: string) =>
    [...cronRunKeys.all, "sync-summary", runId] as const,
};

export function useCronRunList(q: CronRunListQuery, enabled = true) {
  return useQuery({
    queryKey: cronRunKeys.list(q),
    queryFn: () => listCronRuns(q),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useCronRun(runId: string | undefined) {
  return useQuery({
    queryKey: runId ? cronRunKeys.detail(runId) : ["cron-runs", "detail", "noop"],
    queryFn: () => getCronRun(runId!),
    enabled: !!runId,
  });
}

/** Per-patient sync progress for a run's SYNC step.
 *
 * `enabled` is passed by the caller so the query only fires for runs whose
 * scope can reach SYNC — a scrape-only run would otherwise fetch a summary that
 * is always empty on every page load. No polling: it refetches when the run's
 * own detail query is invalidated. */
export function useCronRunSyncSummary(
  runId: string | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: runId
      ? cronRunKeys.syncSummary(runId)
      : ["cron-runs", "sync-summary", "noop"],
    queryFn: () => getCronRunSyncSummary(runId!),
    enabled: !!runId && enabled,
  });
}

export function useCancelCronRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => cancelCronRun(runId),
    onSuccess: (run) => {
      qc.setQueryData(cronRunKeys.detail(run.id), run);
      qc.setQueriesData<Page<CronRun>>(
        { queryKey: cronRunKeys.lists() },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((r) => (r.id === run.id ? run : r)),
              }
            : old,
      );
    },
  });
}

export function useRetryCronRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => retryCronRun(runId),
    onSuccess: (run) => {
      qc.setQueryData(cronRunKeys.detail(run.id), run);
      qc.setQueriesData<Page<CronRun>>(
        { queryKey: cronRunKeys.lists() },
        (old) =>
          old
            ? { ...old, items: [run, ...old.items], total: old.total + 1 }
            : old,
      );
    },
  });
}
