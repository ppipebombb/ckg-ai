"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  cancelCronBackfill,
  createCronBackfill,
  getCronBackfill,
  listCronBackfillRuns,
  listCronBackfills,
  type CronBackfillListQuery,
  type CronBackfillRunsQuery,
} from "@/lib/api/cron-backfill";
import type { CronBackfill, Page } from "@/lib/api/types";

export const cronBackfillKeys = {
  all: ["cron-backfills"] as const,
  lists: () => [...cronBackfillKeys.all, "list"] as const,
  list: (q: CronBackfillListQuery) =>
    [...cronBackfillKeys.lists(), q] as const,
  detail: (id: string) => [...cronBackfillKeys.all, "detail", id] as const,
  childRunsAll: () => [...cronBackfillKeys.all, "child-runs"] as const,
  childRuns: (id: string, q: CronBackfillRunsQuery) =>
    [...cronBackfillKeys.childRunsAll(), id, q] as const,
};

export function useCronBackfillList(
  q: CronBackfillListQuery,
  enabled = true,
) {
  return useQuery({
    queryKey: cronBackfillKeys.list(q),
    queryFn: () => listCronBackfills(q),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useCronBackfill(id: string | undefined) {
  return useQuery({
    queryKey: id
      ? cronBackfillKeys.detail(id)
      : ["cron-backfills", "detail", "noop"],
    queryFn: () => getCronBackfill(id!),
    enabled: !!id,
  });
}

export function useCronBackfillChildRuns(
  id: string | undefined,
  q: CronBackfillRunsQuery,
  enabled = true,
) {
  return useQuery({
    queryKey: id
      ? cronBackfillKeys.childRuns(id, q)
      : ["cron-backfills", "child-runs", "noop"],
    queryFn: () => listCronBackfillRuns(id!, q),
    enabled: !!id && enabled,
    placeholderData: keepPreviousData,
  });
}

export function useCreateCronBackfill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createCronBackfill,
    onSuccess: (bf) => {
      qc.setQueryData(cronBackfillKeys.detail(bf.id), bf);
      qc.setQueriesData<Page<CronBackfill>>(
        { queryKey: cronBackfillKeys.lists() },
        (old) =>
          old
            ? { ...old, items: [bf, ...old.items], total: old.total + 1 }
            : old,
      );
    },
  });
}

export function useCancelCronBackfill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => cancelCronBackfill(id),
    onSuccess: (bf) => {
      qc.setQueryData(cronBackfillKeys.detail(bf.id), bf);
      qc.setQueriesData<Page<CronBackfill>>(
        { queryKey: cronBackfillKeys.lists() },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((r) => (r.id === bf.id ? bf : r)),
              }
            : old,
      );
    },
  });
}
