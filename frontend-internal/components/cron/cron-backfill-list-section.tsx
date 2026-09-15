"use client";

import { useMemo, useState } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Tabs,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Pagination } from "@/components/common/pagination";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { CronBackfillStatusBadge } from "@/components/cron/cron-backfill-status-badge";
import { CronBackfillFormDialog } from "@/components/cron/cron-backfill-form-dialog";
import { CronBackfillDetailDialog } from "@/components/cron/cron-backfill-detail-dialog";
import {
  useCancelCronBackfill,
  useCronBackfillList,
} from "@/lib/hooks/use-cron-backfill";
import { asApiError } from "@/lib/api/client";
import type {
  CronBackfill,
  CronBackfillStatus,
  CronSourceScopeT,
} from "@/lib/api/types";

const ACTIVE_STATUSES: CronBackfillStatus[] = ["pending", "running"];

const SOURCE_SCOPE_LABEL: Record<CronSourceScopeT, string> = {
  both: "EPUS + ASIK",
  epus_only: "EPUS only",
  asik_only: "ASIK only",
  none: "Sync only (no rescrape)",
};

type Tab = "active" | "all";

export function CronBackfillListSection() {
  const [tab, setTab] = useState<Tab>("active");
  const [page, setPage] = useState(1);
  const [formOpen, setFormOpen] = useState(false);
  const [detailFor, setDetailFor] = useState<CronBackfill | null>(null);
  const [cancelFor, setCancelFor] = useState<CronBackfill | null>(null);

  const cancel = useCancelCronBackfill();

  // Active tab fires two queries (one per status) since the server filter is
  // single-status. Pagination on this tab is intentionally disabled (pages=1
  // below): pending always pins to page 1 and active backfills are expected
  // to be small (UI guard: one active backfill per puskesmas). The All tab
  // owns real pagination via `page`.
  const activeRunning = useCronBackfillList(
    { page: 1, size: 10, status: "running" },
    tab === "active",
  );
  const activePending = useCronBackfillList(
    { page: 1, size: 10, status: "pending" },
    tab === "active",
  );
  const allList = useCronBackfillList({ page, size: 10 }, tab === "all");

  const items = useMemo<CronBackfill[]>(() => {
    if (tab === "active") {
      const running = activeRunning.data?.items ?? [];
      const pending = activePending.data?.items ?? [];
      // running first, then pending; de-dupe by id just in case.
      const seen = new Set<string>();
      return [...running, ...pending].filter((b) => {
        if (seen.has(b.id)) return false;
        seen.add(b.id);
        return true;
      });
    }
    return allList.data?.items ?? [];
  }, [tab, activeRunning.data, activePending.data, allList.data]);

  const total =
    tab === "active"
      ? (activeRunning.data?.total ?? 0) + (activePending.data?.total ?? 0)
      : (allList.data?.total ?? 0);
  const pages = tab === "active" ? 1 : (allList.data?.pages ?? 0);
  const error = tab === "active"
    ? activeRunning.error || activePending.error
    : allList.error;

  const onCancelConfirm = async () => {
    if (!cancelFor) return;
    try {
      await cancel.mutateAsync(cancelFor.id);
      toast.success("Backfill cancelled");
      setCancelFor(null);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Date-range backfills</h2>
          <p className="text-sm text-[var(--muted-foreground)]">
            Run the cron pipeline (ASIK → EPUS → Merge) forward across a
            range of dates for one puskesmas.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Tabs value={tab} onValueChange={(v) => {
            setTab(v as Tab);
            setPage(1);
          }}>
            <TabsList>
              <TabsTrigger value="active">Active</TabsTrigger>
              <TabsTrigger value="all">All</TabsTrigger>
            </TabsList>
          </Tabs>
          <Button onClick={() => setFormOpen(true)}>
            <Plus className="h-4 w-4" />
            Run for date range
          </Button>
        </div>
      </div>

      {error && <ErrorState error={error} />}

      <div className="rounded-lg border border-[var(--border)] max-h-[60vh] overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Puskesmas</TableHead>
              <TableHead>Range</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Progress</TableHead>
              <TableHead>Cursor</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((b) => {
              const isActive = ACTIVE_STATUSES.includes(b.status);
              return (
                <TableRow key={b.id}>
                  <TableCell className="font-medium">
                    {b.puskesmas_name}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs">
                    {b.date_from} → {b.date_to}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs">
                    {b.mandiri_only
                      ? "Mandiri (ASIK)"
                      : SOURCE_SCOPE_LABEL[b.source_scope]}
                  </TableCell>
                  <TableCell className="text-xs">
                    {b.completed_dates}/{b.total_dates}
                  </TableCell>
                  <TableCell className="text-xs">
                    {b.cursor_date ?? "—"}
                  </TableCell>
                  <TableCell>
                    <CronBackfillStatusBadge status={b.status} />
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDetailFor(b)}
                      >
                        View runs
                      </Button>
                      {isActive && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setCancelFor(b)}
                        >
                          Cancel
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        {items.length === 0 && (
          <div className="p-6">
            <EmptyState
              title={
                tab === "active"
                  ? "No active backfills"
                  : "No backfills yet"
              }
            />
          </div>
        )}
      </div>

      {tab === "all" && allList.data && (
        <Pagination
          page={allList.data.page}
          pages={pages}
          total={total}
          onPageChange={setPage}
        />
      )}

      <CronBackfillFormDialog open={formOpen} onOpenChange={setFormOpen} />
      <CronBackfillDetailDialog
        open={!!detailFor}
        onOpenChange={(v) => !v && setDetailFor(null)}
        backfill={detailFor}
      />
      <ConfirmDialog
        open={!!cancelFor}
        onOpenChange={(v) => !v && setCancelFor(null)}
        title="Cancel backfill?"
        description={
          cancelFor
            ? `Stops the backfill for ${cancelFor.puskesmas_name}. Already-completed dates' data is preserved.`
            : ""
        }
        confirmLabel="Cancel backfill"
        destructive
        loading={cancel.isPending}
        onConfirm={onCancelConfirm}
      />
    </div>
  );
}
