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
import { ScrapeStatusBadge } from "@/components/scrape/scrape-status-badge";
import { ScrapeLogStream, ScrapeLogHistory } from "@/components/scrape/scrape-log-stream";
import { useCancelScrapeJob, useScrapeJob } from "@/lib/hooks/use-scrape";
import { asApiError } from "@/lib/api/client";

export default function ScrapeJobDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const job = useScrapeJob(id);
  const cancel = useCancelScrapeJob();

  const handleCancel = async () => {
    try {
      await cancel.mutateAsync(id);
      toast.success("Job dibatalkan");
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
        <Link href="/scrape-jobs" prefetch={false}>
          <ArrowLeft className="h-4 w-4" />
          Kembali
        </Link>
      </Button>

      <PageHeader
        title="Scrape job"
        description={
          job.data
            ? `${job.data.puskesmas_name} • ${job.data.kind.toUpperCase()} • ${job.data.date_filter ?? (job.data.patient_nik ? `NIK ${job.data.patient_nik}` : "—")}`
            : "Memuat…"
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

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">Status</CardTitle>
          </CardHeader>
          <CardContent>
            {job.data ? <ScrapeStatusBadge status={job.data.status} /> : "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">Scraped</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {job.data?.scraped_count ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">Inserted/Updated</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {job.data
              ? `${job.data.inserted_count ?? 0} / ${job.data.updated_count ?? 0}`
              : "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">Duration</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {job.data?.duration_seconds != null
              ? `${job.data.duration_seconds.toFixed(1)}s`
              : "—"}
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
          <p className="font-mono text-xs">{job.data.error_message}</p>
        </div>
      )}

      {live ? (
        <ScrapeLogStream jobId={id} enabled={live} />
      ) : job.data ? (
        <ScrapeLogHistory jobId={id} />
      ) : null}

      {job.data && (
        <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
          <Meta label="Started" value={fmt(job.data.started_at)} />
          <Meta label="Finished" value={fmt(job.data.finished_at)} />
          <Meta label="Triggered by" value={job.data.triggered_by_type} />
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
