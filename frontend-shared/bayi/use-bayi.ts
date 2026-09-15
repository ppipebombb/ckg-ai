"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clearBayiRegistryCache,
  exportBayiRegistry,
  getBayiRegistry,
  type BayiRegistryQuery,
} from "./api";
import type { BayiSheet } from "./types";

export const bayiKeys = {
  all: ["bayi-report"] as const,
  registries: () => [...bayiKeys.all, "registry"] as const,
  registry: (q: BayiRegistryQuery) => [...bayiKeys.registries(), q] as const,
};

export function useBayiRegistry(q: BayiRegistryQuery, enabled = true) {
  return useQuery({
    queryKey: bayiKeys.registry(q),
    queryFn: () => getBayiRegistry(q),
    enabled,
    // Keep previous data for page/search/sheet changes WITHIN the same
    // puskesmas+year scope; drop it on a puskesmas/year switch.
    placeholderData: (prev, prevQuery) => {
      const prevQ = prevQuery?.queryKey?.[2] as BayiRegistryQuery | undefined;
      const sameScope =
        prevQ?.puskesmas_id === q.puskesmas_id && prevQ?.year === q.year;
      return sameScope ? prev : undefined;
    },
    refetchInterval: (query) => (query.state.data?.computing ? 4000 : false),
  });
}

export function useClearBayiRegistryCache() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ puskesmasId, year }: { puskesmasId: string; year: number }) =>
      clearBayiRegistryCache(puskesmasId, year),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: bayiKeys.registries() });
    },
  });
}

export function useExportBayiRegistry() {
  return useMutation({
    mutationFn: async ({
      puskesmasId,
      year,
      sheet,
      filename,
    }: {
      puskesmasId: string;
      year: number;
      sheet: BayiSheet;
      filename: string;
    }) => {
      const blob = await exportBayiRegistry(puskesmasId, year, sheet);
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
