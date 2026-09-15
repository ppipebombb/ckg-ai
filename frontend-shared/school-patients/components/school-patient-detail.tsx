"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ArrowLeft } from "lucide-react";
import { ErrorState } from "@/components/common/error-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  FormCard,
  StatPill,
  formatValue,
  type FieldRow,
  type FormBlock,
} from "@shared/patients/components/form-card";
import { TatalaksanaCard } from "@shared/patients/components/tatalaksana-card";
import { useDecryptedSchoolPatient } from "@shared/school-patients/use-school-patients";
import { SchoolStatusBadge } from "./school-status-badge";

type JsonRecord = Record<string, unknown>;
const isRecord = (v: unknown): v is JsonRecord =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const asRecord = (v: unknown): JsonRecord => (isRecord(v) ? v : {});
const asArray = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

function walkLeaves(
  value: unknown,
  path: string[] = [],
): Array<{ path: string[]; value: unknown }> {
  if (isRecord(value)) {
    return Object.entries(value).flatMap(([k, c]) => walkLeaves(c, [...path, k]));
  }
  if (Array.isArray(value)) {
    return value.flatMap((c, i) => walkLeaves(c, [...path, String(i + 1)]));
  }
  return path.length > 0 ? [{ path, value }] : [];
}

function recordToRows(record: unknown): FieldRow[] {
  return walkLeaves(record)
    .filter(({ path }) => !path[path.length - 1]?.startsWith("_"))
    .map(({ path, value }) => ({
      label: path.join(" > "),
      value: formatValue(value),
    }));
}

function makeBlock(name: string, rows: FieldRow[]): FormBlock {
  const filled = rows.filter((r) => r.value !== null).length;
  return { name, filled, total: rows.length, rows };
}

// detail_data section key → human label. Unknown sections fall back to a
// title-cased key so a new section the scraper adds still renders.
const SECTION_LABEL: Record<string, string> = {
  data_individu: "Identitas Pasien",
  data_sekolah: "Data Sekolah",
  data_domisili: "Alamat & Domisili",
};
function sectionLabel(key: string): string {
  return (
    SECTION_LABEL[key] ??
    key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

function buildBlocks(blob: JsonRecord): {
  identity: FormBlock[];
  nakes: FormBlock[];
} {
  const identity: FormBlock[] = [];
  const detail = asRecord(blob.detail_data);
  for (const [key, vals] of Object.entries(detail)) {
    const rows = recordToRows(vals);
    if (rows.length > 0) identity.push(makeBlock(sectionLabel(key), rows));
  }

  const nakes: FormBlock[] = [];
  asArray(blob.pelayanan_nakes).forEach((entry, idx) => {
    const er = asRecord(entry);
    const layanan =
      typeof er.layanan === "string" && er.layanan.trim()
        ? er.layanan.trim()
        : `Pelayanan Nakes ${idx + 1}`;
    const rows = recordToRows(er.form_data);
    nakes.push(makeBlock(layanan, rows));
  });

  return { identity, nakes };
}

export function SchoolPatientDetail({ id }: { id: string }) {
  const q = useDecryptedSchoolPatient(id, true);
  const d = q.data;
  const blob = asRecord(d?.scraped_sekolah_data);

  const { identity, nakes } = useMemo(() => buildBlocks(blob), [blob]);
  const totals = useMemo(() => {
    let filled = 0;
    let total = 0;
    let formsWithData = 0;
    for (const b of [...identity, ...nakes]) {
      filled += b.filled;
      total += b.total;
      if (b.filled > 0) formsWithData += 1;
    }
    return { filled, total, formsWithData, blocks: identity.length + nakes.length };
  }, [identity, nakes]);

  const tatalaksana = blob.tatalaksana;
  const hasTatalaksana =
    asArray(asRecord(tatalaksana).rows).length > 0 ||
    typeof asRecord(tatalaksana).error === "string";

  return (
    <div className="space-y-5">
      <Button variant="ghost" size="sm" asChild className="-ml-2 h-8 px-2">
        <Link href="/school-patients" prefetch={false}>
          <ArrowLeft className="h-4 w-4" />
          Kembali
        </Link>
      </Button>

      {q.error && <ErrorState error={q.error} />}

      {!d && !q.error && (
        <div className="h-32 rounded-lg border border-[var(--border)] animate-pulse bg-[var(--muted)]" />
      )}

      {d && (
        <>
          <Card className="shadow-sm">
            <CardContent className="pt-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <h2 className="text-xl font-bold text-[var(--foreground)]">
                      {d.nama}
                    </h2>
                    <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-800">
                      CKG Sekolah
                    </span>
                    <SchoolStatusBadge status={d.screening_status} />
                  </div>
                  <div className="mt-1 text-sm font-medium text-[var(--foreground)]">
                    NIK: {d.nik}
                  </div>
                  <div className="text-sm text-[var(--muted-foreground)]">
                    {d.school_name ?? "—"}
                    {" · "}
                    {d.class_name ?? "—"}
                    {d.klaster_name ? ` · ${d.klaster_name}` : ""}
                  </div>
                  <div className="mt-1 text-xs text-[var(--muted-foreground)]">
                    Tahun Ajaran {d.school_year}
                  </div>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  <StatPill
                    label="Form"
                    value={totals.formsWithData}
                    hint={`/ ${totals.blocks}`}
                    tone="blue"
                  />
                  <StatPill
                    label="Field Terisi"
                    value={totals.filled}
                    hint={`/ ${totals.total}`}
                    tone="green"
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          {identity.map((block, idx) => (
            <FormCard key={`identity-${block.name}-${idx}`} block={block} />
          ))}

          {hasTatalaksana && <TatalaksanaCard data={tatalaksana} />}

          {nakes.map((block, idx) => (
            <FormCard key={`nakes-${block.name}-${idx}`} block={block} />
          ))}
        </>
      )}
    </div>
  );
}
