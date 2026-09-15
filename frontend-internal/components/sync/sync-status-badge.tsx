import { Badge } from "@/components/ui/badge";
import type { SyncStatus } from "@/lib/api/types";

const VARIANT: Record<
  SyncStatus,
  "default" | "secondary" | "destructive" | "success" | "warning"
> = {
  pending: "secondary",
  running: "warning",
  success: "success",
  failed: "destructive",
  cancelled: "secondary",
};

export function SyncStatusBadge({ status }: { status: SyncStatus }) {
  return <Badge variant={VARIANT[status]}>{status}</Badge>;
}
