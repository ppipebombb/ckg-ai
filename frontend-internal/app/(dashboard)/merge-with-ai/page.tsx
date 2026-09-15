"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { format, parseISO } from "date-fns";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/page-header";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Pagination } from "@/components/common/pagination";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { MergeStatusBadge } from "@/components/merge/merge-status-badge";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import {
  useMergeJobList,
  useMergePreview,
  useStartMerge,
} from "@/lib/hooks/use-merge";
import { useMergeJobsListStore } from "@/lib/stores/merge-jobs-list-store";
import { asApiError } from "@/lib/api/client";
import type { MergeJobScope } from "@/lib/api/merge";
import type { MergeStatus } from "@/lib/api/types";

function todayISO(): string {
  return format(new Date(), "yyyy-MM-dd");
}

export default function MergeWithAiPage() {
  const router = useRouter();

  const [startPuskesmasId, setStartPuskesmasId] = useState<string>("");
  const [rangeMode, setRangeMode] = useState<boolean>(false);
  const [startDate, setStartDate] = useState<string>(todayISO());
  const [dateFrom, setDateFrom] = useState<string>(todayISO());
  const [dateTo, setDateTo] = useState<string>(todayISO());
  const [force, setForce] = useState<boolean>(false);

  const startPkDetail = usePuskesmas(startPuskesmasId || undefined);
  // Preview is single-date only — skip in range mode.
  const preview = useMergePreview(
    rangeMode ? undefined : startPuskesmasId || undefined,
    rangeMode ? undefined : startDate || undefined,
  );
  const startMerge = useStartMerge(startPuskesmasId);

  const handleStart = async () => {
    if (!startPuskesmasId) return;
    try {
      if (rangeMode) {
        if (!dateFrom || !dateTo) return;
        const jobs = await startMerge.mutateAsync({
          date_from: dateFrom,
          date_to: dateTo,
          force,
        });
        toast.success(
          `${jobs.length} job merge dimulai (${dateFrom} → ${dateTo})`,
        );
        // Don't navigate — N jobs run sequentially; user watches list.
      } else {
        if (!startDate) return;
        const jobs = await startMerge.mutateAsync({ date: startDate, force });
        toast.success("Job merge dimulai");
        if (jobs[0]) router.push(`/merge-with-ai/${jobs[0].id}`);
      }
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const matched = preview.data?.matched_count ?? 0;
  const pending = preview.data?.pending_count ?? 0;
  const already = preview.data?.already_merged_count ?? 0;
  const buttonDisabled =
    !startPuskesmasId ||
    startMerge.isPending ||
    (rangeMode
      ? !dateFrom || !dateTo || dateFrom > dateTo
      : !startDate ||
        preview.isLoading ||
        (!force && pending === 0) ||
        (force && matched === 0));

  // List section state
  const page = useMergeJobsListStore((s) => s.page);
  const puskesmasId = useMergeJobsListStore((s) => s.puskesmasId);
  const dateFilter = useMergeJobsListStore((s) => s.dateFilter);
  const status = useMergeJobsListStore((s) => s.status);
  const scope = useMergeJobsListStore((s) => s.scope);
  const setPage = useMergeJobsListStore((s) => s.setPage);
  const setPuskesmasId = useMergeJobsListStore((s) => s.setPuskesmasId);
  const setDateFilter = useMergeJobsListStore((s) => s.setDateFilter);
  const setStatus = useMergeJobsListStore((s) => s.setStatus);
  const setScope = useMergeJobsListStore((s) => s.setScope);

  const filterPkDetail = usePuskesmas(puskesmasId || undefined);
  const query = useMemo(
    () => ({
      page,
      size: 20,
      puskesmas_id: puskesmasId || undefined,
      date_filter: dateFilter || undefined,
      status: (status as MergeStatus) || undefined,
      scope,
    }),
    [page, puskesmasId, dateFilter, status, scope],
  );
  const jobs = useMergeJobList(query);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Merge With AI"
        description="Jalankan LLM aktif pada pasien yang cocok untuk menghasilkan satu rekaman gabungan per pasien."
      />

      <Card>
        <CardHeader>
          <CardTitle>Mulai job merge</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-4">
            <div className="w-72 space-y-1">
              <Label>Puskesmas</Label>
              <AsyncCombobox
                value={startPuskesmasId || undefined}
                onChange={(v) => setStartPuskesmasId(v ?? "")}
                useOptions={usePuskesmasOptions}
                selectedLabel={startPkDetail.data?.name}
                placeholder="Pilih puskesmas…"
              />
            </div>
            {rangeMode ? (
              <>
                <div className="w-44 space-y-1">
                  <Label>Tanggal dari</Label>
                  <Input
                    type="date"
                    value={dateFrom}
                    onChange={(e) => setDateFrom(e.target.value)}
                  />
                </div>
                <div className="w-44 space-y-1">
                  <Label>Tanggal sampai</Label>
                  <Input
                    type="date"
                    value={dateTo}
                    onChange={(e) => setDateTo(e.target.value)}
                  />
                </div>
              </>
            ) : (
              <div className="w-44 space-y-1">
                <Label>Tanggal</Label>
                <Input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                />
              </div>
            )}
            <div className="flex items-center gap-2 pb-1">
              <Switch
                id="merge-range"
                checked={rangeMode}
                onCheckedChange={setRangeMode}
              />
              <Label htmlFor="merge-range" className="cursor-pointer">
                Rentang tanggal
              </Label>
            </div>
            <div className="flex items-center gap-2 pb-1">
              <Switch
                id="merge-force"
                checked={force}
                onCheckedChange={setForce}
              />
              <Label htmlFor="merge-force" className="cursor-pointer">
                Paksa merge ulang
              </Label>
            </div>
            <Button onClick={handleStart} disabled={buttonDisabled}>
              {startMerge.isPending ? "Memulai…" : "Merge With AI"}
            </Button>
          </div>

          <div className="text-sm text-[var(--muted-foreground)]">
            {rangeMode ? (
              !startPuskesmasId || !dateFrom || !dateTo ? (
                "Pilih puskesmas dan rentang tanggal. Satu job merge akan dibuat per hari dan dijalankan berurutan."
              ) : dateFrom > dateTo ? (
                <span className="text-[var(--destructive)]">
                  Tanggal dari harus sama dengan atau sebelum Tanggal sampai.
                </span>
              ) : (
                <>
                  Akan membuat{" "}
                  <span className="font-medium">
                    {Math.round(
                      (Date.parse(dateTo) - Date.parse(dateFrom)) /
                        86_400_000,
                    ) + 1}
                  </span>{" "}
                  job merge, satu per hari dari {dateFrom} sampai {dateTo},
                  dijalankan berurutan. Hari tanpa pasien yang cocok selesai
                  seketika.
                </>
              )
            ) : !startPuskesmasId || !startDate ? (
              "Pilih puskesmas dan tanggal untuk melihat berapa banyak pasien yang cocok dan memenuhi syarat."
            ) : preview.isLoading ? (
              "Memeriksa pasien yang cocok…"
            ) : preview.error ? (
              <span className="text-[var(--destructive)]">
                {asApiError(preview.error).message}
              </span>
            ) : matched === 0 ? (
              "Tidak ada pasien yang cocok pada tanggal ini — pilih tanggal lain atau jalankan scrape terlebih dahulu."
            ) : force ? (
              <>
                <span className="font-medium">{matched}</span> pasien yang
                cocok akan di-merge ulang ({already} sudah memiliki data
                gabungan, {pending} belum di-merge).
              </>
            ) : pending === 0 ? (
              <>
                Semua {matched} pasien yang cocok pada tanggal ini sudah
                memiliki data gabungan. Aktifkan{" "}
                <span className="font-medium">Paksa merge ulang</span> untuk
                menjalankan lagi.
              </>
            ) : (
              <>
                <span className="font-medium">{pending}</span> pasien yang
                cocok menunggu merge ({already} sudah di-merge dari {matched}).
              </>
            )}
          </div>

          {startMerge.error && <ErrorState error={startMerge.error} />}
        </CardContent>
      </Card>

      <div className="space-y-3">
        <h2 className="text-base font-semibold">Recent merge jobs</h2>
        <div className="flex flex-wrap gap-4">
          <div className="w-64 space-y-1">
            <Label>Puskesmas</Label>
            <AsyncCombobox
              value={puskesmasId || undefined}
              onChange={(v) => setPuskesmasId(v ?? "")}
              useOptions={usePuskesmasOptions}
              selectedLabel={filterPkDetail.data?.name}
              placeholder="Select a puskesmas…"
              allOptionLabel="All puskesmas"
            />
          </div>
          <div className="w-44 space-y-1">
            <Label>Date</Label>
            <div className="flex gap-1">
              <Input
                type="date"
                value={dateFilter}
                onChange={(e) => setDateFilter(e.target.value)}
                className="flex-1"
              />
              {dateFilter && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="px-2 text-[var(--muted-foreground)]"
                  onClick={() => setDateFilter("")}
                  title="Clear date filter"
                >
                  ×
                </Button>
              )}
            </div>
          </div>
          <div className="w-44 space-y-1">
            <Label>Status</Label>
            <Select
              value={status || "all"}
              onValueChange={(v) =>
                setStatus(v === "all" ? "" : (v as MergeStatus))
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
                <SelectItem value="running">Running</SelectItem>
                <SelectItem value="success">Success</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
                <SelectItem value="cancelled">Cancelled</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="w-44 space-y-1">
            <Label>Scope</Label>
            <Select
              value={scope}
              onValueChange={(v) => setScope(v as MergeJobScope)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                <SelectItem value="puskesmas">Puskesmas-wide</SelectItem>
                <SelectItem value="patient">Per-NIK</SelectItem>
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
                    <TableHead>Puskesmas</TableHead>
                    <TableHead>NIK</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Progress</TableHead>
                    <TableHead>Force</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {jobs.data.items.map((j) => (
                    <TableRow key={j.id}>
                      <TableCell className="font-medium">
                        {j.puskesmas_name}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {j.patient_nik ?? "—"}
                      </TableCell>
                      <TableCell>{j.date_filter ?? "—"}</TableCell>
                      <TableCell>
                        <MergeStatusBadge status={j.status} />
                      </TableCell>
                      <TableCell className="text-xs text-[var(--muted-foreground)]">
                        {j.total_count != null
                          ? `${j.processed_count ?? 0}/${j.total_count} • ✓${j.succeeded_count ?? 0} ✗${j.failed_count ?? 0} ⤳${j.skipped_count ?? 0}`
                          : "—"}
                      </TableCell>
                      <TableCell className="text-xs">
                        {j.force_remerge ? "yes" : "no"}
                      </TableCell>
                      <TableCell className="text-xs text-[var(--muted-foreground)]">
                        {j.started_at
                          ? format(parseISO(j.started_at), "yyyy-MM-dd HH:mm")
                          : "—"}
                      </TableCell>
                      <TableCell className="text-xs text-[var(--muted-foreground)]">
                        {j.duration_seconds != null
                          ? `${j.duration_seconds.toFixed(1)}s`
                          : "—"}
                      </TableCell>
                      <TableCell>
                        <Button variant="ghost" size="sm" asChild>
                          <Link
                            href={`/merge-with-ai/${j.id}`}
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
              {jobs.data.items.length === 0 && (
                <div className="p-6">
                  <EmptyState title="No merge jobs yet" />
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
    </div>
  );
}
