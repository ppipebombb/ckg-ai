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
import { SyncStatusBadge } from "@/components/sync/sync-status-badge";
import { useSyncJobsListStore } from "@/lib/stores/sync-jobs-list-store";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import { useSyncJobList } from "@/lib/hooks/use-sync";
import type { SyncStatus } from "@/lib/api/types";

const STATUSES: SyncStatus[] = [
  "pending",
  "running",
  "success",
  "failed",
  "cancelled",
];

export default function SyncJobsPage() {
  const puskesmasId = useSyncJobsListStore((s) => s.puskesmasId);
  const status = useSyncJobsListStore((s) => s.status);
  const page = useSyncJobsListStore((s) => s.page);
  const setPuskesmasId = useSyncJobsListStore((s) => s.setPuskesmasId);
  const setStatus = useSyncJobsListStore((s) => s.setStatus);
  const setPage = useSyncJobsListStore((s) => s.setPage);

  const pkDetail = usePuskesmas(puskesmasId || undefined);
  const query = useMemo(
    () => ({
      page,
      size: 20,
      puskesmas_id: puskesmasId || undefined,
      status: (status || undefined) as SyncStatus | undefined,
    }),
    [page, puskesmasId, status],
  );
  const jobs = useSyncJobList(query);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Sync Jobs"
        description="History of ASIK form-fill sync jobs."
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label>Puskesmas</Label>
          <AsyncCombobox
            value={puskesmasId || undefined}
            onChange={(v) => setPuskesmasId(v ?? "")}
            useOptions={usePuskesmasOptions}
            selectedLabel={pkDetail.data?.name}
            placeholder="Select a puskesmas…"
            allOptionLabel="All puskesmas"
          />
        </div>
        <div className="space-y-2">
          <Label>Status</Label>
          <Select
            value={status || "all"}
            onValueChange={(v) =>
              setStatus(v === "all" ? "" : (v as SyncStatus))
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

      {jobs.error && <ErrorState error={jobs.error} />}

      {jobs.data && (
        <>
          <div className="rounded-lg border border-[var(--border)]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Patient</TableHead>
                  <TableHead>Puskesmas</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Forms</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.data.items.map((j) => (
                  <TableRow key={j.id}>
                    <TableCell>
                      <div className="font-medium">{j.patient_name}</div>
                      <div className="font-mono text-xs text-[var(--muted-foreground)]">
                        NIK {j.patient_nik}
                      </div>
                    </TableCell>
                    <TableCell>{j.puskesmas_name}</TableCell>
                    <TableCell>
                      <SyncStatusBadge status={j.status} />
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {j.forms_succeeded ?? "—"}/{j.forms_total ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs text-[var(--muted-foreground)]">
                      {j.started_at
                        ? format(parseISO(j.started_at), "yyyy-MM-dd HH:mm")
                        : "—"}
                    </TableCell>
                    <TableCell>
                      <Button variant="ghost" size="sm" asChild>
                        <Link href={`/sync-jobs/${j.id}`} prefetch={false}>
                          Open
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {jobs.data.items.length === 0 && (
              <div className="p-6">
                <EmptyState title="No sync jobs" />
              </div>
            )}
          </div>
          <Pagination
            page={jobs.data.page}
            pages={jobs.data.pages}
            total={jobs.data.total}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
