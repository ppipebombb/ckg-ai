import { http } from "./client";
import {
  CronBackfillOut,
  CronRunOut,
  PageSchema,
  type CronBackfill,
  type CronBackfillCreateInput,
  type CronBackfillStatus,
  type CronRun,
  type Page,
} from "./types";

export type CronBackfillListQuery = {
  page: number;
  size: number;
  puskesmas_id?: string;
  status?: CronBackfillStatus;
};

export type CronBackfillRunsQuery = {
  page: number;
  size: number;
};

export async function listCronBackfills(
  q: CronBackfillListQuery,
): Promise<Page<CronBackfill>> {
  const { data } = await http.get("/admin/cron-backfills", { params: q });
  return PageSchema(CronBackfillOut).parse(data);
}

export async function getCronBackfill(id: string): Promise<CronBackfill> {
  const { data } = await http.get(`/admin/cron-backfills/${id}`);
  return CronBackfillOut.parse(data);
}

export async function createCronBackfill(
  input: CronBackfillCreateInput,
): Promise<CronBackfill> {
  const { data } = await http.post("/admin/cron-backfills", input);
  return CronBackfillOut.parse(data);
}

export async function cancelCronBackfill(id: string): Promise<CronBackfill> {
  const { data } = await http.post(`/admin/cron-backfills/${id}/cancel`);
  return CronBackfillOut.parse(data);
}

export async function listCronBackfillRuns(
  id: string,
  q: CronBackfillRunsQuery,
): Promise<Page<CronRun>> {
  const { data } = await http.get(
    `/admin/cron-backfills/${id}/cron-runs`,
    { params: q },
  );
  return PageSchema(CronRunOut).parse(data);
}
