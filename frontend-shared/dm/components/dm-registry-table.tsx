"use client";

import { Fragment, useState } from "react";
import { format, parseISO } from "date-fns";
import { ChevronDown, ChevronRight } from "lucide-react";
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
import { fmtGlu, fmtHba1c, interpClass } from "@shared/dm/format";
import type { DmFollowUpReading, DmRegistryRow } from "@shared/dm/types";

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  try {
    return format(parseISO(iso), "dd/MM/yyyy");
  } catch {
    return iso;
  }
}

function ObatList({ obat }: { obat: string[] }) {
  if (!obat.length) return <span className="text-[var(--muted-foreground)]">—</span>;
  return (
    <ul className="list-disc space-y-0.5 pl-4">
      {obat.map((o, i) => (
        <li key={i}>{o}</li>
      ))}
    </ul>
  );
}

// Tiny provenance pill: ASIK (blue) is the source of truth, ePuskesmas (emerald)
// the fallback. Null source (field absent) renders nothing.
function SourceTag({ src }: { src: string | null }) {
  if (!src) return null;
  const asik = src === "ASIK";
  return (
    <span
      className={`ml-1.5 rounded px-1 py-0.5 text-[10px] font-medium ${
        asik ? "bg-blue-100 text-blue-900" : "bg-emerald-100 text-emerald-900"
      }`}
    >
      {asik ? "ASIK" : "ePus"}
    </span>
  );
}

function SourceRow({
  label,
  value,
  src,
}: {
  label: string;
  value: string;
  src: string | null;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[var(--muted-foreground)]">{label}</span>
      <span className="flex items-center tabular-nums">
        {value}
        <SourceTag src={src} />
      </span>
    </div>
  );
}

function FollowUpDetail({
  followup,
}: {
  followup: Record<string, DmFollowUpReading[]>;
}) {
  const months = Object.keys(followup)
    .map(Number)
    .filter((m) => (followup[String(m)] ?? []).length > 0)
    .sort((a, b) => a - b);
  if (!months.length)
    return (
      <p className="text-xs text-[var(--muted-foreground)]">
        Tidak ada kunjungan follow-up.
      </p>
    );
  return (
    <div className="space-y-3">
      {months.map((m) => (
        <div key={m}>
          <div className="mb-1 text-xs font-semibold text-[var(--foreground)]">
            {MONTHS_ID[m - 1]}
            {(followup[String(m)] ?? []).length > 1 && (
              <span className="ml-2 font-normal text-[var(--muted-foreground)]">
                {(followup[String(m)] ?? []).length} kunjungan
              </span>
            )}
          </div>
          <div className="overflow-hidden rounded-md border border-[var(--border)]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[110px] text-xs">
                    Tanggal Pemeriksaan
                  </TableHead>
                  <TableHead className="w-[70px] text-center text-xs">GDS</TableHead>
                  <TableHead className="w-[70px] text-center text-xs">GDP</TableHead>
                  <TableHead className="w-[70px] text-center text-xs">GD2PP</TableHead>
                  <TableHead className="w-[70px] text-center text-xs">HbA1C</TableHead>
                  <TableHead className="w-[230px] text-xs">Interpretasi</TableHead>
                  <TableHead className="text-xs">Jenis Obat</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(followup[String(m)] ?? []).map((r, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs">{fmtDate(r.tanggal)}</TableCell>
                    <TableCell className="text-center tabular-nums text-sm">
                      {fmtGlu(r.gds)}
                    </TableCell>
                    <TableCell className="text-center tabular-nums text-sm">
                      {fmtGlu(r.gdp)}
                    </TableCell>
                    <TableCell className="text-center tabular-nums text-sm">
                      {fmtGlu(r.gd2pp)}
                    </TableCell>
                    <TableCell className="text-center tabular-nums text-sm">
                      {fmtHba1c(r.hba1c)}
                    </TableCell>
                    <TableCell className="text-xs">
                      <span
                        className={`rounded px-1.5 py-0.5 ${interpClass(r.interpretasi)}`}
                      >
                        {r.interpretasi || "—"}
                      </span>
                    </TableCell>
                    <TableCell className="text-xs">
                      <ObatList obat={r.obat} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      ))}
    </div>
  );
}

export function DmRegistryTable({ items }: { items: DmRegistryRow[] }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (nik: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(nik)) next.delete(nik);
      else next.add(nik);
      return next;
    });

  if (!items.length)
    return (
      <div className="p-6">
        <EmptyState
          title="Belum ada pasien"
          description="Tidak ada pasien diabetes melitus atau prediabetes dengan kunjungan CKG (EPUS+ASIK) untuk puskesmas + tahun ini."
        />
      </div>
    );

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
      <Table className="min-w-[1200px]">
        <TableHeader>
          <TableRow>
            <TableHead className="w-[36px]" />
            <TableHead className="w-[150px]">NIK</TableHead>
            <TableHead className="w-[160px]">Nama</TableHead>
            <TableHead className="w-[90px]">Jenis Kelamin</TableHead>
            <TableHead className="w-[110px]">Tanggal Lahir</TableHead>
            <TableHead className="w-[120px]">Tanggal Berkunjung</TableHead>
            <TableHead className="w-[90px] text-center">Riwayat DM</TableHead>
            <TableHead className="w-[70px] text-center text-xs">GDS 1</TableHead>
            <TableHead className="w-[70px] text-center text-xs">GDS 2</TableHead>
            <TableHead className="w-[70px] text-center text-xs">GDP</TableHead>
            <TableHead className="w-[70px] text-center text-xs">GD2PP</TableHead>
            <TableHead className="w-[150px]">Interpretasi</TableHead>
            <TableHead className="w-[70px] text-center text-xs">Follow-up</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((row) => {
            const isOpen = open.has(row.nik);
            const fuCount = Object.values(row.followup).reduce(
              (a, arr) => a + arr.length,
              0,
            );
            return (
              <Fragment key={row.nik}>
                <TableRow
                  className="cursor-pointer hover:bg-[var(--muted)]/40"
                  onClick={() => toggle(row.nik)}
                >
                  <TableCell className="text-center">
                    {isOpen ? (
                      <ChevronDown className="h-4 w-4" />
                    ) : (
                      <ChevronRight className="h-4 w-4" />
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{row.nik}</TableCell>
                  <TableCell>{row.nama || "—"}</TableCell>
                  <TableCell className="text-xs">
                    {row.jenis_kelamin || "—"}
                  </TableCell>
                  <TableCell className="text-xs">
                    {fmtDate(row.tanggal_lahir)}
                  </TableCell>
                  <TableCell className="text-xs">
                    {fmtDate(row.tanggal_berkunjung)}
                  </TableCell>
                  <TableCell className="text-center">
                    <span
                      className={`rounded px-1.5 py-0.5 text-xs ${
                        row.riwayat_dm === "Ya"
                          ? "bg-red-100 text-red-900"
                          : "text-[var(--muted-foreground)]"
                      }`}
                    >
                      {row.riwayat_dm}
                    </span>
                  </TableCell>
                  <TableCell className="text-center tabular-nums text-xs">
                    {fmtGlu(row.gds1)}
                  </TableCell>
                  <TableCell className="text-center tabular-nums text-xs">
                    {fmtGlu(row.gds2)}
                  </TableCell>
                  <TableCell className="text-center tabular-nums text-xs">
                    {fmtGlu(row.gdp)}
                  </TableCell>
                  <TableCell className="text-center tabular-nums text-xs">
                    {fmtGlu(row.gd2pp)}
                  </TableCell>
                  <TableCell>
                    <span
                      className={`rounded px-1.5 py-0.5 text-xs ${interpClass(row.interpretasi)}`}
                    >
                      {row.interpretasi || "—"}
                    </span>
                  </TableCell>
                  <TableCell className="text-center tabular-nums text-xs">
                    {fuCount}
                  </TableCell>
                </TableRow>
                {isOpen && (
                  <TableRow>
                    <TableCell colSpan={13} className="bg-[var(--muted)]/20">
                      <div className="grid grid-cols-1 gap-6 p-2 lg:grid-cols-[300px_1fr]">
                        <div className="space-y-3 text-xs">
                          <div>
                            <div className="font-semibold text-[var(--foreground)]">
                              No. Telepon
                            </div>
                            <div>{row.no_tlp || "—"}</div>
                          </div>
                          <div>
                            <div className="font-semibold text-[var(--foreground)]">
                              Alamat
                            </div>
                            <div>{row.alamat || "—"}</div>
                          </div>
                          <div>
                            <div className="flex items-center font-semibold text-[var(--foreground)]">
                              Jenis Obat (pada Tanggal Berkunjung)
                              <SourceTag src={row.sources.obat} />
                            </div>
                            <ObatList obat={row.obat} />
                          </div>
                          <div>
                            <div className="mb-1 font-semibold text-[var(--foreground)]">
                              Sumber Data (kunjungan CKG)
                            </div>
                            <div className="space-y-0.5">
                              <SourceRow
                                label="Gula darah"
                                value={`GDS ${fmtGlu(row.gds1)} · GDP ${fmtGlu(row.gdp)}`}
                                src={row.sources.gula_darah}
                              />
                              <SourceRow
                                label="HbA1C"
                                value={fmtHba1c(row.hba1c)}
                                src={row.sources.gula_darah}
                              />
                              <SourceRow
                                label="Riwayat DM"
                                value={row.riwayat_dm}
                                src={row.sources.riwayat_dm}
                              />
                            </div>
                            <p className="mt-1 text-[10px] text-[var(--muted-foreground)]">
                              ASIK = data skrining CKG (sumber utama); ePus =
                              ePuskesmas (pelengkap). Follow Up selalu dari
                              ePuskesmas.
                            </p>
                          </div>
                        </div>
                        <div>
                          <div className="mb-2 text-xs font-semibold text-[var(--foreground)]">
                            Follow Up
                          </div>
                          <FollowUpDetail followup={row.followup} />
                        </div>
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
