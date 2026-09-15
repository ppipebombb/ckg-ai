import { Badge } from "@/components/ui/badge";
import type { LoopRunStatus } from "@/lib/api/types";

const VARIANT: Record<
  LoopRunStatus,
  "default" | "secondary" | "destructive" | "success" | "warning"
> = {
  pending: "secondary",
  running: "warning",
  covered: "success",
  no_data: "secondary",
  needs_review: "warning",
  merged: "success",
  pr_rejected: "destructive",
  changes_ready: "default",
  bad_creds: "destructive",
  failed: "destructive",
  cancelled: "secondary",
};

const LABEL: Record<LoopRunStatus, string> = {
  pending: "pending",
  running: "running",
  covered: "covered",
  no_data: "no data",
  needs_review: "needs review",
  merged: "merged",
  pr_rejected: "pr rejected",
  changes_ready: "changes ready",
  bad_creds: "bad creds",
  failed: "failed",
  cancelled: "cancelled",
};

export function LoopStatusBadge({ status }: { status: LoopRunStatus }) {
  return <Badge variant={VARIANT[status]}>{LABEL[status]}</Badge>;
}
