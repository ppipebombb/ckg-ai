import { use } from "react";
import { SchoolPatientDetail } from "@shared/school-patients/components/school-patient-detail";

// Client (read-only) CKG-Sekolah detail. Same shared component as the internal
// app; no mutation controls exist for school patients in either bundle.
export default function SchoolPatientDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <SchoolPatientDetail id={id} />;
}
