"use client";

import Link from "next/link";
import { useMemo } from "react";
import { format, parseISO } from "date-fns";
import { PageHeader } from "@/components/common/page-header";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Pagination } from "@/components/common/pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useIsAdmin } from "@/lib/hooks/use-is-admin";
import { usePatientsList } from "@shared/patients/use-patients";
import { usePatientsListStore } from "@shared/patients/patients-list-store";
import type { MatchStatus } from "@shared/patients/types";

const MATCH_STATUS_LABEL: Record<MatchStatus, string> = {
  asik_only: "Hanya ASIK",
  epus_only: "Hanya EPUS",
  matched: "Cocok",
};

const MATCH_STATUS_VARIANT: Record<
  MatchStatus,
  "default" | "secondary" | "success" | "warning"
> = {
  asik_only: "warning",
  epus_only: "secondary",
  matched: "success",
};

// Upper bound for the umur filter. MUST stay in sync with the backend's
// Query(..., le=150) on min_age/max_age in routes/patients.py — a value above it
// would 422 the whole list, so parseAge clamps here instead.
const MAX_AGE = 150;

// Full current age (today − birth_date) as "X Tahun Y Bulan Z Hari" for the
// display-only "Umur" column. Medical data needs the precise breakdown — a bare
// "0" for an infant is ambiguous, so always show years/months/days. Computed
// client-side from the stable birth_date (not server-returned) so it never goes
// stale in the TanStack cache. Caveat: it reads the BROWSER clock while the
// min_age/max_age filter reads the SERVER clock, so exactly on a patient's
// birthday across a timezone/midnight boundary it can read ±1 day from what the
// filter includes. That's cosmetic — filtering is authoritative server-side.
function fullAge(iso: string | null): string | null {
  if (!iso) return null;
  const b = parseISO(iso);
  if (Number.isNaN(b.getTime())) return null;
  const now = new Date();
  let years = now.getFullYear() - b.getFullYear();
  let months = now.getMonth() - b.getMonth();
  let days = now.getDate() - b.getDate();
  if (days < 0) {
    months -= 1;
    // borrow the day count of the previous calendar month
    days += new Date(now.getFullYear(), now.getMonth(), 0).getDate();
  }
  if (months < 0) {
    years -= 1;
    months += 12;
  }
  if (years < 0) return null; // future birth date → treat as unknown
  return `${years} Tahun ${months} Bulan ${days} Hari`;
}

// Parse a raw age input into a query value. Drops blanks / non-integers /
// negatives to undefined (filter off) and clamps to [0, MAX_AGE] so an
// over-range typo (e.g. "200", "1999") can never reach the backend and 422 it.
function parseAge(s: string): number | undefined {
  const t = s.trim();
  if (t === "") return undefined;
  const n = Number(t);
  if (!Number.isInteger(n) || n < 0) return undefined;
  return Math.min(n, MAX_AGE);
}

export function PatientList() {
  const isAdmin = useIsAdmin();

  const page = usePatientsListStore((s) => s.page);
  const q = usePatientsListStore((s) => s.q);
  const puskesmasId = usePatientsListStore((s) => s.puskesmasId);
  const filterDate = usePatientsListStore((s) => s.filterDate);
  const matchStatus = usePatientsListStore((s) => s.matchStatus);
  const merged = usePatientsListStore((s) => s.merged);
  const minAge = usePatientsListStore((s) => s.minAge);
  const maxAge = usePatientsListStore((s) => s.maxAge);

  const setPage = usePatientsListStore((s) => s.setPage);
  const setQ = usePatientsListStore((s) => s.setQ);
  const setPuskesmasId = usePatientsListStore((s) => s.setPuskesmasId);
  const setFilterDate = usePatientsListStore((s) => s.setFilterDate);
  const setMatchStatus = usePatientsListStore((s) => s.setMatchStatus);
  const setMerged = usePatientsListStore((s) => s.setMerged);
  const setMinAge = usePatientsListStore((s) => s.setMinAge);
  const setMaxAge = usePatientsListStore((s) => s.setMaxAge);

  const debouncedQ = useDebouncedValue(q);
  const debouncedMinAge = useDebouncedValue(minAge);
  const debouncedMaxAge = useDebouncedValue(maxAge);
  const pkDetail = usePuskesmas(puskesmasId || undefined);

  const query = useMemo(
    () => ({
      page,
      size: 20,
      q: debouncedQ.trim() || undefined,
      puskesmas_id: puskesmasId || undefined,
      filter_date: filterDate || undefined,
      match_status: (matchStatus as MatchStatus) || undefined,
      merged:
        merged === "merged" ? true : merged === "unmerged" ? false : undefined,
      min_age: parseAge(debouncedMinAge),
      max_age: parseAge(debouncedMaxAge),
    }),
    [
      page,
      debouncedQ,
      puskesmasId,
      filterDate,
      matchStatus,
      merged,
      debouncedMinAge,
      debouncedMaxAge,
    ],
  );

  const patients = usePatientsList(query);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pasien"
        description="Telusuri dan cari data pasien."
      />

      <div className="flex flex-wrap gap-4">
        <div className="w-64 space-y-1">
          <Label>Cari</Label>
          <Input
            placeholder="Nama atau NIK…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>

        <div className="w-44 space-y-1">
          <Label>Tanggal</Label>
          <div className="flex gap-1">
            <Input
              type="date"
              value={filterDate}
              onChange={(e) => setFilterDate(e.target.value)}
              className="flex-1"
            />
            {filterDate && (
              <Button
                variant="ghost"
                size="sm"
                className="px-2 text-[var(--muted-foreground)]"
                onClick={() => setFilterDate("")}
                title="Hapus filter tanggal"
              >
                ×
              </Button>
            )}
          </div>
        </div>

        <div className="w-44 space-y-1">
          <Label>Status</Label>
          <Select
            value={matchStatus || "all"}
            onValueChange={(v) => setMatchStatus(v === "all" ? "" : v)}
          >
            <SelectTrigger>
              <SelectValue placeholder="Semua status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Semua status</SelectItem>
              <SelectItem value="asik_only">Hanya ASIK</SelectItem>
              <SelectItem value="epus_only">Hanya EPUS</SelectItem>
              <SelectItem value="matched">Cocok</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="w-44 space-y-1">
          <Label>Penggabungan</Label>
          <Select
            value={merged}
            onValueChange={(v) =>
              setMerged(v as "all" | "merged" | "unmerged")
            }
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Semua</SelectItem>
              <SelectItem value="merged">Tergabung</SelectItem>
              <SelectItem value="unmerged">Belum tergabung</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="w-40 space-y-1">
          <Label>Umur</Label>
          <div className="flex items-center gap-1">
            <Input
              type="number"
              min={0}
              max={MAX_AGE}
              placeholder="min"
              value={minAge}
              onChange={(e) => setMinAge(e.target.value)}
              className="w-full"
            />
            <span className="text-[var(--muted-foreground)]">–</span>
            <Input
              type="number"
              min={0}
              max={MAX_AGE}
              placeholder="maks"
              value={maxAge}
              onChange={(e) => setMaxAge(e.target.value)}
              className="w-full"
            />
          </div>
        </div>

        {isAdmin && (
          <div className="w-64 space-y-1">
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
        )}
      </div>

      {patients.error && <ErrorState error={patients.error} />}

      {patients.data && (
        <>
          <div className="rounded-lg border border-[var(--border)]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>NIK</TableHead>
                  <TableHead>Nama</TableHead>
                  <TableHead>Umur</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Tanggal</TableHead>
                  <TableHead>Dibuat</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {patients.data.items.map((p) => {
                  const age = fullAge(p.birth_date);
                  return (
                    <TableRow key={p.id}>
                      <TableCell className="font-mono text-xs">{p.nik}</TableCell>
                      <TableCell className="font-medium">{p.nama}</TableCell>
                      <TableCell className="text-xs text-[var(--muted-foreground)]">
                        {age === null ? "—" : age}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1">
                          <Badge variant={MATCH_STATUS_VARIANT[p.match_status]}>
                            {MATCH_STATUS_LABEL[p.match_status]}
                          </Badge>
                          {p.has_merged_data && (
                            <Badge variant="default">Tergabung</Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-[var(--muted-foreground)]">
                        {p.filter_date}
                      </TableCell>
                      <TableCell className="text-xs text-[var(--muted-foreground)]">
                        {format(parseISO(p.created_at), "yyyy-MM-dd")}
                      </TableCell>
                      <TableCell>
                        <Button variant="ghost" size="sm" asChild>
                          <Link href={`/patients/${p.id}`} prefetch={false}>
                            Buka
                          </Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            {patients.data.items.length === 0 && (
              <div className="p-6">
                <EmptyState title="Tidak ada pasien ditemukan" />
              </div>
            )}
          </div>
          <Pagination
            page={patients.data.page}
            pages={patients.data.pages}
            total={patients.data.total}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
