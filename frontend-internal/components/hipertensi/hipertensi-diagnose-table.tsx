"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/common/empty-state";
import { MONTHS_ID } from "@/lib/gdp-format";
import { bpClass, fmtBp } from "@/lib/hipertensi-format";
import type { HipertensiReportRow } from "@/lib/api/types";

type DayReading = { day: number; sys: number | null; dia: number | null };

// Group a row's bp_by_day (ISO date → { sys, dia }) into month → days[], each
// month's days sorted ascending. Months with no reading are absent.
function byMonth(
  bpByDay: HipertensiReportRow["bp_by_day"],
): Map<number, DayReading[]> {
  const out = new Map<number, DayReading[]>();
  for (const [iso, c] of Object.entries(bpByDay)) {
    const month = Number(iso.slice(5, 7));
    const day = Number(iso.slice(8, 10));
    const list = out.get(month) ?? [];
    list.push({ day, sys: c.sys, dia: c.dia });
    out.set(month, list);
  }
  for (const list of out.values()) list.sort((a, b) => a.day - b.day);
  return out;
}

function DayReadingCell({ r }: { r: DayReading }) {
  const cls = bpClass(r.sys, r.dia);
  return (
    <div className="overflow-hidden rounded-md border border-[var(--border)]">
      <div className="bg-[var(--muted)] px-1 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
        Tgl {r.day}
      </div>
      <div className="flex items-center justify-between gap-1 px-1.5 py-0.5">
        <span className="text-[9px] uppercase text-[var(--muted-foreground)]">
          Sis
        </span>
        <span className={`min-w-[28px] rounded px-1 tabular-nums ${cls}`}>
          {fmtBp(r.sys)}
        </span>
      </div>
      <div className="border-t border-dashed border-[var(--border)]" />
      <div className="flex items-center justify-between gap-1 px-1.5 py-0.5">
        <span className="text-[9px] uppercase text-[var(--muted-foreground)]">
          Dia
        </span>
        <span className={`min-w-[28px] rounded px-1 tabular-nums ${cls}`}>
          {fmtBp(r.dia)}
        </span>
      </div>
    </div>
  );
}

export function HipertensiDiagnoseTable({
  items,
}: {
  items: HipertensiReportRow[];
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
      <Table className="min-w-[1800px]">
        <TableHeader>
          <TableRow>
            <TableHead className="w-[180px]">Nama Puskesmas</TableHead>
            <TableHead className="w-[160px]">Nama Pasien</TableHead>
            <TableHead className="w-[160px]">NIK</TableHead>
            {MONTHS_ID.map((m) => (
              <TableHead key={m} className="w-[120px] text-center text-xs">
                {m}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((row) => {
            const months = byMonth(row.bp_by_day);
            return (
              <TableRow key={row.nik}>
                <TableCell className="align-top text-xs">
                  {row.puskesmas_name}
                </TableCell>
                <TableCell className="align-top">{row.nama || "—"}</TableCell>
                <TableCell className="align-top font-mono text-xs">
                  {row.nik}
                </TableCell>
                {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
                  const days = months.get(m);
                  return (
                    <TableCell key={m} className="align-top text-sm">
                      {days && days.length > 0 ? (
                        <div className="flex flex-col gap-1.5">
                          {days.map((r) => (
                            <DayReadingCell key={r.day} r={r} />
                          ))}
                        </div>
                      ) : (
                        <div className="text-center text-[var(--muted-foreground)]">
                          —
                        </div>
                      )}
                    </TableCell>
                  );
                })}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {items.length === 0 && (
        <div className="p-6">
          <EmptyState
            title="No patients with tekanan darah"
            description="No patient in this puskesmas+year has any blood-pressure reading."
          />
        </div>
      )}
    </div>
  );
}
