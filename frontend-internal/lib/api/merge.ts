import { z } from "zod";
import { http } from "./client";
import {
  MergeJobLogOut,
  MergeJobOut,
  MergePreviewOut,
  PageSchema,
  type MergeJob,
  type MergePreview,
  type MergeStartInput,
  type MergeStatus,
  type Page,
} from "./types";

export type MergeJobScope = "all" | "puskesmas" | "patient";

export type MergeJobListQuery = {
  page: number;
  size: number;
  puskesmas_id?: string;
  status?: MergeStatus;
  date_filter?: string;
  scope?: MergeJobScope;
  patient_id?: string;
};

export async function getMergePreview(
  puskesmasId: string,
  date: string,
): Promise<MergePreview> {
  const { data } = await http.get(
    `/puskesmas/${puskesmasId}/merge/preview`,
    { params: { date } },
  );
  return MergePreviewOut.parse(data);
}

export async function startMerge(
  puskesmasId: string,
  input: MergeStartInput,
): Promise<MergeJob[]> {
  const { data } = await http.post(`/puskesmas/${puskesmasId}/merge`, input);
  return z.array(MergeJobOut).parse(data);
}

export async function startPatientMerge(patientId: string): Promise<MergeJob> {
  const { data } = await http.post(`/patients/${patientId}/merge`);
  return MergeJobOut.parse(data);
}

export async function listMergeJobs(
  q: MergeJobListQuery,
): Promise<Page<MergeJob>> {
  const { data } = await http.get(`/merge/jobs`, { params: q });
  return PageSchema(MergeJobOut).parse(data);
}

export async function getMergeJob(jobId: string): Promise<MergeJob> {
  const { data } = await http.get(`/merge/jobs/${jobId}`);
  return MergeJobOut.parse(data);
}

export async function getMergeJobLog(jobId: string, tail = 200) {
  const { data } = await http.get(`/merge/jobs/${jobId}/log`, {
    params: { tail },
  });
  return MergeJobLogOut.parse(data);
}

export async function cancelMergeJob(jobId: string): Promise<MergeJob> {
  const { data } = await http.post(`/merge/jobs/${jobId}/cancel`);
  return MergeJobOut.parse(data);
}
