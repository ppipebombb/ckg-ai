import { z } from "zod";

// Re-declared here (not imported from an app's @/lib/api/types) so the shared
// hipertensi registry feature is self-contained across both apps. The
// app-local Full Review Diagnose tab keeps its own HipertensiReportRow.

// Hipertensi Registry (V8juni2026 dirjen layout) — one patient per row with the
// full baseline + follow-up detail, so the UI can expand it and the export emits
// the wide multi-row sheet.
export const FollowUpReading = z.object({
  // One kunjungan — every visit in the month is listed, each with its own status.
  tanggal: z.string().nullable(), // null for a Missed Visit (month with no kunjungan)
  sys: z.number().nullable(),
  dia: z.number().nullable(),
  interpretasi: z.string(),
  obat: z.array(z.string()).default([]),
});
export type FollowUpReading = z.infer<typeof FollowUpReading>;

// Per-field source of each baseline value: "ASIK" | "EPUS" | null (absent).
// ASIK is the source of truth; ePuskesmas (EPUS) is the per-field fallback.
export const RegistrySources = z.object({
  td1: z.string().nullable().default(null),
  td2: z.string().nullable().default(null),
  riwayat_ht: z.string().nullable().default(null),
  obat: z.string().nullable().default(null),
});
export type RegistrySources = z.infer<typeof RegistrySources>;

export const HipertensiRegistryRow = z.object({
  puskesmas_name: z.string(),
  tahun_pelaporan: z.number(),
  nik: z.string(),
  nama: z.string(),
  jenis_kelamin: z.string().default(""),
  tanggal_lahir: z.string().nullable(),
  no_tlp: z.string().default(""),
  alamat: z.string().default(""),
  tanggal_berkunjung: z.string().nullable(),
  riwayat_ht: z.string(),
  td_sys1: z.number().nullable(),
  td_dia1: z.number().nullable(),
  td_sys2: z.number().nullable(),
  td_dia2: z.number().nullable(),
  rerata_sys: z.number().nullable(),
  rerata_dia: z.number().nullable(),
  interpretasi: z.string(),
  obat: z.array(z.string()).default([]),
  sources: RegistrySources.default({
    td1: null,
    td2: null,
    riwayat_ht: null,
    obat: null,
  }),
  // Month number (1..12) → readings. JSON keys arrive as strings.
  followup: z.record(z.string(), z.array(FollowUpReading)).default({}),
});
export type HipertensiRegistryRow = z.infer<typeof HipertensiRegistryRow>;

// Gap Tatalaksana — one registry member who has never been prescribed an
// antihypertensive, i.e. a patient in the gap between the two lines of the
// "Pasien Hipertensi Tertatalaksana" chart. Contact details can legitimately be
// empty (the source left them blank); rows are still listed.
export const HipertensiGapRow = z.object({
  puskesmas_name: z.string(),
  nik: z.string(),
  nama: z.string(),
  jenis_kelamin: z.string().default(""),
  tanggal_lahir: z.string().nullable(),
  no_tlp: z.string().default(""),
  alamat: z.string().default(""),
  tanggal_berkunjung: z.string().nullable(),
  rerata_sys: z.number().nullable(),
  rerata_dia: z.number().nullable(),
  interpretasi: z.string(),
  // "YYYY-MM" — the month the patient entered the registry.
  registration_ym: z.string(),
});
export type HipertensiGapRow = z.infer<typeof HipertensiGapRow>;
