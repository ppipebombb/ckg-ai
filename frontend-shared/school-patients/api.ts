import { http } from "@/lib/api/client";
import {
  PageSchema,
  SchoolFacetsOut,
  SchoolPatientDecryptedOut,
  SchoolPatientOut,
  type Page,
  type SchoolFacets,
  type SchoolPatient,
  type SchoolPatientDecrypted,
} from "./types";

// Read-only surface only. The delete mutation is internal-only and stays in
// frontend-internal so the client dashboard bundle ships no way to trigger it.
export type SchoolPatientListQuery = {
  page: number;
  size: number;
  puskesmas_id?: string;
  screening_status?: string;
  school_name?: string;
  class_name?: string;
  school_year?: number;
  min_age?: number;
  max_age?: number;
  q?: string;
};

export async function listSchoolPatients(
  query: SchoolPatientListQuery,
): Promise<Page<SchoolPatient>> {
  const { data } = await http.get("/school-patients", { params: query });
  return PageSchema(SchoolPatientOut).parse(data);
}

export async function decryptSchoolPatient(
  id: string,
): Promise<SchoolPatientDecrypted> {
  const { data } = await http.post(`/school-patients/${id}/decrypt`);
  return SchoolPatientDecryptedOut.parse(data);
}

export async function getSchoolFacets(
  puskesmasId?: string,
): Promise<SchoolFacets> {
  const { data } = await http.get("/school-patients/facets", {
    params: puskesmasId ? { puskesmas_id: puskesmasId } : undefined,
  });
  return SchoolFacetsOut.parse(data);
}
