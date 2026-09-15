"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, Ban } from "lucide-react";
import { format, parseISO } from "date-fns";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ErrorState } from "@/components/common/error-state";
import { MergeStatusBadge } from "@/components/merge/merge-status-badge";
import { MergeLogStream, MergeLogHistory } from "@/components/merge/merge-log-stream";
import { useCancelMergeJob, useMergeJob } from "@/lib/hooks/use-merge";
import { asApiError } from "@/lib/api/client";

export default function MergeJobDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const job = useMergeJob(id);
  const cancel = useCancelMergeJob();

  const handleCancel = async () => {
    try {
      await cancel.mutateAsync(id);
      toast.success("Job cancelled");
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  if (job.error) return <ErrorState error={job.error} />;

  const live =
    job.data?.status === "pending" || job.data?.status === "running";
  const cancellable = live;

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="h-8 -ml-2 px-2">
        <Link href="/merge-with-ai" prefetch={false}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
      </Button>

      <PageHeader
        title="Merge job"
        description={
          job.data
            ? `${job.data.puskesmas_name} • ${job.data.date_filter ?? (job.data.patient_nik ? `NIK ${job.data.patient_nik}` : "—")}${job.data.force_remerge ? " • force" : ""}`
            : "Loading…"
        }
        actions={
          cancellable ? (
            <Button
              variant="destructive"
              onClick={handleCancel}
              disabled={cancel.isPending}
            >
              <Ban className="h-4 w-4" />
              Cancel
            </Button>
          ) : undefined
        }
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-7">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">Status</CardTitle>
          </CardHeader>
          <CardContent>
            {job.data ? <MergeStatusBadge status={job.data.status} /> : "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">Progress</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {job.data
              ? `${job.data.processed_count ?? 0} / ${job.data.total_count ?? 0}`
              : "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">Succeeded</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums text-emerald-600">
            {job.data?.succeeded_count ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">Failed</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums text-[var(--destructive)]">
            {job.data?.failed_count ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">Skipped</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {job.data?.skipped_count ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">CPU avg / peak</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {job.data?.cpu_avg_pct != null
              ? `${job.data.cpu_avg_pct.toFixed(0)}%`
              : "—"}
            {job.data?.cpu_peak_pct != null && (
              <span className="ml-1 text-xs font-normal text-[var(--muted-foreground)]">
                / {job.data.cpu_peak_pct.toFixed(0)}%
              </span>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">RAM avg / peak</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {job.data?.mem_avg_mb != null
              ? `${job.data.mem_avg_mb.toFixed(0)}`
              : "—"}
            {job.data?.mem_peak_mb != null && (
              <span className="ml-1 text-xs font-normal text-[var(--muted-foreground)]">
                / {job.data.mem_peak_mb.toFixed(0)} MB
              </span>
            )}
          </CardContent>
        </Card>
      </div>

      {job.data?.error_message && (
        <div className="rounded-md border border-[var(--destructive)]/40 bg-[var(--destructive)]/10 p-3 text-sm text-[var(--destructive)]">
          <p className="font-medium">Error</p>
          <p className="font-mono text-xs whitespace-pre-wrap">{job.data.error_message}</p>
        </div>
      )}

      {live ? (
        <MergeLogStream jobId={id} enabled={live} />
      ) : job.data ? (
        <MergeLogHistory jobId={id} />
      ) : null}

      {job.data && (
        <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
          <Meta label="Started" value={fmt(job.data.started_at)} />
          <Meta label="Finished" value={fmt(job.data.finished_at)} />
          <Meta
            label="Duration"
            value={
              job.data.duration_seconds != null
                ? `${job.data.duration_seconds.toFixed(1)}s`
                : "—"
            }
          />
          <Meta label="Triggered by" value={job.data.triggered_by_type} />
          <Meta label="Force re-merge" value={job.data.force_remerge ? "yes" : "no"} />
          <Meta label="Celery task" value={job.data.celery_task_id ?? "—"} />
        </div>
      )}
    </div>
  );
}

function fmt(iso: string | null) {
  return iso ? format(parseISO(iso), "yyyy-MM-dd HH:mm:ss") : "—";
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-[var(--muted-foreground)]">{label}</p>
      <p className="truncate font-mono text-xs">{value}</p>
    </div>
  );
}
