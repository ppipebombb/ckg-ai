import { z } from "zod";
import { http } from "@/lib/api/client";
import { WarmProgressSchema } from "@/lib/api/warm-progress";
import { BayiRegistryRow, type BayiSheet } from "./types";

// ── Registri Bayi Kuning ────────────────────────────────────────────────────
export const BayiRegistryResponseSchema = z.object({
  items: z.array(BayiRegistryRow),
  total: z.number().int(), // rows in the SELECTED sheet
  // Band counts over the whole registry (header context).
  ikterus: z.number().int().default(0),
  ikterus_berat: z.number().int().default(0),
  pjbk: z.number().int().default(0),
  page: z.number().int(),
  size: z.number().int(),
  pages: z.number().int(),
  cache_hit: z.boolean(),
  computed_at: z.string().nullable(),
  computing: z.boolean().default(false),
  progress: WarmProgressSchema.nullable().default(null),
});
export type BayiRegistryResponse = z.infer<typeof BayiRegistryResponseSchema>;

export type BayiRegistryQuery = {
  puskesmas_id: string;
  year: number;
  sheet: BayiSheet;
  q?: string;
  page: number;
  size: number;
};

export async function getBayiRegistry(
  q: BayiRegistryQuery,
): Promise<BayiRegistryResponse> {
  const { data } = await http.get(`/bayi-reports/registry`, { params: q });
  return BayiRegistryResponseSchema.parse(data);
}

export async function clearBayiRegistryCache(
  puskesmas_id: string,
  year: number,
): Promise<void> {
  await http.delete(`/bayi-reports/registry/cache`, {
    params: { puskesmas_id, year },
  });
}

export async function exportBayiRegistry(
  puskesmas_id: string,
  year: number,
  sheet: BayiSheet,
): Promise<Blob> {
  const { data } = await http.get(`/bayi-reports/registry/export`, {
    params: { puskesmas_id, year, sheet },
    responseType: "blob",
  });
  return data as Blob;
}
