"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, RefreshCcw, RotateCw, XCircle } from "lucide-react";
import { format, parseISO } from "date-fns";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ErrorState } from "@/components/common/error-state";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { CronRunStatusBadge } from "@/components/cron/cron-run-status-badge";
import { ScrapeStatusBadge } from "@/components/scrape/scrape-status-badge";
import { MergeStatusBadge } from "@/components/merge/merge-status-badge";
import {
  cronRunKeys,
  useCancelCronRun,
  useCronRun,
  useCronRunSyncSummary,
  useRetryCronRun,
} from "@/lib/hooks/use-cron-runs";
import { mergeKeys, useMergeJob } from "@/lib/hooks/use-merge";
import { scrapeKeys, useScrapeJob } from "@/lib/hooks/use-scrape";
import { asApiError } from "@/lib/api/client";

export default function CronRunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const qc = useQueryClient();
  const run = useCronRun(id);
  const cancel = useCancelCronRun();
  const retry = useRetryCronRun();
  const [cancelOpen, setCancelOpen] = useState(false);

  const onRefresh = async () => {
    const r = run.data;
    const tasks = [
      qc.invalidateQueries({ queryKey: cronRunKeys.detail(id) }),
      // The sync step has no child job id to key off, so Refresh must ask for
      // its aggregate explicitly or the row would stay stale.
      qc.invalidateQueries({ queryKey: cronRunKeys.syncSummary(id) }),
    ];
    if (r?.asik_scrape_job_id) {
      tasks.push(
        qc.invalidateQueries({
          queryKey: scrapeKeys.detail(r.asik_scrape_job_id),
        }),
      );
    }
    if (r?.epus_scrape_job_id) {
      tasks.push(
        qc.invalidateQueries({
          queryKey: scrapeKeys.detail(r.epus_scrape_job_id),
        }),
      );
    }
    if (r?.merge_job_id) {
      tasks.push(
        qc.invalidateQueries({ queryKey: mergeKeys.detail(r.merge_job_id) }),
      );
    }
    await Promise.all(tasks);
  };

  if (run.error) return <ErrorState error={run.error} />;
  if (!run.data) {
    return (
      <div className="space-y-6">
        <PageHeader title="Cron Run" description="Loading…" />
      </div>
    );
  }

  const r = run.data;
  const canCancel = r.status === "pending" || r.status === "running";
  const canRetry = r.status === "failed" || r.status === "cancelled";

  const onCancel = async () => {
    try {
      await cancel.mutateAsync(r.id);
      toast.success("Cron run cancelled");
      setCancelOpen(false);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const onRetry = async () => {
    try {
      const newRun = await retry.mutateAsync(r.id);
      toast.success("Retry started");
      router.push(`/cron-runs/${newRun.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="h-8 -ml-2 px-2">
        <Link href="/cron-runs" prefetch={false}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
      </Button>

      <PageHeader
        title={`Cron run · ${r.puskesmas_name}`}
        description={`Target ${r.target_date}`}
        actions={
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onRefresh}
              disabled={run.isFetching}
            >
              <RotateCw
                className={`h-4 w-4 ${run.isFetching ? "animate-spin" : ""}`}
              />
              Refresh
            </Button>
            {canCancel && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCancelOpen(true)}
                disabled={cancel.isPending}
              >
                <XCircle className="h-4 w-4" />
                Cancel
              </Button>
            )}
            {canRetry && (
              <Button size="sm" onClick={onRetry} disabled={retry.isPending}>
                <RefreshCcw className="h-4 w-4" />
                Retry
              </Button>
            )}
          </div>
        }
      />

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Overview</CardTitle>
            <CronRunStatusBadge status={r.status} />
          </div>
          <CardDescription>
            {r.failed_step
              ? `Failed at step ${r.failed_step.toUpperCase()}`
              : r.current_step
                ? `Step ${r.current_step.toUpperCase()} · attempt ${r.current_step_attempt}`
                : ""}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-2 text-xs text-[var(--muted-foreground)]">
          <div>
            <span className="font-medium">Started: </span>
            {r.started_at
              ? format(parseISO(r.started_at), "yyyy-MM-dd HH:mm")
              : "—"}
          </div>
          <div>
            <span className="font-medium">Finished: </span>
            {r.finished_at
              ? format(parseISO(r.finished_at), "yyyy-MM-dd HH:mm")
              : "—"}
          </div>
          {r.error_message && (
            <div className="col-span-2 mt-2">
              <span className="font-medium">Error: </span>
              <pre className="mt-1 whitespace-pre-wrap rounded bg-[var(--muted)] p-2 text-[var(--foreground)]">
                {r.error_message}
              </pre>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Child jobs</h2>
        <div className="space-y-2">
          <ChildScrapeJobRow label="EPUS Scrape" jobId={r.epus_scrape_job_id} />
          <ChildScrapeJobRow label="ASIK Scrape" jobId={r.asik_scrape_job_id} />
          <ChildMergeJobRow label="Merge" jobId={r.merge_job_id} />
          <SyncStepRow runId={r.id} />
        </div>
      </div>

      <ConfirmDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        title="Cancel this cron run?"
        description="The currently running scrape or merge step will be cancelled. Downstream steps will not run."
        confirmLabel="Cancel run"
        destructive
        loading={cancel.isPending}
        onConfirm={onCancel}
      />
    </div>
  );
}

/** The SYNC step has no single child job — it fans out to one SyncJob per
 * patient — so it shows aggregate progress instead of a job link. Before the
 * step starts `total` is null and the row reads "Not started", matching how the
 * scrape/merge rows render a null job id. */
function SyncStepRow({ runId }: { runId: string }) {
  const summary = useCronRunSyncSummary(runId);
  const s = summary.data;
  const done = s ? s.success + s.failed + s.cancelled : 0;
  return (
    <div className="flex items-center justify-between rounded-md border border-[var(--border)] p-3">
      <div className="min-w-0">
        <p className="text-sm font-medium">ASIK Sync</p>
        <p className="truncate text-xs text-[var(--muted-foreground)]">
          {s && s.total !== null
            ? `${done}/${s.total} patients${s.failed ? ` · ${s.failed} failed` : ""}${
                s.running ? ` · ${s.running} running` : ""
              }`
            : "Not started"}
        </p>
      </div>
      {/* No "Open" link: the sync-jobs list has no cron_run_id filter, so it
          would land on an unfiltered list rather than this run's jobs. */}
      <span className="text-xs text-[var(--muted-foreground)]">
        {s && s.total !== null && done >= s.total ? "Done" : "—"}
      </span>
    </div>
  );
}

function ChildScrapeJobRow({
  label,
  jobId,
}: {
  label: string;
  jobId: string | null;
}) {
  const job = useScrapeJob(jobId ?? undefined);
  return (
    <div className="flex items-center justify-between rounded-md border border-[var(--border)] p-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium">{label}</p>
          {job.data ? <ScrapeStatusBadge status={job.data.status} /> : null}
        </div>
        <p className="truncate text-xs text-[var(--muted-foreground)]">
          {jobId ?? "Not started"}
        </p>
      </div>
      {jobId ? (
        <Button variant="ghost" size="sm" asChild>
          <Link href={`/scrape-jobs/${jobId}`} prefetch={false}>
            Open
          </Link>
        </Button>
      ) : (
        <span className="text-xs text-[var(--muted-foreground)]">—</span>
      )}
    </div>
  );
}

function ChildMergeJobRow({
  label,
  jobId,
}: {
  label: string;
  jobId: string | null;
}) {
  const job = useMergeJob(jobId ?? undefined);
  return (
    <div className="flex items-center justify-between rounded-md border border-[var(--border)] p-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium">{label}</p>
          {job.data ? <MergeStatusBadge status={job.data.status} /> : null}
        </div>
        <p className="truncate text-xs text-[var(--muted-foreground)]">
          {jobId ?? "Not started"}
        </p>
      </div>
      {jobId ? (
        <Button variant="ghost" size="sm" asChild>
          <Link href={`/merge-with-ai/${jobId}`} prefetch={false}>
            Open
          </Link>
        </Button>
      ) : (
        <span className="text-xs text-[var(--muted-foreground)]">—</span>
      )}
    </div>
  );
}
