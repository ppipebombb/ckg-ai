"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clearHipertensiRegistryCache,
  exportHipertensiGap,
  exportHipertensiRegistry,
  getHipertensiGap,
  getHipertensiRegistry,
  type HipertensiGapQuery,
  type HipertensiRegistryQuery,
} from "./api";

// Registry slice of the hipertensi keys. App-local hooks (the internal Full
// Review Diagnose dashboard, the dashboard registry-summary card) derive their
// own keys off `hipertensiKeys.all`.
export const hipertensiKeys = {
  all: ["hipertensi-report"] as const,
  registries: () => [...hipertensiKeys.all, "registry"] as const,
  registry: (q: HipertensiRegistryQuery) =>
    [...hipertensiKeys.registries(), q] as const,
  gaps: () => [...hipertensiKeys.all, "gap"] as const,
  gap: (q: HipertensiGapQuery) => [...hipertensiKeys.gaps(), q] as const,
};

export function useHipertensiRegistry(
  q: HipertensiRegistryQuery,
  enabled = true,
) {
  return useQuery({
    queryKey: hipertensiKeys.registry(q),
    queryFn: () => getHipertensiRegistry(q),
    enabled,
    // Keep previous data for page/search changes WITHIN the same puskesmas+year
    // scope (smooth pagination); drop it on a puskesmas/year switch.
    placeholderData: (prev, prevQuery) => {
      const prevQ = prevQuery?.queryKey?.[2] as
        | HipertensiRegistryQuery
        | undefined;
      const sameScope =
        prevQ?.puskesmas_id === q.puskesmas_id && prevQ?.year === q.year;
      return sameScope ? prev : undefined;
    },
    refetchInterval: (query) => (query.state.data?.computing ? 4000 : false),
  });
}

export function useHipertensiGap(q: HipertensiGapQuery, enabled = true) {
  return useQuery({
    queryKey: hipertensiKeys.gap(q),
    queryFn: () => getHipertensiGap(q),
    enabled,
    // Same rule as the registry: keep rows on screen while paging/searching
    // within one puskesmas+year scope, drop them when the scope changes.
    placeholderData: (prev, prevQuery) => {
      const prevQ = prevQuery?.queryKey?.[2] as HipertensiGapQuery | undefined;
      const sameScope =
        prevQ?.puskesmas_id === q.puskesmas_id && prevQ?.year === q.year;
      return sameScope ? prev : undefined;
    },
    refetchInterval: (query) => (query.state.data?.computing ? 4000 : false),
  });
}

export function useExportHipertensiGap() {
  return useMutation({
    mutationFn: async ({
      puskesmasId,
      year,
      q,
      filename,
    }: {
      puskesmasId: string;
      year?: number;
      q?: string;
      filename: string;
    }) => {
      const blob = await exportHipertensiGap(puskesmasId, year, q);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    },
  });
}

export function useClearHipertensiRegistryCache() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      puskesmasId,
      year,
    }: {
      puskesmasId: string;
      year: number;
    }) => clearHipertensiRegistryCache(puskesmasId, year),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: hipertensiKeys.registries() });
    },
  });
}

export function useExportHipertensiRegistry() {
  return useMutation({
    mutationFn: async ({
      puskesmasId,
      year,
      filename,
    }: {
      puskesmasId: string;
      year: number;
      filename: string;
    }) => {
      const blob = await exportHipertensiRegistry(puskesmasId, year);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    },
  });
}
