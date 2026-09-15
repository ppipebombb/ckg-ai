import { z } from "zod";

// Self-contained (not imported from an app's @/lib/api/types) so the shared Bayi
// Kuning registry works in both apps — same convention as frontend-shared/dm etc.

// Per-value provenance: "EPUS" (EPUS's own klasifikasi field) | "Hitung" (derived
// by the backend from the MTBM questionnaire) | null. Unlike the HT/DM ASIK/EPUS
// pill, here the distinction is isian-EPUS vs backend-computed.
export const BayiRegistrySources = z.object({
  klasifikasi: z.string().nullable().default(null),
  diagnosis: z.string().nullable().default(null),
});
export type BayiRegistrySources = z.infer<typeof BayiRegistrySources>;

export const BayiIkterusBaseline = z.object({
  klasifikasi: z.string().default(""), // "Ikterus" | "Ikterus berat" | "Tidak ada ikterus" | ""
  diagnosis: z.string().default(""),
  rujuk_eksternal: z.string().default(""),
  sources: BayiRegistrySources.default({ klasifikasi: null, diagnosis: null }),
});
export type BayiIkterusBaseline = z.infer<typeof BayiIkterusBaseline>;

export const BayiIkterusPemantauan = BayiIkterusBaseline.extend({
  tanggal: z.string().nullable(),
});
export type BayiIkterusPemantauan = z.infer<typeof BayiIkterusPemantauan>;

export const BayiIkterus = z.object({
  baseline: BayiIkterusBaseline,
  pemantauan: z.array(BayiIkterusPemantauan).default([]),
});
export type BayiIkterus = z.infer<typeof BayiIkterus>;

export const BayiRegistryRow = z.object({
  puskesmas_name: z.string(),
  tahun_pelaporan: z.number(),
  nik: z.string(),
  nama: z.string(),
  jenis_kelamin: z.string().default(""),
  tanggal_lahir: z.string().nullable(),
  no_tlp: z.string().default(""),
  alamat: z.string().default(""),
  tanggal_berkunjung: z.string().nullable(),
  ikterus: BayiIkterus.nullable(),
});
export type BayiRegistryRow = z.infer<typeof BayiRegistryRow>;

export type BayiSheet = "ikterus" | "ikterus_berat";
