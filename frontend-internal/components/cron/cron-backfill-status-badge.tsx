import { Badge } from "@/components/ui/badge";
import type { CronBackfillStatus } from "@/lib/api/types";

const VARIANT: Record<
  CronBackfillStatus,
  "default" | "secondary" | "destructive" | "success" | "warning"
> = {
  pending: "secondary",
  running: "warning",
  success: "success",
  failed: "destructive",
  cancelled: "secondary",
};

export function CronBackfillStatusBadge({
  status,
}: {
  status: CronBackfillStatus;
}) {
  return <Badge variant={VARIANT[status]}>{status}</Badge>;
}
