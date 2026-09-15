"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  cancelMergeJob,
  getMergeJob,
  getMergeJobLog,
  getMergePreview,
  listMergeJobs,
  startMerge,
  startPatientMerge,
  type MergeJobListQuery,
} from "@/lib/api/merge";
import type { MergeJob, MergeStartInput, Page } from "@/lib/api/types";

export const mergeKeys = {
  all: ["merge"] as const,
  lists: () => [...mergeKeys.all, "list"] as const,
  list: (q: MergeJobListQuery) => [...mergeKeys.lists(), q] as const,
  detail: (jobId: string) => [...mergeKeys.all, "detail", jobId] as const,
  preview: (puskesmasId: string, date: string) =>
    [...mergeKeys.all, "preview", puskesmasId, date] as const,
  log: (jobId: string, tail: number) =>
    [...mergeKeys.all, "log", jobId, tail] as const,
};

export function useMergeJobLog(
  jobId: string | undefined,
  enabled = true,
  tail = 500,
) {
  return useQuery({
    queryKey: jobId ? mergeKeys.log(jobId, tail) : ["merge", "log", "noop"],
    queryFn: () => getMergeJobLog(jobId!, tail),
    enabled: !!jobId && enabled,
    staleTime: Infinity,
  });
}

export function useMergePreview(
  puskesmasId: string | undefined,
  date: string | undefined,
) {
  return useQuery({
    queryKey:
      puskesmasId && date
        ? mergeKeys.preview(puskesmasId, date)
        : ["merge", "preview", "noop"],
    queryFn: () => getMergePreview(puskesmasId!, date!),
    enabled: !!puskesmasId && !!date,
    placeholderData: keepPreviousData,
  });
}

export function useMergeJobList(q: MergeJobListQuery, enabled = true) {
  return useQuery({
    queryKey: mergeKeys.list(q),
    queryFn: () => listMergeJobs(q),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useMergeJob(jobId: string | undefined) {
  return useQuery({
    queryKey: jobId ? mergeKeys.detail(jobId) : ["merge", "detail", "noop"],
    queryFn: () => getMergeJob(jobId!),
    enabled: !!jobId,
  });
}

export function useStartMerge(puskesmasId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: MergeStartInput) => startMerge(puskesmasId, input),
    onSuccess: (jobs) => {
      for (const job of jobs) {
        qc.setQueryData(mergeKeys.detail(job.id), job);
      }
      qc.setQueriesData<Page<MergeJob>>(
        { queryKey: mergeKeys.lists() },
        (old) =>
          old
            ? {
                ...old,
                // Newest first — backend returns range jobs in date order
                // (ascending), so reverse before prepending.
                items: [...[...jobs].reverse(), ...old.items],
                total: old.total + jobs.length,
              }
            : old,
      );
    },
  });
}

export function useStartPatientMerge(patientId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => startPatientMerge(patientId),
    onSuccess: (job) => {
      qc.setQueryData(mergeKeys.detail(job.id), job);
      qc.setQueriesData<Page<MergeJob>>(
        { queryKey: mergeKeys.lists() },
        (old) =>
          old
            ? { ...old, items: [job, ...old.items], total: old.total + 1 }
            : old,
      );
    },
  });
}

export function useCancelMergeJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => cancelMergeJob(jobId),
    onSuccess: (job) => {
      qc.setQueryData(mergeKeys.detail(job.id), job);
      qc.setQueriesData<Page<MergeJob>>(
        { queryKey: mergeKeys.lists() },
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
