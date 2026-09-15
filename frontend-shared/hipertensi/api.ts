import { z } from "zod";
import { http } from "@/lib/api/client";
import { WarmProgressSchema } from "@/lib/api/warm-progress";
import { HipertensiGapRow, HipertensiRegistryRow } from "./types";

// ── Registri Hipertensi (V8juni2026) ───────────────────────────────────────
export const HipertensiRegistryResponseSchema = z.object({
  items: z.array(HipertensiRegistryRow),
  total: z.number().int(),
  total_hipertensi: z.number().int().default(0),
  total_pre_hipertensi: z.number().int().default(0),
  page: z.number().int(),
  size: z.number().int(),
  pages: z.number().int(),
  cache_hit: z.boolean(),
  computed_at: z.string().nullable(),
  computing: z.boolean().default(false),
  progress: WarmProgressSchema.nullable().default(null),
});
export type HipertensiRegistryResponse = z.infer<
  typeof HipertensiRegistryResponseSchema
>;

export type HipertensiRegistryQuery = {
  puskesmas_id: string;
  year: number;
  q?: string;
  page: number;
  size: number;
};

export async function getHipertensiRegistry(
  q: HipertensiRegistryQuery,
): Promise<HipertensiRegistryResponse> {
  const { data } = await http.get(`/hipertensi-reports/registry`, { params: q });
  return HipertensiRegistryResponseSchema.parse(data);
}

export async function clearHipertensiRegistryCache(
  puskesmas_id: string,
  year: number,
): Promise<void> {
  await http.delete(`/hipertensi-reports/registry/cache`, {
    params: { puskesmas_id, year },
  });
}

export async function exportHipertensiRegistry(
  puskesmas_id: string,
  year: number,
): Promise<Blob> {
  const { data } = await http.get(`/hipertensi-reports/registry/export`, {
    params: { puskesmas_id, year },
    responseType: "blob",
  });
  return data as Blob;
}

// ── Gap Tatalaksana (drill-down behind the Tertatalaksana chart) ────────────
export const HipertensiGapResponseSchema = z.object({
  items: z.array(HipertensiGapRow),
  total: z.number().int(),
  page: z.number().int(),
  size: z.number().int(),
  pages: z.number().int(),
  cache_hit: z.boolean(),
  computed_at: z.string().nullable(),
  computing: z.boolean().default(false),
  progress: WarmProgressSchema.nullable().default(null),
});
export type HipertensiGapResponse = z.infer<typeof HipertensiGapResponseSchema>;

export type HipertensiGapQuery = {
  puskesmas_id: string;
  /** Year the patient ENTERED the registry. Omitted = every year. */
  year?: number;
  q?: string;
  page: number;
  size: number;
};

export async function getHipertensiGap(
  q: HipertensiGapQuery,
): Promise<HipertensiGapResponse> {
  const { data } = await http.get(`/hipertensi-reports/charts/gap`, { params: q });
  return HipertensiGapResponseSchema.parse(data);
}

export async function exportHipertensiGap(
  puskesmas_id: string,
  year: number | undefined,
  q: string | undefined,
): Promise<Blob> {
  const { data } = await http.get(`/hipertensi-reports/charts/gap/export`, {
    params: { puskesmas_id, year, q },
    responseType: "blob",
  });
  return data as Blob;
}
