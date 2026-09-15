import { z } from "zod";

// Re-declared here (not imported from an app's @/lib/api/types) so the shared
// Dislipidemia registry feature is self-contained across both apps — same
// convention as frontend-shared/dm/types.ts.

// One kunjungan in a follow-up month. Expect most of these to be sparse: ASIK's
// lipid form is gated to ≥40 yrs AND HT/DM patients, and ePuskesmas records a
// lipid panel far less often than a blood pressure. Empty is the normal case,
// not an error.
export const LipidFollowUpReading = z.object({
  tanggal: z.string().nullable(), // null for a Missed Visit (control month with no kunjungan)
  kol_total: z.number().nullable(),
  ldl: z.number().nullable(),
  hdl: z.number().nullable(),
  trigliserida: z.number().nullable(),
  interpretasi: z.string(),
  obat: z.array(z.string()).default([]),
});
export type LipidFollowUpReading = z.infer<typeof LipidFollowUpReading>;

// Per-field source of each baseline value: "ASIK" | "EPUS" | null (absent).
// ASIK is the source of truth; ePuskesmas (EPUS) is the per-field fallback.
// `lipid` is one tag for the whole panel — the four analytes are merged per
// field, so a per-slot tag would be misleading.
export const LipidRegistrySources = z.object({
  lipid: z.string().nullable().default(null),
  riwayat_ht: z.string().nullable().default(null),
  riwayat_dm: z.string().nullable().default(null),
  obat: z.string().nullable().default(null),
});
export type LipidRegistrySources = z.infer<typeof LipidRegistrySources>;

export const LipidRegistryRow = z.object({
  puskesmas_name: z.string(),
  tahun_pelaporan: z.number(),
  nik: z.string(),
  nama: z.string(),
  jenis_kelamin: z.string().default(""),
  tanggal_lahir: z.string().nullable(),
  no_tlp: z.string().default(""),
  alamat: z.string().default(""),
  tanggal_berkunjung: z.string().nullable(),
  // Reported columns, NOT filters: unlike the hipertensi/DM registries a
  // recorded riwayat neither admits a patient nor pins the interpretasi.
  riwayat_ht: z.string(),
  riwayat_dm: z.string(),
  // Sheet order: Kolesterol Total, LDL, HDL, Trigliserida (mg/dL).
  kol_total: z.number().nullable(),
  ldl: z.number().nullable(),
  hdl: z.number().nullable(),
  trigliserida: z.number().nullable(),
  interpretasi: z.string(),
  obat: z.array(z.string()).default([]),
  sources: LipidRegistrySources.default({
    lipid: null,
    riwayat_ht: null,
    riwayat_dm: null,
    obat: null,
  }),
  // Month number (1..12) → readings. JSON keys arrive as strings.
  followup: z.record(z.string(), z.array(LipidFollowUpReading)).default({}),
});
export type LipidRegistryRow = z.infer<typeof LipidRegistryRow>;
