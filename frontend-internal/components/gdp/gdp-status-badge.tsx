import { Badge } from "@/components/ui/badge";
import type { GdpReportStatus } from "@/lib/api/types";

const VARIANT: Record<
  GdpReportStatus,
  "default" | "secondary" | "destructive" | "success" | "warning"
> = {
  pending: "secondary",
  running: "warning",
  success: "success",
  failed: "destructive",
  cancelled: "secondary",
};

export function GdpStatusBadge({ status }: { status: GdpReportStatus }) {
  return <Badge variant={VARIANT[status]}>{status}</Badge>;
}
