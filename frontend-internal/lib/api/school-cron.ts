import { http } from "./client";
import {
  ScrapeJobOut,
  SchoolCronConfigOut,
  type ScrapeJob,
  type SchoolCronConfig,
  type SchoolCronConfigCreateInput,
  type SchoolCronConfigUpdateInput,
} from "./types";

export async function getSchoolCronConfig(
  puskesmasId: string,
): Promise<SchoolCronConfig | null> {
  try {
    const { data } = await http.get(
      `/admin/puskesmas/${puskesmasId}/school-cron-config`,
    );
    return SchoolCronConfigOut.parse(data);
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

export async function createSchoolCronConfig(
  puskesmasId: string,
  input: SchoolCronConfigCreateInput,
): Promise<SchoolCronConfig> {
  const { data } = await http.post(
    `/admin/puskesmas/${puskesmasId}/school-cron-config`,
    input,
  );
  return SchoolCronConfigOut.parse(data);
}

export async function updateSchoolCronConfig(
  puskesmasId: string,
  input: SchoolCronConfigUpdateInput,
): Promise<SchoolCronConfig> {
  const { data } = await http.patch(
    `/admin/puskesmas/${puskesmasId}/school-cron-config`,
    input,
  );
  return SchoolCronConfigOut.parse(data);
}

export async function deleteSchoolCronConfig(puskesmasId: string): Promise<void> {
  await http.delete(`/admin/puskesmas/${puskesmasId}/school-cron-config`);
}

export async function runSchoolCronNow(puskesmasId: string): Promise<ScrapeJob> {
  const { data } = await http.post(
    `/admin/puskesmas/${puskesmasId}/school-cron-config/run-now`,
  );
  return ScrapeJobOut.parse(data);
}
