import { Badge } from "@/components/ui/badge";
import type { SchoolScreeningStatus } from "@shared/school-patients/types";

const VARIANT: Record<
  SchoolScreeningStatus,
  "secondary" | "warning" | "success"
> = {
  belum: "secondary",
  sedang: "warning",
  selesai: "success",
};

const LABEL: Record<SchoolScreeningStatus, string> = {
  belum: "Belum Pemeriksaan",
  sedang: "Sedang Pemeriksaan",
  selesai: "Selesai Pemeriksaan",
};

export function SchoolStatusBadge({
  status,
}: {
  status: SchoolScreeningStatus;
}) {
  return <Badge variant={VARIANT[status]}>{LABEL[status]}</Badge>;
}
