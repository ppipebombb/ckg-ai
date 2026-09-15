import { z } from "zod";
import { http } from "./client";

export type AsikLocationLevel = "province" | "city" | "district" | "subdistrict";

const AsikLocation = z.object({ name: z.string(), code: z.string() });
export type AsikLocation = z.infer<typeof AsikLocation>;

// Proxy over ASIK's public teritorial-service (backend filters children by
// parent_code). `province` needs no parentCode; the others require it.
export async function listAsikLocations(
  level: AsikLocationLevel,
  parentCode: string | undefined,
  search: string,
): Promise<AsikLocation[]> {
  const params: Record<string, string> = { search };
  if (parentCode) params.parent_code = parentCode;
  const { data } = await http.get(`/asik-locations/${level}`, { params });
  return z.array(AsikLocation).parse(data);
}
