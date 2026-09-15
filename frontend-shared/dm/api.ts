import { z } from "zod";
import { http } from "@/lib/api/client";
import { WarmProgressSchema } from "@/lib/api/warm-progress";
import { DmRegistryRow } from "./types";

// ── Registri Diabetes Melitus ──────────────────────────────────────────────
export const DmRegistryResponseSchema = z.object({
  items: z.array(DmRegistryRow),
  total: z.number().int(),
  total_dm: z.number().int().default(0),
  total_prediabetes: z.number().int().default(0),
  page: z.number().int(),
  size: z.number().int(),
  pages: z.number().int(),
  cache_hit: z.boolean(),
  computed_at: z.string().nullable(),
  computing: z.boolean().default(false),
  progress: WarmProgressSchema.nullable().default(null),
});
export type DmRegistryResponse = z.infer<typeof DmRegistryResponseSchema>;

export type DmRegistryQuery = {
  puskesmas_id: string;
  year: number;
  q?: string;
  page: number;
  size: number;
};

export async function getDmRegistry(
  q: DmRegistryQuery,
): Promise<DmRegistryResponse> {
  const { data } = await http.get(`/dm-reports/registry`, { params: q });
  return DmRegistryResponseSchema.parse(data);
}

export async function clearDmRegistryCache(
  puskesmas_id: string,
  year: number,
): Promise<void> {
  await http.delete(`/dm-reports/registry/cache`, {
    params: { puskesmas_id, year },
  });
}

export async function exportDmRegistry(
  puskesmas_id: string,
  year: number,
): Promise<Blob> {
  const { data } = await http.get(`/dm-reports/registry/export`, {
    params: { puskesmas_id, year },
    responseType: "blob",
  });
  return data as Blob;
}
