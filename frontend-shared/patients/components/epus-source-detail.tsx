"use client";

import { useMemo } from "react";
import { Card, CardContent } from "@/components/ui/card";
import {
  buildPatientFromRawSource,
  findIdentity,
  type PatientItem,
} from "@shared/patients/raw-patient";
import {
  FormCard,
  StatPill,
  formatValue,
  type FieldRow,
  type FormBlock,
} from "./form-card";
import { TableCard } from "./table-card";

function itemsToRows(items: PatientItem[]): FieldRow[] {
  return items.map((it) => ({
    label: it.merged_key,
    value: formatValue(it.merged_value),
  }));
}

function makeBlock(name: string, rows: FieldRow[]): FormBlock {
  const filled = rows.filter((r) => r.value !== null).length;
  return { name, filled, total: rows.length, rows };
}

export function EpusSourceDetail({
  rawData,
  fallbackName,
  fallbackNik,
  filterDate,
  ruangan,
  rightSlot,
}: {
  rawData: unknown;
  fallbackName: string;
  fallbackNik: string;
  filterDate?: string;
  ruangan?: string;
  rightSlot?: React.ReactNode;
}) {
  const built = useMemo(
    () => buildPatientFromRawSource("epus", rawData, fallbackNik),
    [rawData, fallbackNik],
  );

  const blocks = useMemo<FormBlock[]>(() => {
    const out: FormBlock[] = [];
    for (const section of built.sections) {
      if (section.groups.length > 0) {
        for (const group of section.groups) {
          const rows = itemsToRows(group.items);
          if (rows.length === 0) continue;
          out.push(makeBlock(`${section.label} > ${group.label}`, rows));
        }
      } else if (section.items.length > 0) {
        out.push(makeBlock(section.label, itemsToRows(section.items)));
      }
    }
    return out;
  }, [built]);

  const totals = useMemo(() => {
    let filled = 0;
    let total = 0;
    let formsWithData = 0;
    for (const b of blocks) {
      filled += b.filled;
      total += b.total;
      if (b.filled > 0) formsWithData += 1;
    }
    return { filled, total, formsWithData };
  }, [blocks]);

  const name = findIdentity(built, "Nama") || fallbackName || "(Tanpa Nama)";
  const nik = built.nik || fallbackNik || "";
  const dob = findIdentity(built, "Tanggal lahir");
  const age = findIdentity(built, "Umur");

  return (
    <div className="space-y-5">
      <Card className="shadow-sm">
        <CardContent className="pt-5">
          <div className="flex items-start justify-between flex-wrap gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <h2 className="text-xl font-bold text-[var(--foreground)]">
                  {name}
                </h2>
                <span className="text-xs font-medium rounded-full px-2.5 py-0.5 bg-emerald-100 text-emerald-800">
                  ePus
                </span>
              </div>
              {nik && (
                <div className="text-sm font-medium text-[var(--foreground)] mt-1">
                  NIK: {nik}
                </div>
              )}
              {dob && (
                <div className="text-sm font-medium text-[var(--foreground)]">
                  Tgl Lahir: {dob}
                </div>
              )}
              {age && (
                <div className="text-sm font-medium text-[var(--foreground)]">
                  Umur: {age}
                </div>
              )}
              {ruangan && (
                <div className="text-sm font-medium text-[var(--foreground)]">
                  Ruangan: {ruangan}
                </div>
              )}
              {filterDate && (
                <div className="mt-2 text-xs text-[var(--muted-foreground)]">
                  Scrape: {filterDate}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0 flex-wrap">
              <StatPill
                label="Form"
                value={totals.formsWithData}
                hint={`/ ${blocks.length}`}
                tone="blue"
              />
              <StatPill
                label="Field Terisi"
                value={totals.filled}
                hint={`/ ${totals.total}`}
                tone="green"
              />
              {rightSlot}
            </div>
          </div>
        </CardContent>
      </Card>

      {blocks.length === 0 && built.tables.length === 0 && (
        <Card className="shadow-sm">
          <CardContent className="py-8 text-center text-sm text-[var(--muted-foreground)]">
            No data available for ePus.
          </CardContent>
        </Card>
      )}

      {blocks.map((block, idx) => (
        <FormCard key={`${block.name}-${idx}`} block={block} />
      ))}

      {built.tables.map((tbl) => (
        <TableCard key={tbl.key} table={tbl} />
      ))}
    </div>
  );
}
