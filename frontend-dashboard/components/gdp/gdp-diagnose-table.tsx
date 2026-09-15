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
import { MONTHS_ID, fmtGdp, gdpClass } from "@/lib/gdp-format";
import type { GdpReportRow } from "@/lib/api/types";

type DayReading = { day: number; lab: number | null; ptm: number | null };

// Group a row's gdp_by_day (ISO date → { lab, ptm }) into month → days[],
// each month's days sorted ascending. Months with no reading are absent.
function byMonth(gdpByDay: GdpReportRow["gdp_by_day"]): Map<number, DayReading[]> {
  const out = new Map<number, DayReading[]>();
  for (const [iso, c] of Object.entries(gdpByDay)) {
    const month = Number(iso.slice(5, 7));
    const day = Number(iso.slice(8, 10));
    const list = out.get(month) ?? [];
    list.push({ day, lab: c.lab, ptm: c.ptm });
    out.set(month, list);
  }
  for (const list of out.values()) list.sort((a, b) => a.day - b.day);
  return out;
}

function DayReadingCell({ r }: { r: DayReading }) {
  return (
    <div className="overflow-hidden rounded-md border border-[var(--border)]">
      <div className="bg-[var(--muted)] px-1 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
        Tgl {r.day}
      </div>
      <div className="flex items-center justify-between gap-1 px-1.5 py-0.5">
        <span className="text-[9px] uppercase text-[var(--muted-foreground)]">
          Lab
        </span>
        <span
          className={`min-w-[28px] rounded px-1 tabular-nums ${gdpClass(r.lab)}`}
        >
          {fmtGdp(r.lab)}
        </span>
      </div>
      <div className="border-t border-dashed border-[var(--border)]" />
      <div className="flex items-center justify-between gap-1 px-1.5 py-0.5">
        <span className="text-[9px] uppercase text-[var(--muted-foreground)]">
          PTM
        </span>
        <span
          className={`min-w-[28px] rounded px-1 tabular-nums ${gdpClass(r.ptm)}`}
        >
          {fmtGdp(r.ptm)}
        </span>
      </div>
    </div>
  );
}

export function GdpDiagnoseTable({ items }: { items: GdpReportRow[] }) {
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
            const months = byMonth(row.gdp_by_day);
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
            title="No patients with GDP"
            description="No patient in this puskesmas+year has any GDP reading."
          />
        </div>
      )}
    </div>
  );
}
