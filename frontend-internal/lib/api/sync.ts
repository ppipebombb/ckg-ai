import { http } from "./client";
import {
  PageSchema,
  SyncJobLogOut,
  SyncJobOut,
  type Page,
  type SyncJob,
  type SyncStatus,
} from "./types";

export type SyncJobListQuery = {
  page: number;
  size: number;
  puskesmas_id?: string;
  patient_id?: string;
  status?: SyncStatus;
};

export async function startSyncAsik(
  patientId: string,
  headless = true,
): Promise<SyncJob> {
  const { data } = await http.post(`/patients/${patientId}/sync-asik`, {
    headless,
  });
  return SyncJobOut.parse(data);
}

// Register an epus_only + Tandai-CKG patient into ASIK from scratch, then fill.
// Tracked on a SyncJob (same history/log UI as sync) via the create.run_one task.
export async function startCreateAsik(
  patientId: string,
  headless = true,
): Promise<SyncJob> {
  const { data } = await http.post(`/patients/${patientId}/create-asik`, {
    headless,
  });
  return SyncJobOut.parse(data);
}

export async function listSyncJobs(
  q: SyncJobListQuery,
): Promise<Page<SyncJob>> {
  const { data } = await http.get(`/sync/jobs`, { params: q });
  return PageSchema(SyncJobOut).parse(data);
}

export async function getSyncJob(jobId: string): Promise<SyncJob> {
  const { data } = await http.get(`/sync/jobs/${jobId}`);
  return SyncJobOut.parse(data);
}

export async function getSyncJobLog(jobId: string, tail = 200) {
  const { data } = await http.get(`/sync/jobs/${jobId}/log`, {
    params: { tail },
  });
  return SyncJobLogOut.parse(data);
}

export async function cancelSyncJob(jobId: string): Promise<SyncJob> {
  const { data } = await http.post(`/sync/jobs/${jobId}/cancel`);
  return SyncJobOut.parse(data);
}
