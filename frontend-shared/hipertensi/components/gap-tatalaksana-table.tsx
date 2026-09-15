"use client";

import { format, parseISO } from "date-fns";
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
import { fmtBp } from "@/lib/hipertensi-format";
import type { HipertensiGapRow } from "@shared/hipertensi/types";

// Flat follow-up table — no expandable detail. A user works down this list with
// a phone, so the contact columns are the point and everything else is context.

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  try {
    return format(parseISO(iso), "dd/MM/yyyy");
  } catch {
    return iso;
  }
}

/** "2025-08" → "Agustus 2025". MONTHS_ID is 0-indexed (Januari at 0). */
function fmtYm(ym: string) {
  const [y, m] = ym.split("-");
  const name = MONTHS_ID[Number(m) - 1];
  return name ? `${name} ${y}` : ym;
}

function interpClass(v: string) {
  const s = v.toLowerCase();
  if (s === "hipertensi") return "bg-red-200 text-red-900";
  if (s === "pre-hipertensi") return "bg-yellow-100 text-yellow-900";
  return "";
}

/** Missing contact details are the norm, not an error — show the gap plainly. */
function Dash({ value }: { value: string }) {
  if (value) return <>{value}</>;
  return <span className="text-[var(--muted-foreground)]">—</span>;
}

export function GapTatalaksanaTable({ items }: { items: HipertensiGapRow[] }) {
  if (!items.length)
    return (
      <div className="p-6">
        <EmptyState
          title="Tidak ada pasien"
          description="Semua pasien hipertensi pada filter ini sudah pernah mendapat obat antihipertensi."
        />
      </div>
    );

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
      <Table className="min-w-[1100px]">
        <TableHeader>
          <TableRow>
            <TableHead className="w-[150px]">NIK</TableHead>
            <TableHead className="w-[160px]">Nama</TableHead>
            <TableHead className="w-[90px]">Jenis Kelamin</TableHead>
            <TableHead className="w-[110px]">Tanggal Lahir</TableHead>
            <TableHead className="w-[130px]">No Telp / HP</TableHead>
            <TableHead className="w-[260px]">Alamat</TableHead>
            <TableHead className="w-[120px]">Tanggal Berkunjung</TableHead>
            <TableHead className="w-[90px] text-center text-xs">Rerata (S/D)</TableHead>
            <TableHead className="w-[120px]">Interpretasi</TableHead>
            <TableHead className="w-[130px]">Masuk Registri</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((row) => (
            <TableRow key={row.nik}>
              <TableCell className="font-mono text-xs">{row.nik}</TableCell>
              <TableCell>
                <Dash value={row.nama} />
              </TableCell>
              <TableCell className="text-xs">
                <Dash value={row.jenis_kelamin} />
              </TableCell>
              <TableCell className="text-xs">{fmtDate(row.tanggal_lahir)}</TableCell>
              <TableCell className="text-xs tabular-nums">
                <Dash value={row.no_tlp} />
              </TableCell>
              <TableCell className="text-xs">
                <Dash value={row.alamat} />
              </TableCell>
              <TableCell className="text-xs">
                {fmtDate(row.tanggal_berkunjung)}
              </TableCell>
              <TableCell className="text-center tabular-nums text-xs">
                {fmtBp(row.rerata_sys)}/{fmtBp(row.rerata_dia)}
              </TableCell>
              <TableCell>
                <span
                  className={`rounded px-1.5 py-0.5 text-xs ${interpClass(row.interpretasi)}`}
                >
                  {row.interpretasi || "—"}
                </span>
              </TableCell>
              <TableCell className="text-xs">
                {fmtYm(row.registration_ym)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
