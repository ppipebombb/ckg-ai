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
import {
  fmtAntro,
  fmtImt,
  fmtPenurunan,
  interpClass,
} from "@shared/obesitas/format";
import type {
  ObesitasFollowUpReading,
  ObesitasRegistryRow,
} from "@shared/obesitas/types";

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  try {
    return format(parseISO(iso), "dd/MM/yyyy");
  } catch {
    return iso;
  }
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

// Riwayat diagnosis pill. Reported only — a "Ya" here neither admits the patient
// nor pins the interpretasi (same rule as the Dislipidemia registry).
function RiwayatTag({ value }: { value: string }) {
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-xs ${
        value === "Ya"
          ? "bg-amber-100 text-amber-900"
          : "text-[var(--muted-foreground)]"
      }`}
    >
      {value}
    </span>
  );
}

function FollowUpDetail({
  followup,
}: {
  followup: Record<string, ObesitasFollowUpReading[]>;
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
                  <TableHead className="w-[70px] text-center text-xs">
                    BB (kg)
                  </TableHead>
                  <TableHead className="w-[70px] text-center text-xs">
                    TB (cm)
                  </TableHead>
                  <TableHead className="w-[70px] text-center text-xs">IMT</TableHead>
                  {/* The value the L16 target is actually judged on. Shown next
                      to the label so a reader never has to recompute it. */}
                  <TableHead className="w-[90px] text-center text-xs">
                    Δ BB vs CKG
                  </TableHead>
                  <TableHead className="text-xs">Interpretasi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(followup[String(m)] ?? []).map((r, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs">{fmtDate(r.tanggal)}</TableCell>
                    <TableCell className="text-center tabular-nums text-sm">
                      {fmtAntro(r.bb)}
                    </TableCell>
                    <TableCell className="text-center tabular-nums text-sm">
                      {fmtAntro(r.tb)}
                    </TableCell>
                    <TableCell className="text-center tabular-nums text-sm">
                      {fmtImt(r.imt)}
                    </TableCell>
                    <TableCell className="text-center tabular-nums text-sm">
                      {fmtPenurunan(r.penurunan_pct)}
                    </TableCell>
                    <TableCell className="text-xs">
                      <span
                        className={`rounded px-1.5 py-0.5 ${interpClass(r.interpretasi)}`}
                      >
                        {r.interpretasi || "—"}
                      </span>
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

export function ObesitasRegistryTable({
  items,
}: {
  items: ObesitasRegistryRow[];
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
          title="Belum ada pasien"
          description="Tidak ada pasien obesitas dengan kunjungan CKG (EPUS+ASIK) untuk puskesmas + tahun ini."
        />
      </div>
    );

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
      {/* Column order follows the dirjen "Obesitas" sheet. There is no Jenis
          Obat column — that sheet has none, unlike the three sibling registries. */}
      <Table className="min-w-[1150px]">
        <TableHeader>
          <TableRow>
            <TableHead className="w-[36px]" />
            <TableHead className="w-[150px]">NIK</TableHead>
            <TableHead className="w-[160px]">Nama</TableHead>
            <TableHead className="w-[90px]">Jenis Kelamin</TableHead>
            <TableHead className="w-[110px]">Tanggal Lahir</TableHead>
            <TableHead className="w-[120px]">Tanggal Berkunjung</TableHead>
            <TableHead className="w-[90px] text-center">Riwayat HT</TableHead>
            <TableHead className="w-[90px] text-center">Riwayat DM</TableHead>
            <TableHead className="w-[75px] text-center text-xs">BB (kg)</TableHead>
            <TableHead className="w-[75px] text-center text-xs">TB (cm)</TableHead>
            <TableHead className="w-[70px] text-center text-xs">IMT</TableHead>
            <TableHead className="w-[110px]">Interpretasi</TableHead>
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
                    <RiwayatTag value={row.riwayat_ht} />
                  </TableCell>
                  <TableCell className="text-center">
                    <RiwayatTag value={row.riwayat_dm} />
                  </TableCell>
                  <TableCell className="text-center tabular-nums text-xs">
                    {fmtAntro(row.bb)}
                  </TableCell>
                  <TableCell className="text-center tabular-nums text-xs">
                    {fmtAntro(row.tb)}
                  </TableCell>
                  <TableCell className="text-center tabular-nums text-xs">
                    {fmtImt(row.imt)}
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
                            <div className="mb-1 font-semibold text-[var(--foreground)]">
                              Sumber Data (kunjungan CKG)
                            </div>
                            <div className="space-y-0.5">
                              <SourceRow
                                label="Berat / Tinggi Badan"
                                value={`${fmtAntro(row.bb)} kg · ${fmtAntro(row.tb)} cm`}
                                src={row.sources.antropometri}
                              />
                              <SourceRow
                                label="Riwayat diagnosis HT"
                                value={row.riwayat_ht}
                                src={row.sources.riwayat_ht}
                              />
                              <SourceRow
                                label="Riwayat diagnosis DM"
                                value={row.riwayat_dm}
                                src={row.sources.riwayat_dm}
                              />
                            </div>
                            <p className="mt-1 text-[10px] text-[var(--muted-foreground)]">
                              ASIK = data skrining CKG (sumber utama); ePus =
                              ePuskesmas (pelengkap). IMT tidak punya tanda
                              sumber — dihitung sendiri dari BB dan TB. Follow Up
                              selalu dari ePuskesmas.
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
