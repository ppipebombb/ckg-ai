import { z } from "zod";
import { http } from "./client";

export const ConflictRowSchema = z.object({
  section: z.string(),
  section_label: z.string(),
  merged_key: z.string(),
  asik_question: z.string().nullable(),
  epus_question: z.string().nullable(),
  conflict_count: z.number().int(),
  conflict_pct: z.number(),
});

export const ConflictSummarySchema = z.object({
  puskesmas_id: z.string().uuid().nullable(),
  total_patients: z.number().int(),
  conflicts: z.array(ConflictRowSchema),
  computed_at: z.string().nullable(),
  cache_hit: z.boolean(),
  computing: z.boolean().default(false),
});

export type ConflictRow = z.infer<typeof ConflictRowSchema>;
export type ConflictSummary = z.infer<typeof ConflictSummarySchema>;

export type MergeConflictSummaryQuery = {
  puskesmas_id?: string;
  top: number;
};

export async function getMergeConflictSummary(
  q: MergeConflictSummaryQuery,
): Promise<ConflictSummary> {
  const { data } = await http.get(`/merge-conflicts/summary`, { params: q });
  return ConflictSummarySchema.parse(data);
}

export async function clearMergeConflictCache(
  puskesmas_id?: string,
): Promise<void> {
  await http.delete(`/merge-conflicts/cache`, {
    params: puskesmas_id ? { puskesmas_id } : undefined,
  });
}
