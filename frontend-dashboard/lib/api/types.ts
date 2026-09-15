import { z } from "zod";

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

// Auth
export const TokenResponse = z.object({
  access_token: z.string(),
  token_type: z.string(),
});

export const AdminOut = z.object({
  id: z.string().uuid(),
  email: z.string().email(),
  full_name: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Admin = z.infer<typeof AdminOut>;

// Puskesmas
export const PuskesmasOut = z.object({
  id: z.string().uuid(),
  name: z.string(),
  epus_url: z.string().nullable(),
  asik_url: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Puskesmas = z.infer<typeof PuskesmasOut>;

export const PuskesmasDetailOut = PuskesmasOut.extend({
  is_epus_cred_set: z.boolean(),
  is_asik_cred_set: z.boolean(),
});
export type PuskesmasDetail = z.infer<typeof PuskesmasDetailOut>;

// User
export const UserOut = z.object({
  id: z.string().uuid(),
  email: z.string().email(),
  full_name: z.string(),
  puskesmas_id: z.string().uuid(),
  puskesmas_name: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type User = z.infer<typeof UserOut>;

// Per-quarter terkendali tally + tatalaksana counts (new dashboard tabs).
export const QuarterStatusOut = z.object({
  terkendali: z.number(),
  tidak_terkendali: z.number(),
  belum_atau_tidak_ada: z.number(),
});
export type QuarterStatus = z.infer<typeof QuarterStatusOut>;

export const TerkendaliDashboardOut = z.object({
  total: z.number(),
  tw1: QuarterStatusOut,
  tw2: QuarterStatusOut,
  tw3: QuarterStatusOut,
  tw4: QuarterStatusOut,
  pemberian_obat: z.number(),
  pemberian_edukasi: z.number(),
  cache_hit: z.boolean(),
  computed_at: z.string().nullable(),
  computing: z.boolean(),
});
export type TerkendaliDashboard = z.infer<typeof TerkendaliDashboardOut>;

// Per-puskesmas qualified-NIK totals for one report (the 'total pasien per
// puskesmas' card) — one request instead of N per-puskesmas terkendali calls.
export const PuskesmasTotalOut = z.object({
  puskesmas_id: z.string(),
  name: z.string(),
  total: z.number().nullable(),
  // Hipertensi only: interpretasi-band split of `total` (null for GDP / cold).
  total_hipertensi: z.number().nullable().default(null),
  total_pre_hipertensi: z.number().nullable().default(null),
});
export type PuskesmasTotal = z.infer<typeof PuskesmasTotalOut>;

export const DashboardTotalsOut = z.object({
  items: z.array(PuskesmasTotalOut),
  grand_total: z.number(),
  computing: z.boolean(),
});
export type DashboardTotals = z.infer<typeof DashboardTotalsOut>;

// GDP Report row (dashboard table)
export const GdpReportRow = z.object({
  puskesmas_name: z.string(),
  tahun_pelaporan: z.number(),
  nama: z.string(),
  nik: z.string(),
  tanggal_diagnosis: z.string().nullable(),
  tertatalaksana_obat: z.boolean(),
  tertatalaksana_edukasi: z.boolean(),
  // Map of month number 1..12 → max GDP (mg/dl) or null. JSON arrives with
  // string keys; coerce to number on read.
  gdp_by_month: z.record(z.string(), z.number().nullable()),
  // Raw per-day readings for the Full Review Diagnose tab. Keyed by ISO date →
  // { lab, ptm }, each value nullable. Default {} for pre-existing caches.
  gdp_by_day: z
    .record(
      z.string(),
      z.object({ lab: z.number().nullable(), ptm: z.number().nullable() }),
    )
    .default({}),
  terkendali_bulan_berjalan: z.string(),
  terkendali_tw1: z.string(),
  terkendali_tw2: z.string(),
  terkendali_tw3: z.string(),
  terkendali_tw4: z.string(),
});
export type GdpReportRow = z.infer<typeof GdpReportRow>;
