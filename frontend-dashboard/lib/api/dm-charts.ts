import { z } from "zod";
import { http } from "./client";
import { WarmProgressSchema } from "./warm-progress";

// Bar-1 population is "DM murni" (glukosa mencapai ambang diagnosis: GDP>=126 /
// GD2PP>=200 / GDS-2>=200), NOT registry membership (which also admits
// Prediabetes + riwayat-gated-but-normal patients) — see backend
// dm_charts_scan._dm_murni. The 2026 Ya/Tidak split uses the same diagnosis
// threshold (symmetric with the hipertensi charts).
export const DmKohort2TahunSchema = z.object({
  dm_2025: z.number().int().default(0),
  diperiksa_2026: z.number().int().default(0),
  dm_2026_tinggi: z.number().int().default(0),
  dm_2026_terkendali: z.number().int().default(0),
  // Each split from dm_2026_tinggi / dm_2026_terkendali, not a total.
  tinggi_diobati: z.number().int().default(0),
  tinggi_tidak_diobati: z.number().int().default(0),
  terkendali_diobati: z.number().int().default(0),
  terkendali_tidak_diobati: z.number().int().default(0),
});

export const DmCharts2026Schema = z.object({
  dm_2026: z.number().int().default(0),
  pasien_baru: z.number().int().default(0),
  sudah_dm: z.number().int().default(0),
  // Each split from pasien_baru / sudah_dm, not a total.
  baru_diobati: z.number().int().default(0),
  baru_tidak_diobati: z.number().int().default(0),
  sudah_diobati: z.number().int().default(0),
  sudah_tidak_diobati: z.number().int().default(0),
});

export const DmChartsSchema = z.object({
  kohort_2tahun: DmKohort2TahunSchema,
  dm_2026: DmCharts2026Schema,
  cache_hit: z.boolean(),
  computed_at: z.string().nullable(),
  computing: z.boolean().default(false),
  progress: WarmProgressSchema.nullable().default(null),
});
export type DmCharts = z.infer<typeof DmChartsSchema>;

export async function getDmCharts(puskesmas_id: string): Promise<DmCharts> {
  const { data } = await http.get(`/dm-reports/charts`, {
    params: { puskesmas_id },
  });
  return DmChartsSchema.parse(data);
}
