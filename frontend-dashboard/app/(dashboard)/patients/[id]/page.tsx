import { use } from "react";
import { PatientDetail } from "@shared/patients/components/patient-detail";

// Client (read-only): NO `actions` slot → none of the internal mutation controls
// (Rescrape / Merge / Sync) render or ship in this bundle. The backend
// independently default-denies those mutations to the prod scope.
export default function PatientDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <PatientDetail id={id} />;
}
