import { z } from "zod";

// Re-declared here (not imported from an app's @/lib/api/types) so the shared
// school-patients feature is self-contained across both apps.
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

export const SchoolScreeningStatus = z.enum(["belum", "sedang", "selesai"]);
export type SchoolScreeningStatus = z.infer<typeof SchoolScreeningStatus>;

export const SchoolPatientOut = z.object({
  id: z.string().uuid(),
  puskesmas_id: z.string().uuid(),
  nik: z.string(),
  nama: z.string(),
  born_date: z.string().nullable(),
  gender: z.string().nullable(),
  school_year: z.number().int(),
  school_name: z.string().nullable(),
  class_name: z.string().nullable(),
  klaster_name: z.string().nullable(),
  screening_status: SchoolScreeningStatus,
  has_data: z.boolean(),
  scraped_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type SchoolPatient = z.infer<typeof SchoolPatientOut>;

export const SchoolPatientDecryptedOut = z.object({
  id: z.string().uuid(),
  puskesmas_id: z.string().uuid(),
  nik: z.string(),
  nama: z.string(),
  school_year: z.number().int(),
  school_name: z.string().nullable(),
  class_name: z.string().nullable(),
  klaster_name: z.string().nullable(),
  screening_status: SchoolScreeningStatus,
  scraped_sekolah_data: z.unknown().nullable(),
  scraped_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type SchoolPatientDecrypted = z.infer<typeof SchoolPatientDecryptedOut>;

export const SchoolFacet = z.object({
  name: z.string(),
  classes: z.array(z.string()),
});
export type SchoolFacet = z.infer<typeof SchoolFacet>;

export const SchoolFacetsOut = z.object({
  schools: z.array(SchoolFacet),
  school_years: z.array(z.number().int()),
});
export type SchoolFacets = z.infer<typeof SchoolFacetsOut>;
