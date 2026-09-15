"use client";

import { useMemo } from "react";
import { Card, CardContent } from "@/components/ui/card";
import {
  FormCard,
  StatPill,
  formatValue,
  type FieldRow,
  type FormBlock,
} from "./form-card";
import { TatalaksanaCard } from "./tatalaksana-card";

type JsonRecord = Record<string, unknown>;

function isRecord(v: unknown): v is JsonRecord {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
function asRecord(v: unknown): JsonRecord {
  return isRecord(v) ? v : {};
}
function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function walkLeaves(
  value: unknown,
  path: string[] = [],
): Array<{ path: string[]; value: unknown }> {
  if (isRecord(value)) {
    return Object.entries(value).flatMap(([k, c]) =>
      walkLeaves(c, [...path, k]),
    );
  }
  if (Array.isArray(value)) {
    return value.flatMap((c, i) => walkLeaves(c, [...path, String(i + 1)]));
  }
  return path.length > 0 ? [{ path, value }] : [];
}

function recordToRows(record: unknown): FieldRow[] {
  return walkLeaves(record).map(({ path, value }) => ({
    label: path.join(" > "),
    value: formatValue(value),
  }));
}

function makeBlock(name: string, rows: FieldRow[]): FormBlock {
  const filled = rows.filter((r) => r.value !== null).length;
  return { name, filled, total: rows.length, rows };
}

// Each entry drives both the render group heading and the per-form fallback
// name. Add a row here for any future top-level ASIK form array — nothing
// else needs to change (totals, empty-state, and render all iterate `groups`).
const ASIK_FORM_GROUPS = [
  { key: "pelayanan_nakes", label: "Pelayanan oleh Nakes", fallback: "Pelayanan Nakes" },
  { key: "pemeriksaan_mandiri", label: "Pemeriksaan Mandiri", fallback: "Pemeriksaan Mandiri" },
] as const;

function buildFormGroup(
  record: JsonRecord,
  arrayKey: string,
  fallback: string,
): FormBlock[] {
  const blocks: FormBlock[] = [];
  asArray(record[arrayKey]).forEach((entry, idx) => {
    const er = asRecord(entry);
    const layanan =
      typeof er.layanan === "string" && er.layanan.trim()
        ? er.layanan.trim()
        : `${fallback} ${idx + 1}`;
    const rows = recordToRows(er.form_data);
    if (rows.length === 0) return;
    blocks.push(makeBlock(layanan, rows));
  });
  return blocks;
}

function buildAsikBlocks(raw: unknown): {
  identity: FormBlock[];
  groups: { key: string; label: string; blocks: FormBlock[] }[];
} {
  const record = asRecord(raw);
  const detail = asRecord(record.detail_data);
  const identity: FormBlock[] = [];

  const identitas = recordToRows(detail.data_individu);
  if (identitas.length > 0) identity.push(makeBlock("Identitas Pasien", identitas));

  const domisili = recordToRows(detail.data_domisili);
  if (domisili.length > 0) identity.push(makeBlock("Alamat & Domisili", domisili));

  const groups = ASIK_FORM_GROUPS.map((g) => ({
    key: g.key,
    label: g.label,
    blocks: buildFormGroup(record, g.key, g.fallback),
  }));

  return { identity, groups };
}

function readIndividuField(raw: unknown, key: string): string | null {
  const di = asRecord(asRecord(asRecord(raw).detail_data).data_individu);
  const v = di[key];
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

function readNik(raw: unknown, fallback: string): string {
  return readIndividuField(raw, "NIK") ?? fallback ?? "";
}

function readName(raw: unknown, fallback: string): string {
  return readIndividuField(raw, "Nama") ?? fallback ?? "(Tanpa Nama)";
}

export function AsikSourceDetail({
  rawData,
  fallbackName,
  fallbackNik,
  filterDate,
  rightSlot,
}: {
  rawData: unknown;
  fallbackName: string;
  fallbackNik: string;
  filterDate?: string;
  rightSlot?: React.ReactNode;
}) {
  const { identity: identityBlocks, groups } = useMemo(
    () => buildAsikBlocks(rawData),
    [rawData],
  );

  const totals = useMemo(() => {
    let filled = 0;
    let total = 0;
    let formsWithData = 0;
    for (const b of [...identityBlocks, ...groups.flatMap((g) => g.blocks)]) {
      filled += b.filled;
      total += b.total;
      if (b.filled > 0) formsWithData += 1;
    }
    return { filled, total, formsWithData };
  }, [identityBlocks, groups]);

  const totalBlockCount =
    identityBlocks.length +
    groups.reduce((n, g) => n + g.blocks.length, 0);

  const name = readName(rawData, fallbackName);
  const nik = readNik(rawData, fallbackNik);
  const dob = readIndividuField(rawData, "Tanggal Lahir");
  const age = readIndividuField(rawData, "Umur");

  // Tatalaksana (follow-up) is ASIK-only data carried in the same blob.
  const tatalaksana = asRecord(rawData).tatalaksana;
  const hasTatalaksana =
    asArray(asRecord(tatalaksana).rows).length > 0 ||
    typeof asRecord(tatalaksana).error === "string";

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
                <span className="text-xs font-medium rounded-full px-2.5 py-0.5 bg-blue-100 text-blue-800">
                  ASIK
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
                hint={`/ ${totalBlockCount}`}
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

      {totalBlockCount === 0 && !hasTatalaksana && (
        <Card className="shadow-sm">
          <CardContent className="py-8 text-center text-sm text-[var(--muted-foreground)]">
            No data available for ASIK.
          </CardContent>
        </Card>
      )}

      {identityBlocks.map((block, idx) => (
        <FormCard key={`identity-${block.name}-${idx}`} block={block} />
      ))}

      {hasTatalaksana && <TatalaksanaCard data={tatalaksana} />}

      {groups.map(
        (group) =>
          group.blocks.length > 0 && (
            <div key={group.key} className="space-y-3">
              <GroupHeading label={group.label} count={group.blocks.length} />
              {group.blocks.map((block, idx) => (
                <FormCard key={`${group.key}-${block.name}-${idx}`} block={block} />
              ))}
            </div>
          ),
      )}
    </div>
  );
}

function GroupHeading({ label, count }: { label: string; count: number }) {
  return (
    <div className="flex items-center gap-2 pt-1">
      <h3 className="text-sm font-semibold text-[var(--foreground)] uppercase tracking-wide">
        {label}
      </h3>
      <span className="text-xs text-[var(--muted-foreground)]">
        ({count} formulir)
      </span>
    </div>
  );
}
