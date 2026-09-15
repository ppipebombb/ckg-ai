import { z } from "zod";
import { http } from "./client";
import { HipertensiReportRow } from "./types";

export const HipertensiDashboardResponseSchema = z.object({
  items: z.array(HipertensiReportRow),
  total: z.number().int(),
  page: z.number().int(),
  size: z.number().int(),
  pages: z.number().int(),
  cache_hit: z.boolean(),
  computed_at: z.string().nullable(),
  computing: z.boolean().default(false),
});
export type HipertensiDashboardResponse = z.infer<
  typeof HipertensiDashboardResponseSchema
>;

export type HipertensiDashboardQuery = {
  puskesmas_id: string;
  year: number;
  q?: string;
  ckg_only?: boolean;
  page: number;
  size: number;
};

export async function getHipertensiDashboard(
  q: HipertensiDashboardQuery,
): Promise<HipertensiDashboardResponse> {
  const { data } = await http.get(`/hipertensi-reports/dashboard`, {
    params: q,
  });
  return HipertensiDashboardResponseSchema.parse(data);
}

export async function clearHipertensiDashboardCache(
  puskesmas_id: string,
  year: number,
): Promise<void> {
  await http.delete(`/hipertensi-reports/dashboard/cache`, {
    params: { puskesmas_id, year },
  });
}

export async function exportHipertensiDashboard(
  puskesmas_id: string,
  year: number,
  ckg_only?: boolean,
): Promise<Blob> {
  const { data } = await http.get(`/hipertensi-reports/dashboard/export`, {
    params: { puskesmas_id, year, ckg_only: ckg_only || undefined },
    responseType: "blob",
  });
  return data as Blob;
}

export async function exportHipertensiDiagnose(
  puskesmas_id: string,
  year: number,
  ckg_only?: boolean,
): Promise<Blob> {
  const { data } = await http.get(
    `/hipertensi-reports/dashboard/diagnose-export`,
    {
      params: { puskesmas_id, year, ckg_only: ckg_only || undefined },
      responseType: "blob",
    },
  );
  return data as Blob;
}
