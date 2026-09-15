"use client";

import { useState } from "react";
import { format, parseISO } from "date-fns";
import { Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { WarmProgress } from "@/components/common/warm-progress";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import {
  useClearHipertensiChartsCache,
  useHipertensiCharts,
} from "@/lib/hooks/use-hipertensi-charts";
import { HipertensiChartsGrid } from "@shared/hipertensi/components/hipertensi-charts-grid";

export function HipertensiChartsSection() {
  const [puskesmasId, setPuskesmasId] = useState("");
  const pkDetail = usePuskesmas(puskesmasId || undefined);
  const charts = useHipertensiCharts(puskesmasId || undefined);
  const clearCache = useClearHipertensiChartsCache();
  const data = charts.data;
  const refreshing = charts.isFetching || clearCache.isPending;

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Dashboard Hipertensi</h2>
        <p className="text-sm text-[var(--muted-foreground)]">
          Analisis registri Hipertensi CKG (pasien terpadan ASIK + ePuskesmas) per
          puskesmas.
        </p>
      </div>

      <div className="w-full max-w-sm space-y-2">
        <Label>Puskesmas</Label>
        <AsyncCombobox
          value={puskesmasId || undefined}
          onChange={(v) => setPuskesmasId(v ?? "")}
          useOptions={usePuskesmasOptions}
          selectedLabel={pkDetail.data?.name}
          placeholder="Pilih puskesmas…"
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
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
            {data.computed_at && (
              <span>
                Dihitung {format(parseISO(data.computed_at), "yyyy-MM-dd HH:mm")}
                {data.cache_hit ? " · dari cache" : " · baru"} · cache ~30 jam
              </span>
            )}
            {refreshing && (
              <span className="inline-flex items-center gap-1">
                <Loader2 className="h-3 w-3 animate-spin" />
                menyegarkan…
              </span>
            )}
            <Button
              size="sm"
              variant="outline"
              className="h-6 gap-1 px-2 text-xs"
              onClick={() => clearCache.mutate(puskesmasId)}
              disabled={clearCache.isPending}
            >
              <RefreshCw className={`h-3 w-3 ${clearCache.isPending ? "animate-spin" : ""}`} />
              Bersihkan cache
            </Button>
          </div>

          <HipertensiChartsGrid data={data} puskesmasId={puskesmasId} />
        </div>
      )}
    </section>
  );
}
