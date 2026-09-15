"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useScrapeJobsListStore } from "@/lib/stores/scrape-jobs-list-store";
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
import { Pagination } from "@/components/common/pagination";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { ScrapeStatusBadge } from "@/components/scrape/scrape-status-badge";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import { useScrapeJobList } from "@/lib/hooks/use-scrape";
import type { ScrapeJobScope } from "@/lib/api/scrape";
import type { ScrapeKindFilter } from "@/lib/stores/scrape-jobs-list-store";

export default function ScrapeJobsPage() {
  const puskesmasId = useScrapeJobsListStore((s) => s.puskesmasId);
  const page = useScrapeJobsListStore((s) => s.page);
  const scope = useScrapeJobsListStore((s) => s.scope);
  const kind = useScrapeJobsListStore((s) => s.kind);
  const setPuskesmasId = useScrapeJobsListStore((s) => s.setPuskesmasId);
  const setPage = useScrapeJobsListStore((s) => s.setPage);
  const setScope = useScrapeJobsListStore((s) => s.setScope);
  const setKind = useScrapeJobsListStore((s) => s.setKind);

  const pkDetail = usePuskesmas(puskesmasId || undefined);
  const query = useMemo(
    () => ({
      page,
      size: 20,
      puskesmas_id: puskesmasId || undefined,
      scope,
      kind: kind === "all" ? undefined : kind,
    }),
    [page, puskesmasId, scope, kind],
  );
  const jobs = useScrapeJobList(query);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Scrape Jobs"
        description="Lihat riwayat scrape job di semua puskesmas."
      />

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
        <div className="w-48 space-y-2">
          <Label>Jenis</Label>
          <Select
            value={kind}
            onValueChange={(v) => setKind(v as ScrapeKindFilter)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Semua</SelectItem>
              <SelectItem value="asik">CKG Pelayanan</SelectItem>
              <SelectItem value="asik_sekolah">CKG Sekolah</SelectItem>
              <SelectItem value="epus">ePuskesmas</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="w-48 space-y-2">
          <Label>Scope</Label>
          <Select
            value={scope}
            onValueChange={(v) => setScope(v as ScrapeJobScope)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Semua</SelectItem>
              <SelectItem value="puskesmas">Se-puskesmas</SelectItem>
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
                  <TableHead>Tanggal</TableHead>
                  <TableHead>Jenis</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Jumlah</TableHead>
                  <TableHead>Dimulai</TableHead>
                  <TableHead>Durasi</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.data.items.map((j) => (
                  <TableRow key={j.id}>
                    <TableCell className="font-medium">{j.puskesmas_name}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {j.patient_nik ?? "—"}
                    </TableCell>
                    <TableCell>{j.date_filter ?? "—"}</TableCell>
                    <TableCell className="uppercase">{j.kind}</TableCell>
                    <TableCell>
                      <ScrapeStatusBadge status={j.status} />
                    </TableCell>
                    <TableCell className="text-xs text-[var(--muted-foreground)]">
                      {j.scraped_count != null
                        ? `${j.scraped_count} • ${j.inserted_count ?? 0}+ / ${j.updated_count ?? 0}~`
                        : "—"}
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
                        <Link href={`/scrape-jobs/${j.id}`} prefetch={false}>
                          Buka
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {jobs.data.items.length === 0 && (
              <div className="p-6">
                <EmptyState title="Belum ada scrape job" />
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
