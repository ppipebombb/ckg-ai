import { http } from "./client";
import {
  PageSchema,
  ScrapeJobOut,
  ScrapeJobLogOut,
  type ScrapeJob,
  type ScrapeKind,
  type ScrapeStartInput,
  type ScrapeStatus,
  type Page,
} from "./types";

export async function startScrape(
  puskesmasId: string,
  kind: ScrapeKind,
  input: ScrapeStartInput,
): Promise<ScrapeJob> {
  const { data } = await http.post(
    `/puskesmas/${puskesmasId}/scrape/${kind}`,
    input,
  );
  return ScrapeJobOut.parse(data);
}

export async function startPatientScrape(
  patientId: string,
  kind: ScrapeKind,
  headless = true,
): Promise<ScrapeJob> {
  const { data } = await http.post(`/patients/${patientId}/scrape/${kind}`, {
    headless,
  });
  return ScrapeJobOut.parse(data);
}

export type ScrapeJobScope = "all" | "puskesmas" | "patient";

export type ScrapeJobListQuery = {
  page: number;
  size: number;
  puskesmas_id?: string;
  status?: ScrapeStatus;
  kind?: ScrapeKind;
  scope?: ScrapeJobScope;
  patient_id?: string;
  parent_gdp_job_id?: string;
};

export async function listScrapeJobs(
  q: ScrapeJobListQuery,
): Promise<Page<ScrapeJob>> {
  const { data } = await http.get(`/scrape/jobs`, { params: q });
  return PageSchema(ScrapeJobOut).parse(data);
}

export async function getScrapeJob(jobId: string): Promise<ScrapeJob> {
  const { data } = await http.get(`/scrape/jobs/${jobId}`);
  return ScrapeJobOut.parse(data);
}

export async function getScrapeJobLog(jobId: string, tail = 200) {
  const { data } = await http.get(`/scrape/jobs/${jobId}/log`, {
    params: { tail },
  });
  return ScrapeJobLogOut.parse(data);
}

export async function cancelScrapeJob(jobId: string): Promise<ScrapeJob> {
  const { data } = await http.post(`/scrape/jobs/${jobId}/cancel`);
  return ScrapeJobOut.parse(data);
}
