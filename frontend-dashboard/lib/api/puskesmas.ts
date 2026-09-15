import { http } from "./client";
import {
  PageSchema,
  PuskesmasOut,
  PuskesmasDetailOut,
  type Puskesmas,
  type PuskesmasDetail,
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
