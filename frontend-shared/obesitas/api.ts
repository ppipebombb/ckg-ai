import { z } from "zod";
import { http } from "@/lib/api/client";
import { WarmProgressSchema } from "@/lib/api/warm-progress";
import { ObesitasRegistryRow } from "./types";

// ── Registri Obesitas ──────────────────────────────────────────────────────
export const ObesitasRegistryResponseSchema = z.object({
  items: z.array(ObesitasRegistryRow),
  total: z.number().int(),
  // Band counts. Unlike the Dislipidemia registry's four overlapping analyte
  // counts these are MUTUALLY EXCLUSIVE and DO sum to `total` — the syarat is
  // one IMT scale cut in two.
  obesitas_1: z.number().int().default(0), // IMT 25 – <30
  obesitas_2: z.number().int().default(0), // IMT >= 30
  page: z.number().int(),
  size: z.number().int(),
  pages: z.number().int(),
  cache_hit: z.boolean(),
  computed_at: z.string().nullable(),
  computing: z.boolean().default(false),
  progress: WarmProgressSchema.nullable().default(null),
});
export type ObesitasRegistryResponse = z.infer<
  typeof ObesitasRegistryResponseSchema
>;

export type ObesitasRegistryQuery = {
  puskesmas_id: string;
  year: number;
  q?: string;
  page: number;
  size: number;
};

export async function getObesitasRegistry(
  q: ObesitasRegistryQuery,
): Promise<ObesitasRegistryResponse> {
  const { data } = await http.get(`/obesitas-reports/registry`, { params: q });
  return ObesitasRegistryResponseSchema.parse(data);
}

export async function clearObesitasRegistryCache(
  puskesmas_id: string,
  year: number,
): Promise<void> {
  await http.delete(`/obesitas-reports/registry/cache`, {
    params: { puskesmas_id, year },
  });
}

export async function exportObesitasRegistry(
  puskesmas_id: string,
  year: number,
): Promise<Blob> {
  const { data } = await http.get(`/obesitas-reports/registry/export`, {
    params: { puskesmas_id, year },
    responseType: "blob",
  });
  return data as Blob;
}
