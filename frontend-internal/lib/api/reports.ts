import { z } from "zod";
import { http } from "./client";

export const DelayBucketSchema = z.object({
  days: z.number().int(),
  count: z.number().int(),
  pct: z.number(),
});
export type DelayBucket = z.infer<typeof DelayBucketSchema>;

export const VisitSummarySchema = z.object({
  data_on_asik: z.number().int(),
  data_on_epus: z.number().int(),
  matched: z.number().int(),
  tandai_ckg: z.number().int(),
  delayed_ckg: z.number().int(),
  delayed_ckg_pct: z.number(),
  delay_distribution: z.array(DelayBucketSchema),
});
export type VisitSummary = z.infer<typeof VisitSummarySchema>;

export async function getVisitSummary(
  puskesmasId?: string,
): Promise<VisitSummary> {
  const { data } = await http.get(`/reports/visit-summary`, {
    params: puskesmasId ? { puskesmas_id: puskesmasId } : undefined,
  });
  return VisitSummarySchema.parse(data);
}

export const GdpSourceQualitySchema = z.object({
  puskesmas_id: z.string().uuid().nullable(),
  people_with_gdp: z.number().int(),
  lab_backed: z.number().int(),
  ptm_fallback: z.number().int(),
  ptm_fallback_pct: z.number(),
  computed_at: z.string().nullable(),
  cache_hit: z.boolean(),
  computing: z.boolean().default(false),
});
export type GdpSourceQuality = z.infer<typeof GdpSourceQualitySchema>;

export async function getGdpSourceQuality(
  puskesmasId?: string,
): Promise<GdpSourceQuality> {
  const { data } = await http.get(`/reports/gdp-source-quality`, {
    params: puskesmasId ? { puskesmas_id: puskesmasId } : undefined,
  });
  return GdpSourceQualitySchema.parse(data);
}

export async function clearGdpSourceQualityCache(
  puskesmasId?: string,
): Promise<void> {
  await http.delete(`/reports/gdp-source-quality/cache`, {
    params: puskesmasId ? { puskesmas_id: puskesmasId } : undefined,
  });
}
