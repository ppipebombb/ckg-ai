"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  cancelScrapeJob,
  getScrapeJob,
  getScrapeJobLog,
  listScrapeJobs,
  startPatientScrape,
  startScrape,
  type ScrapeJobListQuery,
} from "@/lib/api/scrape";
import type {
  Page,
  ScrapeJob,
  ScrapeKind,
  ScrapeStartInput,
} from "@/lib/api/types";

export const scrapeKeys = {
  all: ["scrape"] as const,
  lists: () => [...scrapeKeys.all, "list"] as const,
  list: (q: ScrapeJobListQuery) => [...scrapeKeys.lists(), q] as const,
  detail: (jobId: string) => [...scrapeKeys.all, "detail", jobId] as const,
  log: (jobId: string, tail: number) =>
    [...scrapeKeys.all, "log", jobId, tail] as const,
};

export function useScrapeJobLog(
  jobId: string | undefined,
  enabled = true,
  tail = 500,
) {
  return useQuery({
    queryKey: jobId ? scrapeKeys.log(jobId, tail) : ["scrape", "log", "noop"],
    queryFn: () => getScrapeJobLog(jobId!, tail),
    enabled: !!jobId && enabled,
    staleTime: Infinity,
  });
}

export function useScrapeJobList(q: ScrapeJobListQuery, enabled = true) {
  return useQuery({
    queryKey: scrapeKeys.list(q),
    queryFn: () => listScrapeJobs(q),
    enabled,
    placeholderData: keepPreviousData,
    refetchOnMount: "always",
  });
}

export function useScrapeJob(jobId: string | undefined) {
  return useQuery({
    queryKey: jobId ? scrapeKeys.detail(jobId) : ["scrape", "detail", "noop"],
    queryFn: () => getScrapeJob(jobId!),
    enabled: !!jobId,
  });
}

export function useStartScrape(puskesmasId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      kind,
      input,
    }: {
      kind: ScrapeKind;
      input: ScrapeStartInput;
    }) => startScrape(puskesmasId, kind, input),
    onSuccess: (job) => {
      qc.setQueryData(scrapeKeys.detail(job.id), job);
      qc.setQueriesData<Page<ScrapeJob>>(
        { queryKey: scrapeKeys.lists() },
        (old) =>
          old
            ? { ...old, items: [job, ...old.items], total: old.total + 1 }
            : old,
      );
    },
  });
}

export function useStartPatientScrape(patientId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, headless = true }: { kind: ScrapeKind; headless?: boolean }) =>
      startPatientScrape(patientId, kind, headless),
    onSuccess: (job) => {
      qc.setQueryData(scrapeKeys.detail(job.id), job);
      qc.setQueriesData<Page<ScrapeJob>>(
        { queryKey: scrapeKeys.lists() },
        (old) =>
          old
            ? { ...old, items: [job, ...old.items], total: old.total + 1 }
            : old,
      );
    },
  });
}

export function useCancelScrapeJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => cancelScrapeJob(jobId),
    onSuccess: (job) => {
      qc.setQueryData(scrapeKeys.detail(job.id), job);
      qc.setQueriesData<Page<ScrapeJob>>(
        { queryKey: scrapeKeys.lists() },
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
