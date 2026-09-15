"use client";

import Link from "next/link";
import { useMemo } from "react";
import { format, parseISO } from "date-fns";
import { PageHeader } from "@/components/common/page-header";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Pagination } from "@/components/common/pagination";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { CronRunStatusBadge } from "@/components/cron/cron-run-status-badge";
import { CronBackfillListSection } from "@/components/cron/cron-backfill-list-section";
import { useCronRunsListStore } from "@/lib/stores/cron-runs-list-store";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import { useCronRunList } from "@/lib/hooks/use-cron-runs";
import type { CronRunStatus } from "@/lib/api/types";

const STATUSES: CronRunStatus[] = [
  "pending",
  "running",
  "success",
  "failed",
  "cancelled",
];

export default function CronRunsPage() {
  const puskesmasId = useCronRunsListStore((s) => s.puskesmasId);
  const status = useCronRunsListStore((s) => s.status);
  const page = useCronRunsListStore((s) => s.page);
  const setPuskesmasId = useCronRunsListStore((s) => s.setPuskesmasId);
  const setStatus = useCronRunsListStore((s) => s.setStatus);
  const setPage = useCronRunsListStore((s) => s.setPage);

  const pkDetail = usePuskesmas(puskesmasId || undefined);
  const query = useMemo(
    () => ({
      page,
      size: 20,
      puskesmas_id: puskesmasId || undefined,
      status: (status || undefined) as CronRunStatus | undefined,
    }),
    [page, puskesmasId, status],
  );
  const runs = useCronRunList(query);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Cron Runs"
        description="Riwayat cron terjadwal dan on-demand."
      />

      <CronBackfillListSection />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label>Puskesmas</Label>
          <AsyncCombobox
            value={puskesmasId || undefined}
            onChange={(v) => setPuskesmasId(v ?? "")}
            useOptions={usePuskesmasOptions}
            selectedLabel={pkDetail.data?.name}
            placeholder="Pilih puskesmas…"
            allOptionLabel="Semua puskesmas"
          />
        </div>
        <div className="space-y-2">
          <Label>Status</Label>
          <Select
            value={status || "all"}
            onValueChange={(v) =>
              setStatus(v === "all" ? "" : (v as CronRunStatus))
            }
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {runs.error && <ErrorState error={runs.error} />}

      {runs.data && (
        <>
          <div className="rounded-lg border border-[var(--border)]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Puskesmas</TableHead>
                  <TableHead>Target date</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Step</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.data.items.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-medium">
                      {r.puskesmas_name}
                    </TableCell>
                    <TableCell>{r.target_date}</TableCell>
                    <TableCell>
                      <CronRunStatusBadge status={r.status} />
                    </TableCell>
                    <TableCell className="text-xs text-[var(--muted-foreground)] uppercase">
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
                        <Link href={`/cron-runs/${r.id}`} prefetch={false}>
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
                <EmptyState title="No cron runs" />
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
    </div>
  );
}
