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
import { klasifikasiClass } from "@shared/bayi/format";
import type {
  BayiIkterusPemantauan,
  BayiRegistryRow,
} from "@shared/bayi/types";

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  try {
    return format(parseISO(iso), "dd/MM/yyyy");
  } catch {
    return iso;
  }
}

// Provenance pill: "EPUS" (blue) = isian EPUS langsung; "Hitung" (violet) =
// diturunkan backend dari kuesioner MTBM. Null source renders nothing.
function SourceTag({ src }: { src: string | null }) {
  if (!src) return null;
  const epus = src === "EPUS";
  return (
    <span
      className={`ml-1.5 rounded px-1 py-0.5 text-[10px] font-medium ${
        epus ? "bg-blue-100 text-blue-900" : "bg-violet-100 text-violet-900"
      }`}
    >
      {epus ? "EPUS" : "Hitung"}
    </span>
  );
}

function KlasifikasiCell({ value, src }: { value: string; src: string | null }) {
  return (
    <span className="inline-flex items-center">
      <span className={`rounded px-1.5 py-0.5 text-xs ${klasifikasiClass(value)}`}>
        {value || "—"}
      </span>
      <SourceTag src={src} />
    </span>
  );
}

function PemantauanDetail({ rows }: { rows: BayiIkterusPemantauan[] }) {
  if (!rows.length)
    return (
      <p className="text-xs text-[var(--muted-foreground)]">
        Tidak ada kunjungan pemantauan.
      </p>
    );
  return (
    <div className="overflow-hidden rounded-md border border-[var(--border)]">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[40px] text-xs">#</TableHead>
            <TableHead className="w-[110px] text-xs">Tanggal</TableHead>
            <TableHead className="w-[150px] text-xs">Ikterus</TableHead>
            <TableHead className="text-xs">Diagnosis</TableHead>
            <TableHead className="w-[160px] text-xs">Rujuk Eksternal</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r, i) => (
            <TableRow key={i}>
              <TableCell className="text-xs">{i + 1}</TableCell>
              <TableCell className="text-xs">{fmtDate(r.tanggal)}</TableCell>
              <TableCell>
                <KlasifikasiCell value={r.klasifikasi} src={r.sources.klasifikasi} />
              </TableCell>
              <TableCell className="text-xs">
                <span className="inline-flex items-center">
                  {r.diagnosis || "—"}
                  <SourceTag src={r.diagnosis ? r.sources.diagnosis : null} />
                </span>
              </TableCell>
              <TableCell className="text-xs">{r.rujuk_eksternal || "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function BayiRegistryTable({
  items,
  showPemantauan,
}: {
  items: BayiRegistryRow[];
  showPemantauan: boolean;
}) {
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
          title="Belum ada bayi"
          description="Tidak ada bayi dengan klasifikasi ikterus yang memenuhi syarat untuk puskesmas + tahun ini."
        />
      </div>
    );

  const colSpan = showPemantauan ? 10 : 9;

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
      {/* Column order follows the dirjen "Bayi Kuning" sheets. */}
      <Table className="min-w-[1050px]">
        <TableHeader>
          <TableRow>
            <TableHead className="w-[36px]" />
            <TableHead className="w-[150px]">NIK</TableHead>
            <TableHead className="w-[160px]">Nama</TableHead>
            <TableHead className="w-[90px]">Jenis Kelamin</TableHead>
            <TableHead className="w-[110px]">Tanggal Lahir</TableHead>
            <TableHead className="w-[120px]">Tanggal Berkunjung</TableHead>
            <TableHead className="w-[150px]">Ikterus</TableHead>
            <TableHead className="w-[180px]">Diagnosis</TableHead>
            <TableHead className="w-[160px]">Rujuk Eksternal</TableHead>
            {showPemantauan && (
              <TableHead className="w-[80px] text-center text-xs">Pemantauan</TableHead>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((row) => {
            const isOpen = open.has(row.nik);
            const base = row.ikterus?.baseline;
            const pem = row.ikterus?.pemantauan ?? [];
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
                  <TableCell className="text-xs">{row.jenis_kelamin || "—"}</TableCell>
                  <TableCell className="text-xs">{fmtDate(row.tanggal_lahir)}</TableCell>
                  <TableCell className="text-xs">
                    {fmtDate(row.tanggal_berkunjung)}
                  </TableCell>
                  <TableCell>
                    <KlasifikasiCell
                      value={base?.klasifikasi ?? ""}
                      src={base?.sources.klasifikasi ?? null}
                    />
                  </TableCell>
                  <TableCell className="text-xs">
                    <span className="inline-flex items-center">
                      {base?.diagnosis || "—"}
                      <SourceTag
                        src={base?.diagnosis ? base.sources.diagnosis : null}
                      />
                    </span>
                  </TableCell>
                  <TableCell className="text-xs">
                    {base?.rujuk_eksternal || "—"}
                  </TableCell>
                  {showPemantauan && (
                    <TableCell className="text-center tabular-nums text-xs">
                      {pem.length}
                    </TableCell>
                  )}
                </TableRow>
                {isOpen && (
                  <TableRow>
                    <TableCell colSpan={colSpan} className="bg-[var(--muted)]/20">
                      <div className="grid grid-cols-1 gap-6 p-2 lg:grid-cols-[280px_1fr]">
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
                          <p className="mt-1 text-[10px] text-[var(--muted-foreground)]">
                            Tanda <span className="font-medium">EPUS</span> =
                            klasifikasi diambil dari isian EPUS; {" "}
                            <span className="font-medium">Hitung</span> = diturunkan
                            dari kuesioner MTBM oleh sistem.
                          </p>
                        </div>
                        {showPemantauan && (
                          <div>
                            <div className="mb-2 text-xs font-semibold text-[var(--foreground)]">
                              Pemantauan Ikterus
                            </div>
                            <PemantauanDetail rows={pem} />
                          </div>
                        )}
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
