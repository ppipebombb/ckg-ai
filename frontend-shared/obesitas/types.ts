import { z } from "zod";

// Re-declared here (not imported from an app's @/lib/api/types) so the shared
// Obesitas registry feature is self-contained across both apps — same
// convention as frontend-shared/dm/types.ts and frontend-shared/lipid/types.ts.

// One kunjungan in a follow-up month. Expect these to be sparse: weight and
// height are near-universally recorded at the CKG screening itself, but rarely
// re-recorded on an ordinary ePuskesmas visit. Empty is the normal case, not an
// error.
export const ObesitasFollowUpReading = z.object({
  tanggal: z.string().nullable(), // null for a Missed Visit (control month with no kunjungan)
  bb: z.number().nullable(), // Berat Badan (kg)
  tb: z.number().nullable(), // Tinggi Badan (cm)
  imt: z.number().nullable(), // DERIVED: BB / (TB/100)^2, 1 decimal
  // Weight change from the CKG baseline weight, POSITIVE for a loss (matching
  // how the sheet words the target, "penurunan BB >5%"). Negative = gained.
  penurunan_pct: z.number().nullable(),
  interpretasi: z.string(),
});
export type ObesitasFollowUpReading = z.infer<typeof ObesitasFollowUpReading>;

// Per-field source of each baseline value: "ASIK" | "EPUS" | null (absent).
// ASIK is the source of truth; ePuskesmas (EPUS) is the per-field fallback.
// `antropometri` is one tag for BB and TB together — the two are merged per
// field from one form, so a per-slot tag would be misleading. IMT has no tag at
// all: it is derived, never sourced.
export const ObesitasRegistrySources = z.object({
  antropometri: z.string().nullable().default(null),
  riwayat_ht: z.string().nullable().default(null),
  riwayat_dm: z.string().nullable().default(null),
});
export type ObesitasRegistrySources = z.infer<typeof ObesitasRegistrySources>;

export const ObesitasRegistryRow = z.object({
  puskesmas_name: z.string(),
  tahun_pelaporan: z.number(),
  nik: z.string(),
  nama: z.string(),
  jenis_kelamin: z.string().default(""),
  tanggal_lahir: z.string().nullable(),
  no_tlp: z.string().default(""),
  alamat: z.string().default(""),
  tanggal_berkunjung: z.string().nullable(),
  // Reported columns, NOT filters: like the Dislipidemia registry and unlike the
  // hipertensi/DM ones, a recorded riwayat neither admits a patient nor pins the
  // interpretasi.
  riwayat_ht: z.string(),
  riwayat_dm: z.string(),
  bb: z.number().nullable(),
  tb: z.number().nullable(),
  imt: z.number().nullable(),
  interpretasi: z.string(),
  sources: ObesitasRegistrySources.default({
    antropometri: null,
    riwayat_ht: null,
    riwayat_dm: null,
  }),
  // Month number (1..12) → readings. JSON keys arrive as strings.
  followup: z.record(z.string(), z.array(ObesitasFollowUpReading)).default({}),
});
export type ObesitasRegistryRow = z.infer<typeof ObesitasRegistryRow>;
