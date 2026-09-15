"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createSchoolCronConfig,
  deleteSchoolCronConfig,
  getSchoolCronConfig,
  runSchoolCronNow,
  updateSchoolCronConfig,
} from "@/lib/api/school-cron";
import type {
  Page,
  ScrapeJob,
  SchoolCronConfig,
  SchoolCronConfigCreateInput,
  SchoolCronConfigUpdateInput,
} from "@/lib/api/types";
import { scrapeKeys } from "./use-scrape";

export const schoolCronKeys = {
  all: ["school-cron-config"] as const,
  detail: (puskesmasId: string) =>
    [...schoolCronKeys.all, "detail", puskesmasId] as const,
};

export function useSchoolCronConfig(puskesmasId: string | undefined) {
  return useQuery({
    queryKey: puskesmasId
      ? schoolCronKeys.detail(puskesmasId)
      : ["school-cron-config", "detail", "noop"],
    queryFn: () => getSchoolCronConfig(puskesmasId!),
    enabled: !!puskesmasId,
  });
}

export function useCreateSchoolCronConfig(puskesmasId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: SchoolCronConfigCreateInput) =>
      createSchoolCronConfig(puskesmasId, input),
    onSuccess: (cfg) => {
      qc.setQueryData<SchoolCronConfig | null>(
        schoolCronKeys.detail(puskesmasId),
        cfg,
      );
    },
  });
}

export function useUpdateSchoolCronConfig(puskesmasId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: SchoolCronConfigUpdateInput) =>
      updateSchoolCronConfig(puskesmasId, input),
    onSuccess: (cfg) => {
      qc.setQueryData<SchoolCronConfig | null>(
        schoolCronKeys.detail(puskesmasId),
        cfg,
      );
    },
  });
}

export function useDeleteSchoolCronConfig(puskesmasId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => deleteSchoolCronConfig(puskesmasId),
    onSuccess: () => {
      qc.setQueryData<SchoolCronConfig | null>(
        schoolCronKeys.detail(puskesmasId),
        null,
      );
    },
  });
}

export function useRunSchoolCronNow(puskesmasId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => runSchoolCronNow(puskesmasId),
    onSuccess: (job) => {
      // run-now creates an asik_sekolah scrape job — patch the scrape lists.
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
