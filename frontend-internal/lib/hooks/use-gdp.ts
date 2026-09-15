"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  cancelGdpReport,
  clearGdpDashboardCache,
  exportGdpDashboard,
  exportGdpDiagnose,
  getGdpDashboard,
  getGdpReport,
  listGdpReports,
  retryGdpReport,
  startGdpReport,
  type GdpDashboardQuery,
  type GdpReportListQuery,
} from "@/lib/api/gdp";
import type {
  GdpReportCreateInput,
  GdpReportJob,
  Page,
} from "@/lib/api/types";

export const gdpKeys = {
  all: ["gdp-report"] as const,
  jobLists: () => [...gdpKeys.all, "job-list"] as const,
  jobList: (q: GdpReportListQuery) => [...gdpKeys.jobLists(), q] as const,
  jobDetail: (jobId: string) => [...gdpKeys.all, "job-detail", jobId] as const,
  dashboards: () => [...gdpKeys.all, "dashboard"] as const,
  dashboard: (q: GdpDashboardQuery) => [...gdpKeys.dashboards(), q] as const,
};

export function useGdpReportList(q: GdpReportListQuery, enabled = true) {
  return useQuery({
    queryKey: gdpKeys.jobList(q),
    queryFn: () => listGdpReports(q),
    enabled,
    placeholderData: keepPreviousData,
    refetchOnMount: "always",
  });
}

export function useGdpReport(jobId: string | undefined) {
  return useQuery({
    queryKey: jobId
      ? gdpKeys.jobDetail(jobId)
      : ["gdp-report", "job-detail", "noop"],
    queryFn: () => getGdpReport(jobId!),
    enabled: !!jobId,
  });
}

export function useStartGdpReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: GdpReportCreateInput) => startGdpReport(input),
    onSuccess: (job) => {
      qc.setQueryData(gdpKeys.jobDetail(job.id), job);
      qc.setQueriesData<Page<GdpReportJob>>(
        { queryKey: gdpKeys.jobLists() },
        (old) =>
          old
            ? { ...old, items: [job, ...old.items], total: old.total + 1 }
            : old,
      );
    },
  });
}

export function useRetryGdpReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => retryGdpReport(jobId),
    onSuccess: (job) => {
      qc.setQueryData(gdpKeys.jobDetail(job.id), job);
      qc.setQueriesData<Page<GdpReportJob>>(
        { queryKey: gdpKeys.jobLists() },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((j) => (j.id === job.id ? job : j)),
              }
            : old,
      );
    },
  });
}

export function useCancelGdpReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => cancelGdpReport(jobId),
    onSuccess: (job) => {
      qc.setQueryData(gdpKeys.jobDetail(job.id), job);
      qc.setQueriesData<Page<GdpReportJob>>(
        { queryKey: gdpKeys.jobLists() },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((j) => (j.id === job.id ? job : j)),
              }
            : old,
      );
    },
  });
}

export function useGdpDashboard(q: GdpDashboardQuery, enabled = true) {
  return useQuery({
    queryKey: gdpKeys.dashboard(q),
    queryFn: () => getGdpDashboard(q),
    enabled,
    // Keep previous data only for page/search changes WITHIN the same
    // puskesmas+year+ckg scope (smooth pagination). On a puskesmas/year switch
    // OR a CKG-filter toggle, drop it so the page shows the loading state
    // instead of the previous (stale) rows.
    placeholderData: (prev, prevQuery) => {
      const prevQ = prevQuery?.queryKey?.[2] as GdpDashboardQuery | undefined;
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

export function useClearGdpDashboardCache() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      puskesmasId,
      year,
    }: {
      puskesmasId: string;
      year: number;
    }) => clearGdpDashboardCache(puskesmasId, year),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: gdpKeys.dashboards() });
    },
  });
}

export function useExportGdpDashboard() {
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
      const blob = await exportGdpDashboard(puskesmasId, year, ckgOnly);
      // Trigger a browser download from the blob (auth header is on the
      // axios request, so a plain anchor href can't be used).
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

export function useExportGdpDiagnose() {
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
      const blob = await exportGdpDiagnose(puskesmasId, year, ckgOnly);
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
