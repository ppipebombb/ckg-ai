import { z } from "zod";
import { http } from "./client";
import {
  GdpReportJobOut,
  GdpReportRow,
  PageSchema,
  type GdpReportCreateInput,
  type GdpReportJob,
  type GdpReportStatus,
  type Page,
} from "./types";
import { WarmProgressSchema } from "./warm-progress";

export const GdpDashboardResponseSchema = z.object({
  items: z.array(GdpReportRow),
  total: z.number().int(),
  page: z.number().int(),
  size: z.number().int(),
  pages: z.number().int(),
  cache_hit: z.boolean(),
  computed_at: z.string().nullable(),
  computing: z.boolean().default(false),
  progress: WarmProgressSchema.nullable().default(null),
});
export type GdpDashboardResponse = z.infer<typeof GdpDashboardResponseSchema>;

export async function startGdpReport(
  input: GdpReportCreateInput,
): Promise<GdpReportJob> {
  const { data } = await http.post(`/gdp-reports`, input);
  return GdpReportJobOut.parse(data);
}

export type GdpReportListQuery = {
  page: number;
  size: number;
  puskesmas_id?: string;
  status?: GdpReportStatus;
};

export async function listGdpReports(
  q: GdpReportListQuery,
): Promise<Page<GdpReportJob>> {
  const { data } = await http.get(`/gdp-reports`, { params: q });
  return PageSchema(GdpReportJobOut).parse(data);
}

export async function getGdpReport(jobId: string): Promise<GdpReportJob> {
  const { data } = await http.get(`/gdp-reports/${jobId}`);
  return GdpReportJobOut.parse(data);
}

export async function cancelGdpReport(jobId: string): Promise<GdpReportJob> {
  const { data } = await http.post(`/gdp-reports/${jobId}/cancel`);
  return GdpReportJobOut.parse(data);
}

export async function retryGdpReport(jobId: string): Promise<GdpReportJob> {
  const { data } = await http.post(`/gdp-reports/${jobId}/retry`);
  return GdpReportJobOut.parse(data);
}

export type GdpDashboardQuery = {
  puskesmas_id: string;
  year: number;
  q?: string;
  ckg_only?: boolean;
  page: number;
  size: number;
};

export async function getGdpDashboard(
  q: GdpDashboardQuery,
): Promise<GdpDashboardResponse> {
  const { data } = await http.get(`/gdp-reports/dashboard`, { params: q });
  return GdpDashboardResponseSchema.parse(data);
}

export async function clearGdpDashboardCache(
  puskesmas_id: string,
  year: number,
): Promise<void> {
  await http.delete(`/gdp-reports/dashboard/cache`, {
    params: { puskesmas_id, year },
  });
}

export async function exportGdpDashboard(
  puskesmas_id: string,
  year: number,
  ckg_only?: boolean,
): Promise<Blob> {
  const { data } = await http.get(`/gdp-reports/dashboard/export`, {
    params: { puskesmas_id, year, ckg_only: ckg_only || undefined },
    responseType: "blob",
  });
  return data as Blob;
}

export async function exportGdpDiagnose(
  puskesmas_id: string,
  year: number,
  ckg_only?: boolean,
): Promise<Blob> {
  const { data } = await http.get(`/gdp-reports/dashboard/diagnose-export`, {
    params: { puskesmas_id, year, ckg_only: ckg_only || undefined },
    responseType: "blob",
  });
  return data as Blob;
}
