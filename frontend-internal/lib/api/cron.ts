import { http } from "./client";
import {
  CronConfigOut,
  CronRunOut,
  CronRunSyncSummaryOut,
  PageSchema,
  type CronConfig,
  type CronConfigCreateInput,
  type CronConfigUpdateInput,
  type CronRun,
  type CronRunStatus,
  type CronRunSyncSummary,
  type Page,
} from "./types";

export type CronRunListQuery = {
  page: number;
  size: number;
  puskesmas_id?: string;
  status?: CronRunStatus;
};

export async function getCronConfig(puskesmasId: string): Promise<CronConfig | null> {
  try {
    const { data } = await http.get(`/admin/puskesmas/${puskesmasId}/cron-config`);
    return CronConfigOut.parse(data);
  } catch (e: unknown) {
    if (
      typeof e === "object" &&
      e !== null &&
      "response" in e &&
      (e as { response?: { status?: number } }).response?.status === 404
    ) {
      return null;
    }
    throw e;
  }
}

export async function createCronConfig(
  puskesmasId: string,
  input: CronConfigCreateInput,
): Promise<CronConfig> {
  const { data } = await http.post(
    `/admin/puskesmas/${puskesmasId}/cron-config`,
    input,
  );
  return CronConfigOut.parse(data);
}

export async function updateCronConfig(
  puskesmasId: string,
  input: CronConfigUpdateInput,
): Promise<CronConfig> {
  const { data } = await http.patch(
    `/admin/puskesmas/${puskesmasId}/cron-config`,
    input,
  );
  return CronConfigOut.parse(data);
}

export async function deleteCronConfig(puskesmasId: string): Promise<void> {
  await http.delete(`/admin/puskesmas/${puskesmasId}/cron-config`);
}

export async function runCronNow(puskesmasId: string): Promise<CronRun> {
  const { data } = await http.post(
    `/admin/puskesmas/${puskesmasId}/cron-config/run-now`,
  );
  return CronRunOut.parse(data);
}

export async function listCronRuns(q: CronRunListQuery): Promise<Page<CronRun>> {
  const { data } = await http.get("/admin/cron-runs", { params: q });
  return PageSchema(CronRunOut).parse(data);
}

export async function getCronRun(runId: string): Promise<CronRun> {
  const { data } = await http.get(`/admin/cron-runs/${runId}`);
  return CronRunOut.parse(data);
}

export async function getCronRunSyncSummary(
  runId: string,
): Promise<CronRunSyncSummary> {
  const { data } = await http.get(`/admin/cron-runs/${runId}/sync-summary`);
  return CronRunSyncSummaryOut.parse(data);
}

export async function cancelCronRun(runId: string): Promise<CronRun> {
  const { data } = await http.post(`/admin/cron-runs/${runId}/cancel`);
  return CronRunOut.parse(data);
}

export async function retryCronRun(runId: string): Promise<CronRun> {
  const { data } = await http.post(`/admin/cron-runs/${runId}/retry`);
  return CronRunOut.parse(data);
}
