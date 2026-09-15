"use client";

import { useState } from "react";
import { format, parseISO } from "date-fns";
import { RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/common/page-header";
import { StatCard } from "@/components/common/stat-card";
import { ErrorState } from "@/components/common/error-state";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import {
  useClearGdpSourceQualityCache,
  useGdpSourceQuality,
  useVisitSummary,
} from "@/lib/hooks/use-reports";

export default function VisitSummaryPage() {
  const [puskesmasId, setPuskesmasId] = useState("");
  const pkDetail = usePuskesmas(puskesmasId || undefined);
  const summary = useVisitSummary(puskesmasId || undefined);
  const gdp = useGdpSourceQuality(puskesmasId || undefined);

  const loading = summary.isLoading || (summary.isFetching && summary.isPlaceholderData);
  const d = summary.data;
  const scope = puskesmasId ? (pkDetail.data?.name ?? "…") : "Semua puskesmas";
  const maxDelayCount = Math.max(...(d?.delay_distribution.map((b) => b.count) ?? [0]), 1);

  const clearGdpCache = useClearGdpSourceQualityCache();
  // GD Puasa is a heavy cached scan. On a cold cache or after "Muat ulang" the
  // backend recomputes in the background and returns `computing` — show the
  // loading placeholder instead of stale or empty numbers, and poll.
  const gdpComputing = !!gdp.data?.computing;
  const gdpLoading =
    gdp.isLoading || gdp.isFetching || clearGdpCache.isPending || gdpComputing;
  const g = gdpLoading ? undefined : gdp.data;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Ringkasan Kunjungan"
        description="Cakupan data ASIK dan ePuskesmas per kunjungan. Kunjungan yang sama yang tercatat di tanggal berbeda dihitung sebagai satu kunjungan."
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="space-y-2 md:col-span-2">
          <Label>Puskesmas</Label>
          <div className="flex items-center gap-2">
            <div className="flex-1">
              <AsyncCombobox
                value={puskesmasId || undefined}
                onChange={(v) => setPuskesmasId(v ?? "")}
                useOptions={usePuskesmasOptions}
                selectedLabel={pkDetail.data?.name}
                placeholder="Semua puskesmas"
              />
            </div>
            {puskesmasId && (
              <Button variant="outline" size="sm" onClick={() => setPuskesmasId("")}>
                Semua
              </Button>
            )}
          </div>
        </div>
      </div>

      {summary.error && <ErrorState error={summary.error} />}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-[var(--muted-foreground)]">
          Semua Kunjungan — {scope}
        </h2>
        <p className="text-xs text-[var(--muted-foreground)]">
          Mencakup semua kunjungan, bukan hanya CKG.
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <StatCard
            title="Data di ASIK"
            value={d?.data_on_asik.toLocaleString()}
            subtext="Total kunjungan yang ada di ASIK"
            loading={loading}
          />
          <StatCard
            title="Data di ePuskesmas"
            value={d?.data_on_epus.toLocaleString()}
            subtext="Total kunjungan yang ada di ePuskesmas"
            loading={loading}
          />
          <StatCard
            title="Cocok di Keduanya"
            value={d?.matched.toLocaleString()}
            subtext="NIK ada di ASIK dan ePuskesmas"
            loading={loading}
          />
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-[var(--muted-foreground)]">
          Input Terlambat — {scope}
        </h2>
        <p className="text-xs text-[var(--muted-foreground)]">
          Hanya data CKG (sudah CKG). Yaitu saat kunjungan yang sama dimasukkan ke
          ePuskesmas dan ASIK di hari yang berbeda.
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <StatCard
            title="Tandai CKG"
            value={d?.tandai_ckg.toLocaleString()}
            subtext="Kunjungan yang ditandai sudah CKG"
            loading={loading}
          />
          <StatCard
            title="Terlambat Diinput"
            value={d?.delayed_ckg.toLocaleString()}
            subtext="Diinput di hari berbeda pada kedua sistem"
            loading={loading}
          />
          <StatCard
            title="Persentase Terlambat"
            value={d ? `${d.delayed_ckg_pct.toFixed(1)}%` : undefined}
            subtext="Bagian dari kunjungan CKG yang terlambat"
            loading={loading}
          />
        </div>

        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
          <h3 className="mb-3 text-sm font-medium text-[var(--muted-foreground)]">
            Terlambat berapa hari
          </h3>
          {loading ? (
            <p className="text-sm text-[var(--muted-foreground)]">—</p>
          ) : d && d.delayed_ckg > 0 ? (
            <ul className="space-y-2">
              {d.delay_distribution.map((b) => (
                <li key={b.days} className="flex items-center gap-3 text-sm">
                  <span className="w-16 shrink-0 tabular-nums text-[var(--muted-foreground)]">
                    {b.days} hari
                  </span>
                  <div className="h-4 flex-1 overflow-hidden rounded bg-[var(--muted)]">
                    <div
                      className="h-full rounded bg-[var(--primary)]"
                      style={{ width: `${(b.count / maxDelayCount) * 100}%` }}
                    />
                  </div>
                  <span className="w-24 shrink-0 text-right tabular-nums">
                    {b.count.toLocaleString()} ({b.pct.toFixed(1)}%)
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[var(--muted-foreground)]">
              Tidak ada kunjungan yang terlambat diinput.
            </p>
          )}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-[var(--muted-foreground)]">
          Sumber Data GD Puasa — {scope}
        </h2>
        <p className="text-xs text-[var(--muted-foreground)]">
          Hanya data CKG (sudah CKG). Menunjukkan asal nilai GD Puasa tiap orang. Hasil dari
          Laboratorium lebih dapat dipercaya daripada yang diketik di form pemeriksaan PTM.
        </p>
        {gdpComputing && (
          <p className="flex items-center gap-1 text-xs text-[var(--muted-foreground)]">
            <RefreshCw className="h-3 w-3 animate-spin" />
            Menghitung ulang…
          </p>
        )}
        {gdp.data && !gdpComputing && gdp.data.computed_at && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted-foreground)]">
            <span>
              Dihitung {format(parseISO(gdp.data.computed_at!), "yyyy-MM-dd HH:mm")}
              {gdp.data.cache_hit ? " · tersimpan" : " · baru"}
            </span>
            <Button
              size="sm"
              variant="outline"
              className="h-6 gap-1 px-2 text-xs"
              onClick={() => clearGdpCache.mutate({ puskesmasId: puskesmasId || undefined })}
              disabled={clearGdpCache.isPending || gdpLoading}
            >
              <RefreshCw className={`h-3 w-3 ${clearGdpCache.isPending ? "animate-spin" : ""}`} />
              Muat ulang
            </Button>
          </div>
        )}
        {gdp.error && <ErrorState error={gdp.error} />}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <StatCard
            title="Orang dengan GD Puasa"
            value={g?.people_with_gdp.toLocaleString()}
            subtext="Orang yang punya nilai GD Puasa"
            loading={gdpLoading}
          />
          <StatCard
            title="Dari Laboratorium"
            value={g?.lab_backed.toLocaleString()}
            subtext="Punya hasil Laboratorium (lebih dipercaya)"
            loading={gdpLoading}
          />
          <StatCard
            title="Hanya dari PTM"
            value={g?.ptm_fallback.toLocaleString()}
            subtext={
              g
                ? `${g.ptm_fallback_pct.toFixed(1)}% dari ${g.people_with_gdp.toLocaleString()} · tidak ada hasil lab`
                : undefined
            }
            loading={gdpLoading}
          />
        </div>
      </section>
    </div>
  );
}
