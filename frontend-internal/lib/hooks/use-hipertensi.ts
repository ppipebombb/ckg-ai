"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { hipertensiKeys } from "@shared/hipertensi/use-hipertensi";
import {
  clearHipertensiDashboardCache,
  exportHipertensiDashboard,
  exportHipertensiDiagnose,
  getHipertensiDashboard,
  type HipertensiDashboardQuery,
} from "@/lib/api/hipertensi";

// Internal-only Full Review Diagnose keys. The registry slice lives in
// @shared/hipertensi; these derive off the shared root so both share a cache
// namespace.
export const hipertensiDashboardKeys = {
  dashboards: () => [...hipertensiKeys.all, "dashboard"] as const,
  dashboard: (q: HipertensiDashboardQuery) =>
    [...hipertensiDashboardKeys.dashboards(), q] as const,
};

export function useHipertensiDashboard(
  q: HipertensiDashboardQuery,
  enabled = true,
) {
  return useQuery({
    queryKey: hipertensiDashboardKeys.dashboard(q),
    queryFn: () => getHipertensiDashboard(q),
    enabled,
    // Keep previous data only for page/search changes WITHIN the same
    // puskesmas+year+ckg scope (smooth pagination). On a puskesmas/year switch
    // OR a CKG-filter toggle, drop it so the page shows the loading state.
    placeholderData: (prev, prevQuery) => {
      const prevQ = prevQuery?.queryKey?.[2] as
        | HipertensiDashboardQuery
        | undefined;
      const sameScope =
        prevQ?.puskesmas_id === q.puskesmas_id &&
        prevQ?.year === q.year &&
        prevQ?.ckg_only === q.ckg_only;
      return sameScope ? prev : undefined;
    },
    // While the backend recomputes in the background, poll until data lands.
    refetchInterval: (query) => (query.state.data?.computing ? 4000 : false),
  });
}

export function useClearHipertensiDashboardCache() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      puskesmasId,
      year,
    }: {
      puskesmasId: string;
      year: number;
    }) => clearHipertensiDashboardCache(puskesmasId, year),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: hipertensiDashboardKeys.dashboards() });
    },
  });
}

export function useExportHipertensiDashboard() {
  return useMutation({
    mutationFn: async ({
      puskesmasId,
      year,
      ckgOnly,
      filename,
    }: {
      puskesmasId: string;
      year: number;
      ckgOnly?: boolean;
      filename: string;
    }) => {
      const blob = await exportHipertensiDashboard(puskesmasId, year, ckgOnly);
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

export function useExportHipertensiDiagnose() {
  return useMutation({
    mutationFn: async ({
      puskesmasId,
      year,
      ckgOnly,
      filename,
    }: {
      puskesmasId: string;
      year: number;
      ckgOnly?: boolean;
      filename: string;
    }) => {
      const blob = await exportHipertensiDiagnose(puskesmasId, year, ckgOnly);
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
