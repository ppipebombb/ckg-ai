"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  cancelLoopRun,
  getLoopConfig,
  getLoopCoverageSummary,
  getLoopRun,
  getLoopRunLog,
  getLoopSummary,
  listLoopRuns,
  openLoopRunPr,
  reconcileLoopPrs,
  startLoopRun,
  updateLoopConfig,
  type LoopRunListQuery,
} from "@/lib/api/loop";
import type {
  LoopConfig,
  LoopConfigUpdateInput,
  LoopRun,
  LoopRunStartInput,
  Page,
} from "@/lib/api/types";

export const loopKeys = {
  all: ["loop"] as const,
  lists: () => [...loopKeys.all, "list"] as const,
  list: (q: LoopRunListQuery) => [...loopKeys.lists(), q] as const,
  detail: (runId: string) => [...loopKeys.all, "detail", runId] as const,
  log: (runId: string, tail: number) =>
    [...loopKeys.all, "log", runId, tail] as const,
  config: () => [...loopKeys.all, "config"] as const,
  summary: () => [...loopKeys.all, "summary"] as const,
  coverageSummary: () => [...loopKeys.all, "coverage-summary"] as const,
};

export function useLoopSummary(enabled = true) {
  return useQuery({
    queryKey: loopKeys.summary(),
    queryFn: () => getLoopSummary(),
    enabled,
    refetchOnMount: "always",
  });
}

export function useLoopCoverageSummary(enabled = true) {
  return useQuery({
    queryKey: loopKeys.coverageSummary(),
    queryFn: () => getLoopCoverageSummary(),
    enabled,
    staleTime: 60_000,
  });
}

export function useReconcileLoopPrs() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => reconcileLoopPrs(),
    onSuccess: () => {
      // Explicit user refresh: PR statuses changed server-side, so refetch the
      // list and the count (CLAUDE.md §7.1 refresh exception).
      qc.invalidateQueries({ queryKey: loopKeys.lists() });
      qc.invalidateQueries({ queryKey: loopKeys.summary() });
    },
  });
}

export function useLoopConfig(enabled = true) {
  return useQuery({
    queryKey: loopKeys.config(),
    queryFn: () => getLoopConfig(),
    enabled,
    staleTime: Infinity,
  });
}

export function useUpdateLoopConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: LoopConfigUpdateInput) => updateLoopConfig(input),
    onSuccess: (cfg) => {
      qc.setQueryData<LoopConfig>(loopKeys.config(), cfg);
    },
  });
}

export function useLoopRunList(q: LoopRunListQuery, enabled = true) {
  return useQuery({
    queryKey: loopKeys.list(q),
    queryFn: () => listLoopRuns(q),
    enabled,
    placeholderData: keepPreviousData,
    refetchOnMount: "always",
  });
}

export function useLoopRun(runId: string | undefined) {
  return useQuery({
    queryKey: runId ? loopKeys.detail(runId) : ["loop", "detail", "noop"],
    queryFn: () => getLoopRun(runId!),
    enabled: !!runId,
  });
}

export function useLoopRunLog(runId: string | undefined, enabled = true, tail = 300) {
  return useQuery({
    queryKey: runId ? loopKeys.log(runId, tail) : ["loop", "log", "noop"],
    queryFn: () => getLoopRunLog(runId!, tail),
    enabled: !!runId && enabled,
    staleTime: Infinity,
  });
}

export function useStartLoopRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: LoopRunStartInput) => startLoopRun(input),
    onSuccess: (run) => {
      qc.setQueryData(loopKeys.detail(run.id), run);
      qc.setQueriesData<Page<LoopRun>>(
        { queryKey: loopKeys.lists() },
        (old) =>
          old
            ? { ...old, items: [run, ...old.items], total: old.total + 1 }
            : old,
      );
    },
  });
}

export function useCancelLoopRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => cancelLoopRun(runId),
    onSuccess: (run) => {
      qc.setQueryData(loopKeys.detail(run.id), run);
      qc.setQueriesData<Page<LoopRun>>(
        { queryKey: loopKeys.lists() },
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

export function useOpenLoopRunPr() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => openLoopRunPr(runId),
    onSuccess: (run) => {
      qc.setQueryData(loopKeys.detail(run.id), run);
      qc.setQueriesData<Page<LoopRun>>(
        { queryKey: loopKeys.lists() },
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
