import { z } from "zod";
import { http } from "@/lib/api/client";
import { WarmProgressSchema } from "@/lib/api/warm-progress";
import { LipidRegistryRow } from "./types";

// ── Registri Dislipidemia ──────────────────────────────────────────────────
export const LipidRegistryResponseSchema = z.object({
  items: z.array(LipidRegistryRow),
  total: z.number().int(),
  // Per-analyte abnormal counts. These OVERLAP and do NOT sum to `total` — the
  // syarat is an OR of four independent thresholds and one patient routinely
  // breaches several. Render them as four independent counts, never as a
  // stacked bar or an "X of total" split.
  kol_total_tinggi: z.number().int().default(0),
  ldl_tinggi: z.number().int().default(0),
  hdl_rendah: z.number().int().default(0),
  trigliserida_tinggi: z.number().int().default(0),
  page: z.number().int(),
  size: z.number().int(),
  pages: z.number().int(),
  cache_hit: z.boolean(),
  computed_at: z.string().nullable(),
  computing: z.boolean().default(false),
  progress: WarmProgressSchema.nullable().default(null),
});
export type LipidRegistryResponse = z.infer<typeof LipidRegistryResponseSchema>;

export type LipidRegistryQuery = {
  puskesmas_id: string;
  year: number;
  q?: string;
  page: number;
  size: number;
};

export async function getLipidRegistry(
  q: LipidRegistryQuery,
): Promise<LipidRegistryResponse> {
  const { data } = await http.get(`/lipid-reports/registry`, { params: q });
  return LipidRegistryResponseSchema.parse(data);
}

export async function clearLipidRegistryCache(
  puskesmas_id: string,
  year: number,
): Promise<void> {
  await http.delete(`/lipid-reports/registry/cache`, {
    params: { puskesmas_id, year },
  });
}

export async function exportLipidRegistry(
  puskesmas_id: string,
  year: number,
): Promise<Blob> {
  const { data } = await http.get(`/lipid-reports/registry/export`, {
    params: { puskesmas_id, year },
    responseType: "blob",
  });
  return data as Blob;
}
