import { z } from "zod";
import { http } from "./client";

// Per-puskesmas aggregate counts for the dashboard 'Status per Puskesmas' card.
export const HipertensiRegistrySummarySchema = z.object({
  total: z.number().int(),
  total_hipertensi: z.number().int().default(0),
  total_pre_hipertensi: z.number().int().default(0),
  riwayat_ht_ya: z.number().int(),
  dalam_pengobatan: z.number().int(),
  cache_hit: z.boolean(),
  computed_at: z.string().nullable(),
  computing: z.boolean().default(false),
});
export type HipertensiRegistrySummary = z.infer<
  typeof HipertensiRegistrySummarySchema
>;

export async function getHipertensiRegistrySummary(
  puskesmas_id: string,
  year: number,
): Promise<HipertensiRegistrySummary> {
  const { data } = await http.get(`/hipertensi-reports/registry/summary`, {
    params: { puskesmas_id, year },
  });
  return HipertensiRegistrySummarySchema.parse(data);
}
