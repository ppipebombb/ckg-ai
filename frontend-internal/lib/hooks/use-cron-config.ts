"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createCronConfig,
  deleteCronConfig,
  getCronConfig,
  runCronNow,
  updateCronConfig,
} from "@/lib/api/cron";
import type {
  CronConfig,
  CronConfigCreateInput,
  CronConfigUpdateInput,
  CronRun,
  Page,
} from "@/lib/api/types";
import { cronRunKeys } from "./use-cron-runs";

export const cronConfigKeys = {
  all: ["cron-config"] as const,
  detail: (puskesmasId: string) =>
    [...cronConfigKeys.all, "detail", puskesmasId] as const,
};

export function useCronConfig(puskesmasId: string | undefined) {
  return useQuery({
    queryKey: puskesmasId
      ? cronConfigKeys.detail(puskesmasId)
      : ["cron-config", "detail", "noop"],
    queryFn: () => getCronConfig(puskesmasId!),
    enabled: !!puskesmasId,
  });
}

export function useCreateCronConfig(puskesmasId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CronConfigCreateInput) =>
      createCronConfig(puskesmasId, input),
    onSuccess: (cfg) => {
      qc.setQueryData<CronConfig | null>(cronConfigKeys.detail(puskesmasId), cfg);
    },
  });
}

export function useUpdateCronConfig(puskesmasId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CronConfigUpdateInput) =>
      updateCronConfig(puskesmasId, input),
    onSuccess: (cfg) => {
      qc.setQueryData<CronConfig | null>(cronConfigKeys.detail(puskesmasId), cfg);
    },
  });
}

export function useDeleteCronConfig(puskesmasId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => deleteCronConfig(puskesmasId),
    onSuccess: () => {
      qc.setQueryData<CronConfig | null>(cronConfigKeys.detail(puskesmasId), null);
    },
  });
}

export function useRunCronNow(puskesmasId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => runCronNow(puskesmasId),
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
