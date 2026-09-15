import { Badge } from "@/components/ui/badge";
import type { CronRunStatus } from "@/lib/api/types";

const VARIANT: Record<
  CronRunStatus,
  "default" | "secondary" | "destructive" | "success" | "warning"
> = {
  pending: "secondary",
  running: "warning",
  success: "success",
  failed: "destructive",
  cancelled: "secondary",
};

export function CronRunStatusBadge({ status }: { status: CronRunStatus }) {
  return <Badge variant={VARIANT[status]}>{status}</Badge>;
}
