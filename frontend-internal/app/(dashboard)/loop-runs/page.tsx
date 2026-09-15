"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Bot, RefreshCw, Settings } from "lucide-react";
import { format, parseISO } from "date-fns";
import { toast } from "sonner";
import { useLoopRunsListStore } from "@/lib/stores/loop-runs-list-store";
import { PageHeader } from "@/components/common/page-header";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
import { LoopStatusBadge } from "@/components/loop/loop-status-badge";
import { StartLoopDialog } from "@/components/loop/start-loop-dialog";
import { LoopSettingsDialog } from "@/components/loop/loop-settings-dialog";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import {
  useLoopConfig,
  useLoopCoverageSummary,
  useLoopRunList,
  useLoopSummary,
  useReconcileLoopPrs,
} from "@/lib/hooks/use-loop";
import { asApiError } from "@/lib/api/client";
import type {
  LoopStatusFilter,
  LoopTriggerFilter,
} from "@/lib/stores/loop-runs-list-store";

function Glance({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[var(--muted-foreground)]">{label}:</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

export default function LoopRunsPage() {
  const puskesmasId = useLoopRunsListStore((s) => s.puskesmasId);
  const page = useLoopRunsListStore((s) => s.page);
  const status = useLoopRunsListStore((s) => s.status);
  const trigger = useLoopRunsListStore((s) => s.trigger);
  const needsAction = useLoopRunsListStore((s) => s.needsAction);
  const setPuskesmasId = useLoopRunsListStore((s) => s.setPuskesmasId);
  const setPage = useLoopRunsListStore((s) => s.setPage);
  const setStatus = useLoopRunsListStore((s) => s.setStatus);
  const setTrigger = useLoopRunsListStore((s) => s.setTrigger);
  const setNeedsAction = useLoopRunsListStore((s) => s.setNeedsAction);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const pkDetail = usePuskesmas(puskesmasId || undefined);
  const cfg = useLoopConfig(true);
  const summary = useLoopSummary();
  const coverage = useLoopCoverageSummary();
  const reconcile = useReconcileLoopPrs();

  const query = useMemo(
    () => ({
      page,
      size: 20,
      puskesmas_id: puskesmasId || undefined,
      status: status === "all" ? undefined : status,
      trigger: trigger === "all" ? undefined : trigger,
      needs_action: needsAction || undefined,
    }),
    [page, puskesmasId, status, trigger, needsAction],
  );
  const runs = useLoopRunList(query);

  const handleReconcile = async () => {
    try {
      const r = await reconcile.mutateAsync();
      toast.success(
        `Diperiksa ${r.checked} PR — ${r.merged} merged, ${r.rejected} ditolak`,
      );
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const needsActionCount = summary.data?.needs_action ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Loop Agent"
        actions={
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={handleReconcile}
              disabled={reconcile.isPending}
            >
              <RefreshCw className="h-4 w-4" />
              Segarkan status PR
            </Button>
            <Button variant="outline" onClick={() => setSettingsOpen(true)}>
              <Settings className="h-4 w-4" />
              Pengaturan
            </Button>
            <Button onClick={() => setDialogOpen(true)}>
              <Bot className="h-4 w-4" />
              Jalankan
            </Button>
          </div>
        }
      />

      {cfg.data && (
        <div className="flex flex-wrap gap-x-6 gap-y-1 rounded-md border border-[var(--border)] bg-[var(--muted)]/30 px-3 py-2 text-xs">
          <Glance
            label="Jadwal malam"
            value={cfg.data.nightly_enabled ? "Aktif · 00:00 WIB" : "Nonaktif"}
          />
          <Glance
            label="Merge"
            value={cfg.data.merge_mode === "manual" ? "Manual" : "Otomatis"}
          />
          <Glance label="Maks perbaikan" value={String(cfg.data.max_fix_iterations)} />
          <Glance label="Maks review" value={String(cfg.data.max_review_iterations)} />
          <Glance label="Puskesmas/malam" value={String(cfg.data.nightly_budget)} />
        </div>
      )}

      {coverage.data && (
        <div className="flex flex-wrap gap-x-6 gap-y-1 rounded-md border border-[var(--border)] bg-[var(--muted)]/30 px-3 py-2 text-xs">
          <Glance
            label="Cakupan ASIK"
            value={`${coverage.data.mapped}/${coverage.data.total_questions} terpetakan`}
          />
          <Glance label="Terbuka (buruan)" value={String(coverage.data.open)} />
          <Glance
            label="Terbukti tanpa sumber"
            value={String(coverage.data.documented_sourceless)}
          />
          <Glance
            label="Run dengan temuan"
            value={String(coverage.data.runs_with_findings)}
          />
          <Glance
            label="Form dilaporkan kosong"
            value={String(coverage.data.forms_reported_absent)}
          />
        </div>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full max-w-sm space-y-2">
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
        <div className="w-52 space-y-2">
          <Label>Status</Label>
          <Select
            value={status}
            onValueChange={(v) => setStatus(v as LoopStatusFilter)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Semua</SelectItem>
              <SelectItem value="running">Berjalan</SelectItem>
              <SelectItem value="covered">Covered</SelectItem>
              <SelectItem value="no_data">Tidak ada data</SelectItem>
              <SelectItem value="needs_review">Perlu review</SelectItem>
              <SelectItem value="merged">Merged</SelectItem>
              <SelectItem value="pr_rejected">PR ditolak</SelectItem>
              <SelectItem value="changes_ready">Perubahan siap</SelectItem>
              <SelectItem value="bad_creds">Kredensial buruk</SelectItem>
              <SelectItem value="failed">Gagal</SelectItem>
              <SelectItem value="cancelled">Dibatalkan</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="w-40 space-y-2">
          <Label>Trigger</Label>
          <Select
            value={trigger}
            onValueChange={(v) => setTrigger(v as LoopTriggerFilter)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Semua</SelectItem>
              <SelectItem value="manual">Manual</SelectItem>
              <SelectItem value="nightly">Malam</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label className="block">&nbsp;</Label>
          <Button
            variant={needsAction ? "default" : "outline"}
            onClick={() => setNeedsAction(!needsAction)}
          >
            Perlu tindakan
            {needsActionCount > 0 && (
              <Badge variant="secondary" className="ml-1">
                {needsActionCount}
              </Badge>
            )}
          </Button>
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
                  <TableHead>Status</TableHead>
                  <TableHead>Live / Scraped</TableHead>
                  <TableHead>Temuan</TableHead>
                  <TableHead>PR</TableHead>
                  <TableHead>Trigger</TableHead>
                  <TableHead>Dimulai</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.data.items.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-medium">
                      {r.puskesmas_name}
                    </TableCell>
                    <TableCell>
                      <LoopStatusBadge status={r.status} />
                    </TableCell>
                    <TableCell className="text-xs tabular-nums text-[var(--muted-foreground)]">
                      {r.live_count != null || r.scraped_count != null
                        ? `${r.live_count ?? "—"} / ${r.scraped_count ?? "—"}`
                        : "—"}
                    </TableCell>
                    <TableCell className="max-w-xs truncate text-xs text-[var(--muted-foreground)]">
                      {r.gap_summary?.split("\n")[0] ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs">
                      {r.pr_url ? (
                        <a
                          href={r.pr_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[var(--primary)] underline"
                        >
                          PR
                        </a>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-[var(--muted-foreground)]">
                      {r.trigger}
                    </TableCell>
                    <TableCell className="text-xs text-[var(--muted-foreground)]">
                      {r.started_at
                        ? format(parseISO(r.started_at), "yyyy-MM-dd HH:mm")
                        : "—"}
                    </TableCell>
                    <TableCell>
                      <Button variant="ghost" size="sm" asChild>
                        <Link href={`/loop-runs/${r.id}`} prefetch={false}>
                          Buka
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {runs.data.items.length === 0 && (
              <div className="p-6">
                <EmptyState title="Belum ada loop run" />
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

      <StartLoopDialog open={dialogOpen} onOpenChange={setDialogOpen} />
      <LoopSettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  );
}
