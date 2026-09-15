"use client";

import { useMemo } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorState } from "@/components/common/error-state";
import { useAsikPreview } from "@shared/patients/use-patients";
import {
  FormCard,
  StatPill,
  formatValue,
  type FieldRow,
  type FormBlock,
} from "./form-card";

export function EpusToAsikDetail({
  patientId,
  fallbackName,
  fallbackNik,
  rightSlot,
}: {
  patientId: string;
  fallbackName: string;
  fallbackNik: string;
  rightSlot?: React.ReactNode;
}) {
  const { data, isLoading, error } = useAsikPreview(patientId, true);

  const blocks = useMemo<FormBlock[]>(() => {
    if (!data) return [];
    return Object.entries(data.forms).map(([name, fields]) => {
      const displayName =
        name === "identitas_pasien" ? "Identitas Pasien" : name;
      const rows: FieldRow[] = Object.entries(fields).map(([label, value]) => ({
        label,
        value: formatValue(value),
      }));
      const filled = rows.filter((r) => r.value !== null).length;
      return { name: displayName, filled, total: rows.length, rows };
    });
  }, [data]);

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

  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="h-32 rounded-lg border border-[var(--border)] animate-pulse bg-[var(--muted)]" />
        <div className="h-64 rounded-lg border border-[var(--border)] animate-pulse bg-[var(--muted)]" />
      </div>
    );
  }

  if (error) return <ErrorState error={error} />;
  if (!data) return null;

  return (
    <div className="space-y-5">
      <Card className="shadow-sm">
        <CardContent className="pt-5">
          <div className="flex items-start justify-between flex-wrap gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <h2 className="text-xl font-bold text-[var(--foreground)]">
                  {fallbackName || "(Tanpa Nama)"}
                </h2>
                <span className="text-xs font-medium rounded-full px-2.5 py-0.5 bg-amber-100 text-amber-800">
                  Hasil Konversi Otomatis
                </span>
              </div>
              {fallbackNik && (
                <div className="text-sm font-medium text-[var(--foreground)] mt-1">
                  NIK: {fallbackNik}
                </div>
              )}
              <p className="mt-2 text-xs text-[var(--muted-foreground)] max-w-prose">
                Hasil pengisian formulir ASIK secara otomatis dari data
                ePuskesmas. Field tanpa sumber di ePuskesmas dibiarkan kosong
                untuk diisi manual.
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0 flex-wrap">
              <StatPill
                label="Form"
                value={totals.formsWithData}
                hint={`/ ${blocks.length}`}
                tone="amber"
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

      {blocks.length === 0 && (
        <Card className="shadow-sm">
          <CardContent className="py-8 text-center text-sm text-[var(--muted-foreground)]">
            Tidak ada form yang dapat dikonversi dari data ePuskesmas.
          </CardContent>
        </Card>
      )}

      {blocks.map((block) => (
        <FormCard
          key={block.name}
          block={block}
          emptyHint="Form ini tersedia di ASIK untuk pasien tetapi tidak memiliki sumber di ePuskesmas. Diisi manual saat input ke ASIK."
        />
      ))}
    </div>
  );
}
