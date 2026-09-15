import { z } from "zod";

// Re-declared here (not imported from an app's @/lib/api/types) so the shared
// patients feature is self-contained across both apps.
export type Page<T> = {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
};

export const PageSchema = <T extends z.ZodTypeAny>(item: T) =>
  z.object({
    items: z.array(item),
    total: z.number(),
    page: z.number(),
    size: z.number(),
    pages: z.number(),
  });

export const MatchStatus = z.enum(["asik_only", "epus_only", "matched"]);
export type MatchStatus = z.infer<typeof MatchStatus>;

export const PatientOut = z.object({
  id: z.string().uuid(),
  puskesmas_id: z.string().uuid(),
  nik: z.string(),
  nama: z.string(),
  match_status: MatchStatus,
  has_asik_data: z.boolean(),
  has_epus_data: z.boolean(),
  has_merged_data: z.boolean(),
  merged_at: z.string().nullable(),
  filter_date: z.string(),
  ruangan: z.string(),
  birth_date: z.string().nullable(),
  // epus_only + this true = a "create in ASIK" candidate.
  epus_tandai_ckg: z.boolean().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Patient = z.infer<typeof PatientOut>;

export const PatientDecryptedOut = z.object({
  id: z.string().uuid(),
  puskesmas_id: z.string().uuid(),
  nik: z.string(),
  nama: z.string(),
  match_status: MatchStatus,
  scraped_asik_data: z.unknown().nullable(),
  scraped_epus_data: z.unknown().nullable(),
  merged_data: z.unknown().nullable(),
  merged_at: z.string().nullable(),
  filter_date: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type PatientDecrypted = z.infer<typeof PatientDecryptedOut>;

export const AsikPreviewOut = z.object({
  id: z.string().uuid(),
  forms: z.record(z.string(), z.record(z.string(), z.unknown())),
});
export type AsikPreview = z.infer<typeof AsikPreviewOut>;
