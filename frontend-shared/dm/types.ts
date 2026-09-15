import { z } from "zod";

// Re-declared here (not imported from an app's @/lib/api/types) so the shared
// DM registry feature is self-contained across both apps — same convention as
// frontend-shared/hipertensi/types.ts.

// One kunjungan in a follow-up month. Expect most of these to be sparse:
// only ~4% of ePuskesmas visits carry any glucose value (vs blood pressure,
// recorded at nearly every visit). Empty is the normal case, not an error.
export const DmFollowUpReading = z.object({
  tanggal: z.string().nullable(), // null for a Missed Visit (month with no kunjungan)
  gds: z.number().nullable(),
  gdp: z.number().nullable(),
  gd2pp: z.number().nullable(),
  hba1c: z.number().nullable(),
  interpretasi: z.string(),
  obat: z.array(z.string()).default([]),
});
export type DmFollowUpReading = z.infer<typeof DmFollowUpReading>;

// Per-field source of each baseline value: "ASIK" | "EPUS" | null (absent).
// ASIK is the source of truth; ePuskesmas (EPUS) is the per-field fallback.
// `gula_darah` is one tag for the whole reading block — the CKG values are
// split across several ASIK layanan and merged per field, so a per-slot tag
// would be misleading.
export const DmRegistrySources = z.object({
  gula_darah: z.string().nullable().default(null),
  riwayat_dm: z.string().nullable().default(null),
  obat: z.string().nullable().default(null),
});
export type DmRegistrySources = z.infer<typeof DmRegistrySources>;

export const DmRegistryRow = z.object({
  puskesmas_name: z.string(),
  tahun_pelaporan: z.number(),
  nik: z.string(),
  nama: z.string(),
  jenis_kelamin: z.string().default(""),
  tanggal_lahir: z.string().nullable(),
  no_tlp: z.string().default(""),
  alamat: z.string().default(""),
  tanggal_berkunjung: z.string().nullable(),
  riwayat_dm: z.string(),
  gds1: z.number().nullable(),
  gds2: z.number().nullable(),
  gdp: z.number().nullable(),
  gd2pp: z.number().nullable(),
  hba1c: z.number().nullable(),
  interpretasi: z.string(),
  obat: z.array(z.string()).default([]),
  sources: DmRegistrySources.default({
    gula_darah: null,
    riwayat_dm: null,
    obat: null,
  }),
  // Month number (1..12) → readings. JSON keys arrive as strings.
  followup: z.record(z.string(), z.array(DmFollowUpReading)).default({}),
});
export type DmRegistryRow = z.infer<typeof DmRegistryRow>;
