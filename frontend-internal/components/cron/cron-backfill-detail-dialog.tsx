"use client";

import Link from "next/link";
import { useState } from "react";
import { format, parseISO } from "date-fns";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CronRunStatusBadge } from "@/components/cron/cron-run-status-badge";
import { CronBackfillStatusBadge } from "@/components/cron/cron-backfill-status-badge";
import { Pagination } from "@/components/common/pagination";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { useCronBackfillChildRuns } from "@/lib/hooks/use-cron-backfill";
import type { CronBackfill } from "@/lib/api/types";

export function CronBackfillDetailDialog({
  open,
  onOpenChange,
  backfill,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  backfill: CronBackfill | null;
}) {
  const [page, setPage] = useState(1);
  const runs = useCronBackfillChildRuns(
    backfill?.id,
    { page, size: 50 },
    open && !!backfill,
  );

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) setPage(1);
        onOpenChange(v);
      }}
    >
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {backfill
              ? `Backfill: ${backfill.puskesmas_name}`
              : "Backfill"}
          </DialogTitle>
          <DialogDescription>
            {backfill
              ? `${backfill.date_from} → ${backfill.date_to} · ${backfill.completed_dates}/${backfill.total_dates} completed`
              : ""}
          </DialogDescription>
        </DialogHeader>

        {backfill && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3 text-sm text-[var(--muted-foreground)]">
              <CronBackfillStatusBadge status={backfill.status} />
              {backfill.cursor_date && (
                <span>Cursor: {backfill.cursor_date}</span>
              )}
              {backfill.failed_date && (
                <span className="text-[var(--destructive)]">
                  Failed on {backfill.failed_date}
                </span>
              )}
              {backfill.mandiri_only && (
                <span>Pemeriksaan Mandiri only (ASIK)</span>
              )}
              {!backfill.mandiri_only &&
                backfill.source_scope === "epus_only" && (
                  <span>EPUS only</span>
                )}
              {!backfill.mandiri_only &&
                backfill.source_scope === "asik_only" && (
                  <span>ASIK only</span>
                )}
              {backfill.source_scope === "none" && (
                <span>Sync only (no rescrape)</span>
              )}
              {backfill.merge_mode === "force_remerge" && (
                <span>Force re-merge</span>
              )}
              {backfill.merge_mode === "no_merge" && (
                <span>No merge (scrape only)</span>
              )}
              {backfill.sync_mode !== "off" && (
                <span>
                  Create missing
                  {backfill.sync_mode === "force_resync" ? " (force)" : ""}
                </span>
              )}
              {backfill.create_new && <span>Create new</span>}
            </div>
            {backfill.error_message && (
              <div className="rounded border border-[var(--border)] bg-[var(--muted)] p-2 text-xs">
                {backfill.error_message}
              </div>
            )}
          </div>
        )}

        {runs.error && <ErrorState error={runs.error} />}

        {runs.data && (
          <>
            <div className="rounded-lg border border-[var(--border)]">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Step</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.data.items.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell>{r.target_date}</TableCell>
                      <TableCell>
                        <CronRunStatusBadge status={r.status} />
                      </TableCell>
                      <TableCell className="text-xs uppercase text-[var(--muted-foreground)]">
                        {r.status === "failed" && r.failed_step
                          ? `${r.failed_step} (failed)`
                          : r.current_step
                            ? `${r.current_step} (try ${r.current_step_attempt})`
                            : "—"}
                      </TableCell>
                      <TableCell className="text-xs text-[var(--muted-foreground)]">
                        {r.started_at
                          ? format(parseISO(r.started_at), "yyyy-MM-dd HH:mm")
                          : "—"}
                      </TableCell>
                      <TableCell>
                        <Button variant="ghost" size="sm" asChild>
                          <Link
                            href={`/cron-runs/${r.id}`}
                            prefetch={false}
                          >
                            Open
                          </Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {runs.data.items.length === 0 && (
                <div className="p-6">
                  <EmptyState title="No runs yet" />
                </div>
              )}
            </div>
            <Pagination
              page={runs.data.page}
              pages={runs.data.pages}
              total={runs.data.total}
              onPageChange={setPage}
            />
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
