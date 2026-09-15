import { http } from "./client";
import {
  PageSchema,
  PuskesmasOut,
  PuskesmasDetailOut,
  CredOut,
  type Puskesmas,
  type PuskesmasDetail,
  type PuskesmasCreateInput,
  type PuskesmasUpdateInput,
  type CredInput,
  type Page,
} from "./types";

export type PuskesmasListQuery = { page: number; size: number; name?: string };

export async function listPuskesmas(q: PuskesmasListQuery): Promise<Page<Puskesmas>> {
  const { data } = await http.get("/puskesmas", { params: q });
  return PageSchema(PuskesmasOut).parse(data);
}

export async function getPuskesmas(id: string): Promise<PuskesmasDetail> {
  const { data } = await http.get(`/puskesmas/${id}`);
  return PuskesmasDetailOut.parse(data);
}

export async function createPuskesmas(input: PuskesmasCreateInput): Promise<Puskesmas> {
  const { data } = await http.post("/puskesmas", input);
  return PuskesmasOut.parse(data);
}

export async function updatePuskesmas(
  id: string,
  input: PuskesmasUpdateInput,
): Promise<PuskesmasDetail> {
  const payload: Record<string, unknown> = {};
  if (input.name !== undefined) payload.name = input.name;
  if (input.epus_url !== undefined) payload.epus_url = input.epus_url;
  if (input.asik_url !== undefined) payload.asik_url = input.asik_url;
  if (input.asik_default_alamat !== undefined)
    payload.asik_default_alamat = input.asik_default_alamat;
  const { data } = await http.patch(`/puskesmas/${id}`, payload);
  return PuskesmasDetailOut.parse(data);
}

export async function deletePuskesmas(id: string): Promise<void> {
  await http.delete(`/puskesmas/${id}`);
}

export type CredKind = "epus" | "asik";

export async function setCredentials(
  id: string,
  kind: CredKind,
  input: CredInput,
): Promise<void> {
  await http.put(`/puskesmas/${id}/credentials/${kind}`, input);
}

export async function clearCredentials(id: string, kind: CredKind): Promise<void> {
  await http.delete(`/puskesmas/${id}/credentials/${kind}`);
}

export async function decryptCredentials(id: string, kind: CredKind) {
  const { data } = await http.post(`/puskesmas/${id}/credentials/${kind}/decrypt`);
  return CredOut.parse(data);
}
