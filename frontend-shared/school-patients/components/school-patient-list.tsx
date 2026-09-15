"use client";

import Link from "next/link";
import { useMemo } from "react";
import { format, parseISO } from "date-fns";
import { PageHeader } from "@/components/common/page-header";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Pagination } from "@/components/common/pagination";
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
import {
  useSchoolFacets,
  useSchoolPatientsList,
} from "@shared/school-patients/use-school-patients";
import { useSchoolPatientsListStore } from "@shared/school-patients/school-patients-list-store";
import type { SchoolScreeningStatus } from "@shared/school-patients/types";
import { SchoolStatusBadge } from "./school-status-badge";

// Mirror routes/school_patients.py Query(..., le=150) — over-range typo would 422.
const MAX_AGE = 150;

// Full current age (today − born_date) as "X Tahun Y Bulan Z Hari" for the
// display-only Umur column — same convention as the CKG-Umum patient list.
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
    days += new Date(now.getFullYear(), now.getMonth(), 0).getDate();
  }
  if (months < 0) {
    years -= 1;
    months += 12;
  }
  if (years < 0) return null;
  return `${years} Tahun ${months} Bulan ${days} Hari`;
}

function parseAge(s: string): number | undefined {
  const t = s.trim();
  if (t === "") return undefined;
  const n = Number(t);
  if (!Number.isInteger(n) || n < 0) return undefined;
  return Math.min(n, MAX_AGE);
}

export function SchoolPatientList() {
  const isAdmin = useIsAdmin();

  const page = useSchoolPatientsListStore((s) => s.page);
  const q = useSchoolPatientsListStore((s) => s.q);
  const puskesmasId = useSchoolPatientsListStore((s) => s.puskesmasId);
  const status = useSchoolPatientsListStore((s) => s.status);
  const schoolName = useSchoolPatientsListStore((s) => s.schoolName);
  const className = useSchoolPatientsListStore((s) => s.className);
  const schoolYear = useSchoolPatientsListStore((s) => s.schoolYear);
  const minAge = useSchoolPatientsListStore((s) => s.minAge);
  const maxAge = useSchoolPatientsListStore((s) => s.maxAge);

  const setPage = useSchoolPatientsListStore((s) => s.setPage);
  const setQ = useSchoolPatientsListStore((s) => s.setQ);
  const setPuskesmasId = useSchoolPatientsListStore((s) => s.setPuskesmasId);
  const setStatus = useSchoolPatientsListStore((s) => s.setStatus);
  const setSchoolName = useSchoolPatientsListStore((s) => s.setSchoolName);
  const setClassName = useSchoolPatientsListStore((s) => s.setClassName);
  const setSchoolYear = useSchoolPatientsListStore((s) => s.setSchoolYear);
  const setMinAge = useSchoolPatientsListStore((s) => s.setMinAge);
  const setMaxAge = useSchoolPatientsListStore((s) => s.setMaxAge);

  const debouncedQ = useDebouncedValue(q);
  const debouncedMinAge = useDebouncedValue(minAge);
  const debouncedMaxAge = useDebouncedValue(maxAge);
  const pkDetail = usePuskesmas(puskesmasId || undefined);

  // Facets (schools + their classes + years) drive the cascading dropdowns.
  const facets = useSchoolFacets(puskesmasId);
  const schools = facets.data?.schools ?? [];
  const years = facets.data?.school_years ?? [];
  // Pilih Kelas options: the selected school's classes, else the union of all.
  const classOptions = useMemo(() => {
    if (schoolName) {
      return schools.find((s) => s.name === schoolName)?.classes ?? [];
    }
    return Array.from(new Set(schools.flatMap((s) => s.classes))).sort();
  }, [schools, schoolName]);

  const query = useMemo(
    () => ({
      page,
      size: 20,
      puskesmas_id: puskesmasId || undefined,
      screening_status: status || undefined,
      school_name: schoolName || undefined,
      class_name: className || undefined,
      school_year: schoolYear ? Number(schoolYear) : undefined,
      min_age: parseAge(debouncedMinAge),
      max_age: parseAge(debouncedMaxAge),
      q: debouncedQ.trim() || undefined,
    }),
    [
      page,
      puskesmasId,
      status,
      schoolName,
      className,
      schoolYear,
      debouncedMinAge,
      debouncedMaxAge,
      debouncedQ,
    ],
  );
  const list = useSchoolPatientsList(query);

  return (
    <div className="space-y-6">
      <PageHeader
        title="CKG Sekolah"
        description="Pemeriksaan kesehatan anak sekolah (school health checkup), per sekolah × kelas."
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

        <div className="w-64 space-y-1">
          <Label>Sekolah</Label>
          <Select
            value={schoolName || "all"}
            onValueChange={(v) => setSchoolName(v === "all" ? "" : v)}
          >
            <SelectTrigger>
              <SelectValue placeholder="Semua sekolah" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Semua sekolah</SelectItem>
              {schools.map((s) => (
                <SelectItem key={s.name} value={s.name}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="w-44 space-y-1">
          <Label>Kelas</Label>
          <Select
            value={className || "all"}
            onValueChange={(v) => setClassName(v === "all" ? "" : v)}
          >
            <SelectTrigger>
              <SelectValue placeholder="Semua kelas" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Semua kelas</SelectItem>
              {classOptions.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="w-44 space-y-1">
          <Label>Status</Label>
          <Select
            value={status || "all"}
            onValueChange={(v) => setStatus(v === "all" ? "" : v)}
          >
            <SelectTrigger>
              <SelectValue placeholder="Semua status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Semua status</SelectItem>
              <SelectItem value="belum">Belum Pemeriksaan</SelectItem>
              <SelectItem value="sedang">Sedang Pemeriksaan</SelectItem>
              <SelectItem value="selesai">Selesai Pemeriksaan</SelectItem>
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
              placeholder="max"
              value={maxAge}
              onChange={(e) => setMaxAge(e.target.value)}
              className="w-full"
            />
          </div>
        </div>

        <div className="w-36 space-y-1">
          <Label>Tahun Ajaran</Label>
          <Select
            value={schoolYear || "all"}
            onValueChange={(v) => setSchoolYear(v === "all" ? "" : v)}
          >
            <SelectTrigger>
              <SelectValue placeholder="Semua" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Semua</SelectItem>
              {years.map((y) => (
                <SelectItem key={y} value={String(y)}>
                  {y}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
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

      {list.error && <ErrorState error={list.error} />}

      {list.data && (
        <>
          <div className="rounded-lg border border-[var(--border)]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>NIK</TableHead>
                  <TableHead>Nama</TableHead>
                  <TableHead>Umur</TableHead>
                  <TableHead>Sekolah</TableHead>
                  <TableHead>Kelas</TableHead>
                  <TableHead>Klaster</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Tahun</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.data.items.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="font-mono text-xs">{s.nik}</TableCell>
                    <TableCell className="font-medium">{s.nama}</TableCell>
                    <TableCell className="text-xs text-[var(--muted-foreground)]">
                      {fullAge(s.born_date) ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs">
                      {s.school_name ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs">
                      {s.class_name ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs text-[var(--muted-foreground)]">
                      {s.klaster_name ?? "—"}
                    </TableCell>
                    <TableCell>
                      <SchoolStatusBadge status={s.screening_status} />
                    </TableCell>
                    <TableCell className="text-xs">{s.school_year}</TableCell>
                    <TableCell>
                      <Button variant="ghost" size="sm" asChild>
                        <Link
                          href={`/school-patients/${s.id}`}
                          prefetch={false}
                        >
                          Buka
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {list.data.items.length === 0 && (
              <div className="p-6">
                <EmptyState title="Tidak ada data CKG Sekolah" />
              </div>
            )}
          </div>
          <Pagination
            page={list.data.page}
            pages={list.data.pages}
            total={list.data.total}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
