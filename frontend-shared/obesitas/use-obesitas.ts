"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clearObesitasRegistryCache,
  exportObesitasRegistry,
  getObesitasRegistry,
  type ObesitasRegistryQuery,
} from "./api";

// Registry slice of the Obesitas keys. App-local hooks (e.g. a dashboard
// summary card) derive their own keys off `obesitasKeys.all`.
export const obesitasKeys = {
  all: ["obesitas-report"] as const,
  registries: () => [...obesitasKeys.all, "registry"] as const,
  registry: (q: ObesitasRegistryQuery) =>
    [...obesitasKeys.registries(), q] as const,
};

export function useObesitasRegistry(q: ObesitasRegistryQuery, enabled = true) {
  return useQuery({
    queryKey: obesitasKeys.registry(q),
    queryFn: () => getObesitasRegistry(q),
    enabled,
    // Keep previous data for page/search changes WITHIN the same puskesmas+year
    // scope (smooth pagination); drop it on a puskesmas/year switch.
    placeholderData: (prev, prevQuery) => {
      const prevQ = prevQuery?.queryKey?.[2] as ObesitasRegistryQuery | undefined;
      const sameScope =
        prevQ?.puskesmas_id === q.puskesmas_id && prevQ?.year === q.year;
      return sameScope ? prev : undefined;
    },
    refetchInterval: (query) => (query.state.data?.computing ? 4000 : false),
  });
}

export function useClearObesitasRegistryCache() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      puskesmasId,
      year,
    }: {
      puskesmasId: string;
      year: number;
    }) => clearObesitasRegistryCache(puskesmasId, year),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: obesitasKeys.registries() });
    },
  });
}

export function useExportObesitasRegistry() {
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
      const blob = await exportObesitasRegistry(puskesmasId, year);
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
