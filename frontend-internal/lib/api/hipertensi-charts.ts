import { z } from "zod";
import { http } from "./client";
import { WarmProgressSchema } from "./warm-progress";

// One month on the cumulative axis. Invariant:
// tercapai + tidak_tercapai + tidak_berkunjung === treated_cumulative.
export const ChartsMonthPointSchema = z.object({
  ym: z.string(), // "YYYY-MM"
  registered_cumulative: z.number().int(),
  treated_cumulative: z.number().int(),
  tercapai: z.number().int(),
  tidak_tercapai: z.number().int(),
  tidak_berkunjung: z.number().int(),
});
export type ChartsMonthPoint = z.infer<typeof ChartsMonthPointSchema>;

export const CascadeSchema = z.object({
  registered: z.number().int().default(0),
  treated: z.number().int().default(0),
  controlled: z.number().int().default(0),
});
export const ProporsiSchema = z.object({
  registry_2025: z.number().int().default(0),
  both_years: z.number().int().default(0),
  controlled_baseline_2026: z.number().int().default(0),
  controlled_current_month: z.number().int().default(0),
});

// Bar-1 population is "HT murni" (rerata TD >=140/90), NOT registry
// membership (which also admits Pre-Hipertensi + riwayat-gated-but-controlled
// patients) — see backend hipertensi_charts_scan._ht_murni.
export const Kohort2TahunSchema = z.object({
  hipertensi_2025: z.number().int().default(0),
  diperiksa_2026: z.number().int().default(0),
  td_2026_tinggi: z.number().int().default(0),
  td_2026_terkendali: z.number().int().default(0),
  // Each split from td_2026_tinggi / td_2026_terkendali, not a total.
  tinggi_diobati: z.number().int().default(0),
  tinggi_tidak_diobati: z.number().int().default(0),
  terkendali_diobati: z.number().int().default(0),
  terkendali_tidak_diobati: z.number().int().default(0),
});

export const HT2026Schema = z.object({
  hipertensi_2026: z.number().int().default(0),
  pasien_baru: z.number().int().default(0),
  sudah_hipertensi: z.number().int().default(0),
  // Each split from pasien_baru / sudah_hipertensi, not a total.
  baru_diobati: z.number().int().default(0),
  baru_tidak_diobati: z.number().int().default(0),
  sudah_diobati: z.number().int().default(0),
  sudah_tidak_diobati: z.number().int().default(0),
});

export const HipertensiChartsSchema = z.object({
  current_month: z.string().nullable().default(null),
  monthly: z.array(ChartsMonthPointSchema).default([]),
  cascade: CascadeSchema,
  proporsi: ProporsiSchema,
  kohort_2tahun: Kohort2TahunSchema,
  hipertensi_2026: HT2026Schema,
  cache_hit: z.boolean(),
  computed_at: z.string().nullable(),
  computing: z.boolean().default(false),
  progress: WarmProgressSchema.nullable().default(null),
});
export type HipertensiCharts = z.infer<typeof HipertensiChartsSchema>;

export async function getHipertensiCharts(
  puskesmas_id: string,
): Promise<HipertensiCharts> {
  const { data } = await http.get(`/hipertensi-reports/charts`, {
    params: { puskesmas_id },
  });
  return HipertensiChartsSchema.parse(data);
}

export async function clearHipertensiChartsCache(
  puskesmas_id: string,
): Promise<void> {
  await http.delete(`/hipertensi-reports/charts/cache`, {
    params: { puskesmas_id },
  });
}
