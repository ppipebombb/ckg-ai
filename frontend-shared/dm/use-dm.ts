"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clearDmRegistryCache,
  exportDmRegistry,
  getDmRegistry,
  type DmRegistryQuery,
} from "./api";

// Registry slice of the DM keys. App-local hooks (e.g. a dashboard summary
// card) derive their own keys off `dmKeys.all`.
export const dmKeys = {
  all: ["dm-report"] as const,
  registries: () => [...dmKeys.all, "registry"] as const,
  registry: (q: DmRegistryQuery) => [...dmKeys.registries(), q] as const,
};

export function useDmRegistry(q: DmRegistryQuery, enabled = true) {
  return useQuery({
    queryKey: dmKeys.registry(q),
    queryFn: () => getDmRegistry(q),
    enabled,
    // Keep previous data for page/search changes WITHIN the same puskesmas+year
    // scope (smooth pagination); drop it on a puskesmas/year switch.
    placeholderData: (prev, prevQuery) => {
      const prevQ = prevQuery?.queryKey?.[2] as DmRegistryQuery | undefined;
      const sameScope =
        prevQ?.puskesmas_id === q.puskesmas_id && prevQ?.year === q.year;
      return sameScope ? prev : undefined;
    },
    refetchInterval: (query) => (query.state.data?.computing ? 4000 : false),
  });
}

export function useClearDmRegistryCache() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      puskesmasId,
      year,
    }: {
      puskesmasId: string;
      year: number;
    }) => clearDmRegistryCache(puskesmasId, year),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: dmKeys.registries() });
    },
  });
}

export function useExportDmRegistry() {
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
      const blob = await exportDmRegistry(puskesmasId, year);
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
