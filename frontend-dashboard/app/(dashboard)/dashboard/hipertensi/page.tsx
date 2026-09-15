"use client";

import { useState } from "react";
import { format, parseISO } from "date-fns";
import { PageHeader } from "@/components/common/page-header";
import { Label } from "@/components/ui/label";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { WarmProgress } from "@/components/common/warm-progress";
import { usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import { useHipertensiCharts } from "@/lib/hooks/use-hipertensi-charts";
import { HipertensiChartsGrid } from "@shared/hipertensi/components/hipertensi-charts-grid";

export default function DashboardHipertensiPage() {
  const [puskesmasId, setPuskesmasId] = useState<string | undefined>();
  const charts = useHipertensiCharts(puskesmasId);
  const data = charts.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard Hipertensi"
        description="Analisis registri Hipertensi CKG (pasien terpadan ASIK + ePuskesmas) per puskesmas."
      />

      <div className="max-w-sm space-y-2">
        <Label>Puskesmas</Label>
        <AsyncCombobox
          value={puskesmasId}
          onChange={setPuskesmasId}
          useOptions={usePuskesmasOptions}
          placeholder="Pilih Puskesmas"
        />
      </div>

      {!puskesmasId ? (
        <p className="text-sm text-[var(--muted-foreground)]">
          Pilih puskesmas untuk menampilkan grafik.
        </p>
      ) : charts.isError ? (
        <p className="text-sm text-[var(--muted-foreground)]">Gagal memuat data.</p>
      ) : charts.isLoading || data?.computing || !data ? (
        <WarmProgress progress={data?.progress} />
      ) : (
        <div className="space-y-4">
          {data.computed_at && (
            <p className="text-xs text-[var(--muted-foreground)]">
              Computed {format(parseISO(data.computed_at), "yyyy-MM-dd HH:mm")}
              {data.cache_hit ? " · cached" : " · fresh"} · hasil di-cache ~30 jam,
              dihitung ulang otomatis tiap pagi ~05.00 WIB.
            </p>
          )}
          <HipertensiChartsGrid data={data} puskesmasId={puskesmasId} />
        </div>
      )}
    </div>
  );
}
