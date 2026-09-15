"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  cancelSyncJob,
  getSyncJob,
  getSyncJobLog,
  listSyncJobs,
  startCreateAsik,
  startSyncAsik,
  type SyncJobListQuery,
} from "@/lib/api/sync";
import type { Page, SyncJob } from "@/lib/api/types";

export const syncKeys = {
  all: ["sync"] as const,
  lists: () => [...syncKeys.all, "list"] as const,
  list: (q: SyncJobListQuery) => [...syncKeys.lists(), q] as const,
  detail: (jobId: string) => [...syncKeys.all, "detail", jobId] as const,
  log: (jobId: string, tail: number) =>
    [...syncKeys.all, "log", jobId, tail] as const,
};

export function useSyncJobLog(
  jobId: string | undefined,
  enabled = true,
  tail = 500,
) {
  return useQuery({
    queryKey: jobId ? syncKeys.log(jobId, tail) : ["sync", "log", "noop"],
    queryFn: () => getSyncJobLog(jobId!, tail),
    enabled: !!jobId && enabled,
    staleTime: Infinity,
  });
}

export function useSyncJobList(q: SyncJobListQuery, enabled = true) {
  return useQuery({
    queryKey: syncKeys.list(q),
    queryFn: () => listSyncJobs(q),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useSyncJob(jobId: string | undefined) {
  return useQuery({
    queryKey: jobId ? syncKeys.detail(jobId) : ["sync", "detail", "noop"],
    queryFn: () => getSyncJob(jobId!),
    enabled: !!jobId,
  });
}

export function useStartSyncAsik() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ patientId, headless = true }: { patientId: string; headless?: boolean }) =>
      startSyncAsik(patientId, headless),
    onSuccess: (job) => {
      qc.setQueryData(syncKeys.detail(job.id), job);
      qc.setQueriesData<Page<SyncJob>>(
        { queryKey: syncKeys.lists() },
        (old) =>
          old
            ? { ...old, items: [job, ...old.items], total: old.total + 1 }
            : old,
      );
    },
  });
}

export function useStartCreateAsik() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ patientId, headless = true }: { patientId: string; headless?: boolean }) =>
      startCreateAsik(patientId, headless),
    onSuccess: (job) => {
      qc.setQueryData(syncKeys.detail(job.id), job);
      qc.setQueriesData<Page<SyncJob>>(
        { queryKey: syncKeys.lists() },
        (old) =>
          old
            ? { ...old, items: [job, ...old.items], total: old.total + 1 }
            : old,
      );
    },
  });
}

export function useCancelSyncJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => cancelSyncJob(jobId),
    onSuccess: (job) => {
      qc.setQueryData(syncKeys.detail(job.id), job);
      qc.setQueriesData<Page<SyncJob>>(
        { queryKey: syncKeys.lists() },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((j) => (j.id === job.id ? job : j)),
              }
            : old,
      );
    },
  });
}
