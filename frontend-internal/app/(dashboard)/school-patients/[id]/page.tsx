import { use } from "react";
import { SchoolPatientDetail } from "@shared/school-patients/components/school-patient-detail";

export default function SchoolPatientDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <SchoolPatientDetail id={id} />;
}
