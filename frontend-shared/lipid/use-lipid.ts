"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clearLipidRegistryCache,
  exportLipidRegistry,
  getLipidRegistry,
  type LipidRegistryQuery,
} from "./api";

// Registry slice of the Dislipidemia keys. App-local hooks (e.g. a dashboard
// summary card) derive their own keys off `lipidKeys.all`.
export const lipidKeys = {
  all: ["lipid-report"] as const,
  registries: () => [...lipidKeys.all, "registry"] as const,
  registry: (q: LipidRegistryQuery) => [...lipidKeys.registries(), q] as const,
};

export function useLipidRegistry(q: LipidRegistryQuery, enabled = true) {
  return useQuery({
    queryKey: lipidKeys.registry(q),
    queryFn: () => getLipidRegistry(q),
    enabled,
    // Keep previous data for page/search changes WITHIN the same puskesmas+year
    // scope (smooth pagination); drop it on a puskesmas/year switch.
    placeholderData: (prev, prevQuery) => {
      const prevQ = prevQuery?.queryKey?.[2] as LipidRegistryQuery | undefined;
      const sameScope =
        prevQ?.puskesmas_id === q.puskesmas_id && prevQ?.year === q.year;
      return sameScope ? prev : undefined;
    },
    refetchInterval: (query) => (query.state.data?.computing ? 4000 : false),
  });
}

export function useClearLipidRegistryCache() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      puskesmasId,
      year,
    }: {
      puskesmasId: string;
      year: number;
    }) => clearLipidRegistryCache(puskesmasId, year),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: lipidKeys.registries() });
    },
  });
}

export function useExportLipidRegistry() {
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
      const blob = await exportLipidRegistry(puskesmasId, year);
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
