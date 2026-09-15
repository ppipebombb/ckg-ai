import { http } from "@/lib/api/client";
import {
  AsikPreviewOut,
  PageSchema,
  PatientOut,
  PatientDecryptedOut,
  type AsikPreview,
  type Patient,
  type PatientDecrypted,
  type Page,
} from "./types";

// Read-only surface only. Mutations (scrape/merge/sync/delete) deliberately do
// NOT live here — they are internal-only and stay in frontend-internal so the
// client dashboard bundle ships no way to trigger them.
export type PatientListQuery = {
  page: number;
  size: number;
  q?: string;
  puskesmas_id?: string;
  match_status?: string;
  filter_date?: string;
  merged?: boolean;
  min_age?: number;
  max_age?: number;
};

export async function listPatients(query: PatientListQuery): Promise<Page<Patient>> {
  const { data } = await http.get("/patients", { params: query });
  return PageSchema(PatientOut).parse(data);
}

export async function getPatient(id: string): Promise<Patient> {
  const { data } = await http.get(`/patients/${id}`);
  return PatientOut.parse(data);
}

export async function decryptPatient(id: string): Promise<PatientDecrypted> {
  const { data } = await http.post(`/patients/${id}/decrypt`);
  return PatientDecryptedOut.parse(data);
}

export async function asikPreview(id: string): Promise<AsikPreview> {
  const { data } = await http.post(`/patients/${id}/asik-preview`);
  return AsikPreviewOut.parse(data);
}
