"use client";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatValue, type FieldRow } from "./form-card";

// Tatalaksana (follow-up treatment) lives inside the ASIK source blob as
// `scraped_asik_data.tatalaksana` (see scrapers/asik/CLAUDE.md). It is ASIK-only
// data — the merge does not consume it — so it renders in the ASIK source tab.
// This is a pure presentational component: it reads the already-decrypted blob
// and never fetches.

type JsonRecord = Record<string, unknown>;

const isRecord = (v: unknown): v is JsonRecord =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const asRecord = (v: unknown): JsonRecord => (isRecord(v) ? v : {});
const asArray = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const asStr = (v: unknown): string | null =>
  typeof v === "string" && v.trim() ? v.trim() : null;

function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Flatten a row's `form_data` ({question: answer}, incl. indexed repeats like
// "Pilih obat (2)") into label/value rows in their original (form) order.
function formDataRows(formData: unknown): FieldRow[] {
  return Object.entries(asRecord(formData))
    .filter(([k]) => !k.startsWith("_"))
    .map(([label, value]) => ({ label, value: formatValue(value) }));
}

type TataRow = {
  kelompok: string | null;
  name: string | null;
  hasil: string | null;
  statusText: string;
  isDone: boolean;
  formError: string | null;
  fields: FieldRow[];
};

function parseRow(raw: unknown): TataRow {
  const r = asRecord(raw);
  const status = (asStr(r.status) ?? "").toLowerCase();
  const statusLabel = asStr(r.status_label);
  const isDone = status !== "belum_dilakukan" && status !== "";
  return {
    kelompok: asStr(r.kelompok_skrinning),
    name: asStr(r.tatalaksana_name),
    hasil: asStr(r.hasil_pemeriksaan),
    // Backend only prettifies "belum_dilakukan" → "Belum tatalaksana"; for other
    // statuses status_label echoes the raw enum, so title-case it for display.
    statusText:
      statusLabel && statusLabel.toLowerCase() !== status
        ? statusLabel
        : titleCase(asStr(r.status) ?? "—"),
    isDone,
    formError: asStr(r.form_read_error),
    fields: formDataRows(r.form_data),
  };
}

export function TatalaksanaCard({ data }: { data: unknown }) {
  const t = asRecord(data);
  const error = asStr(t.error);
  const rows = asArray(t.rows).map(parseRow);

  if (rows.length === 0 && !error) return null;

  const klaster = asStr(t.klaster);
  const screeningDate = asStr(t.screening_date);
  const doneCount = rows.filter((r) => r.isDone).length;

  return (
    <Card className="shadow-sm overflow-hidden p-0 gap-0 border-teal-200">
      <CardHeader className="py-3 px-5 bg-teal-50 border-b border-teal-200">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-sm text-[var(--foreground)]">
              Tatalaksana
            </h3>
            {klaster && (
              <span className="text-xs text-[var(--muted-foreground)]">
                {klaster}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {screeningDate && (
              <span className="text-xs text-[var(--muted-foreground)]">
                {screeningDate}
              </span>
            )}
            {rows.length > 0 && (
              <span className="text-xs font-medium rounded px-2 py-0.5 bg-teal-100 text-teal-800">
                {doneCount} / {rows.length} tertatalaksana
              </span>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-0 divide-y divide-[var(--border)]">
        {error && (
          <div className="px-5 py-3 text-xs text-red-700 bg-red-50">
            Gagal memuat tatalaksana: {error}
          </div>
        )}

        {rows.map((row, idx) => (
          <div key={`${row.name ?? "row"}-${idx}`} className="px-5 py-3 space-y-2">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div>
                {row.kelompok && (
                  <div className="text-[11px] uppercase tracking-wide text-[var(--muted-foreground)]">
                    {row.kelompok}
                  </div>
                )}
                <div className="text-sm font-semibold text-[var(--foreground)]">
                  {row.name ?? "—"}
                </div>
                {row.hasil && (
                  <div className="text-xs text-[var(--muted-foreground)]">
                    {row.hasil}
                  </div>
                )}
              </div>
              <span
                className={cn(
                  "text-xs font-medium rounded-full px-2.5 py-0.5 shrink-0",
                  row.isDone
                    ? "bg-green-100 text-green-800"
                    : "bg-red-100 text-red-700",
                )}
              >
                {row.statusText}
              </span>
            </div>

            {row.formError && (
              <div className="text-xs text-amber-700 bg-amber-50 rounded px-2 py-1">
                Form gagal dibaca: {row.formError}
              </div>
            )}

            {row.fields.length > 0 ? (
              <div className="rounded-md border border-[var(--border)] divide-y divide-[var(--border)] bg-[var(--muted)]/20">
                {row.fields.map((f, i) => (
                  <div
                    key={`${f.label}-${i}`}
                    className="grid grid-cols-[2fr_1fr] gap-4 px-3 py-2 items-start"
                  >
                    <span className="text-xs text-[var(--muted-foreground)]">
                      {f.label}
                    </span>
                    <span
                      className={cn(
                        "text-sm",
                        f.value === null
                          ? "text-[var(--muted-foreground)] italic"
                          : "font-medium text-[var(--foreground)]",
                      )}
                    >
                      {f.value ?? "—"}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              !row.formError && (
                <div className="text-xs text-[var(--muted-foreground)] italic">
                  {row.isDone
                    ? "Tidak ada detail form."
                    : "Belum tatalaksana — belum ada tindak lanjut yang dicatat."}
                </div>
              )
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
