"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, Ban, ExternalLink, GitPullRequest } from "lucide-react";
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
import { LoopStatusBadge } from "@/components/loop/loop-status-badge";
import { LoopLogStream, LoopLogHistory } from "@/components/loop/loop-log-stream";
import { useCancelLoopRun, useLoopRun, useOpenLoopRunPr } from "@/lib/hooks/use-loop";
import { asApiError } from "@/lib/api/client";
import type { LoopCoverageFindingType } from "@/lib/api/types";

export default function LoopRunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const run = useLoopRun(id);
  const cancel = useCancelLoopRun();
  const openPr = useOpenLoopRunPr();

  const handleCancel = async () => {
    try {
      await cancel.mutateAsync(id);
      toast.success("Run dibatalkan");
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const handleOpenPr = async () => {
    try {
      const updated = await openPr.mutateAsync(id);
      toast.success(`PR dibuka: ${updated.pr_url}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  if (run.error) return <ErrorState error={run.error} />;

  const live = run.data?.status === "pending" || run.data?.status === "running";

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="h-8 -ml-2 px-2">
        <Link href="/loop-runs" prefetch={false}>
          <ArrowLeft className="h-4 w-4" />
          Kembali
        </Link>
      </Button>

      <PageHeader
        title="Loop run"
        description={
          run.data
            ? `${run.data.puskesmas_name}${run.data.test_date ? ` • ${run.data.test_date}` : ""}${run.data.pin_ref ? ` • pin ${run.data.pin_ref}` : ""}`
            : "Memuat…"
        }
        actions={
          <div className="flex gap-2">
            {run.data?.status === "changes_ready" && !run.data?.pr_url && (
              <Button onClick={handleOpenPr} disabled={openPr.isPending}>
                <GitPullRequest className="h-4 w-4" />
                {openPr.isPending ? "Membuka…" : "Buat PR"}
              </Button>
            )}
            {run.data?.pr_url && (
              <Button variant="outline" asChild>
                <a href={run.data.pr_url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="h-4 w-4" />
                  Buka PR
                </a>
              </Button>
            )}
            {live && (
              <Button
                variant="destructive"
                onClick={handleCancel}
                disabled={cancel.isPending}
              >
                <Ban className="h-4 w-4" />
                Batalkan
              </Button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">Status</CardTitle>
          </CardHeader>
          <CardContent>
            {run.data ? <LoopStatusBadge status={run.data.status} /> : "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">Live count</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {run.data?.live_count ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">Scraped count</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {run.data?.scraped_count ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">Tanggal uji</CardTitle>
          </CardHeader>
          <CardContent className="text-sm font-semibold tabular-nums">
            {run.data?.test_date ?? "—"}
          </CardContent>
        </Card>
      </div>

      {run.data?.gap_summary && (
        <div className="rounded-md border border-[var(--border)] bg-[var(--muted)]/30 p-3 text-sm">
          <p className="text-xs font-medium text-[var(--muted-foreground)]">
            Laporan pemeriksaan (agent vs situs live)
          </p>
          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap font-mono text-xs">
            {run.data.gap_summary}
          </pre>
        </div>
      )}

      <CoverageFindings findings={run.data?.coverage_findings} />

      {run.data?.review_comments && (
        <div className="rounded-md border border-[var(--border)] bg-[var(--muted)]/30 p-3 text-sm">
          <p className="text-xs font-medium text-[var(--muted-foreground)]">
            Review ({run.data.review_verdict ?? "none"})
          </p>
          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap font-mono text-xs">
            {run.data.review_comments}
          </pre>
        </div>
      )}

      {run.data?.error_message && (
        <div className="rounded-md border border-[var(--destructive)]/40 bg-[var(--destructive)]/10 p-3 text-sm text-[var(--destructive)]">
          <p className="font-medium">Error</p>
          <p className="font-mono text-xs">{run.data.error_message}</p>
        </div>
      )}

      {live ? (
        <LoopLogStream runId={id} enabled={live} />
      ) : run.data ? (
        <LoopLogHistory runId={id} />
      ) : null}

      {run.data && (
        <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
          <Meta label="Trigger" value={run.data.trigger} />
          <Meta label="Branch" value={run.data.branch_name ?? "—"} />
          <Meta label="Dimulai" value={fmt(run.data.started_at)} />
          <Meta label="Selesai" value={fmt(run.data.finished_at)} />
          <Meta label="Heartbeat" value={fmt(run.data.heartbeat_at)} />
          <Meta label="Container" value={run.data.container_name ?? "—"} />
          <Meta label="Celery task" value={run.data.celery_task_id ?? "—"} />
          <Meta label="Pin ref" value={run.data.pin_ref ?? "—"} />
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

const COVERAGE_LABEL: Record<string, string> = {
  mapped: "Terpetakan",
  absent: "Tidak ada di portal",
  candidate: "Kandidat",
};

function CoverageFindings({
  findings,
}: {
  findings: LoopCoverageFindingType[] | null | undefined;
}) {
  if (findings == null) return null;
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--muted)]/30 p-3 text-sm">
      <p className="text-xs font-medium text-[var(--muted-foreground)]">
        Temuan cakupan ASIK (
        {findings.length === 0
          ? "diperiksa, tidak ada temuan"
          : `${findings.length} temuan`}
        )
      </p>
      {findings.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {findings.map((f, i) => (
            <li key={i} className="text-xs leading-relaxed">
              <span className="font-medium">
                {COVERAGE_LABEL[(f.status ?? "").toLowerCase()] ?? f.status} ·{" "}
                {f.form ?? "?"}
              </span>
              {f.off_list && (
                <span className="ml-1 text-[var(--muted-foreground)]">
                  (di luar daftar)
                </span>
              )}
              {f.questions && f.questions.length > 0 && (
                <span className="text-[var(--muted-foreground)]">
                  {" "}
                  — {f.questions.join("; ")}
                </span>
              )}
              {f.epus_source && (
                <span className="block font-mono text-[10px] text-[var(--muted-foreground)]">
                  ← {f.epus_source}
                </span>
              )}
              {f.tabs_checked && f.tabs_checked.length > 0 && (
                <span className="block font-mono text-[10px] text-[var(--muted-foreground)]">
                  tab: {f.tabs_checked.join(", ")}
                </span>
              )}
              {f.evidence && (
                <span className="block text-[10px] text-[var(--muted-foreground)]">
                  {f.evidence}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
