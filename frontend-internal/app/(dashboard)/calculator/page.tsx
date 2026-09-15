"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { Info } from "lucide-react";
import { StatCard } from "@/components/common/stat-card";
import { EmptyState } from "@/components/common/empty-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCapacityStats } from "@/lib/hooks/use-stats";
import { derive } from "@/lib/calculator/derive";
import { recommend } from "@/components/calculator/server-tiers";
import type { CalcInputs } from "@/lib/calculator/derive";

const ConcurrencyBars = dynamic(
  () => import("@/components/calculator/concurrency-bars"),
  { ssr: false },
);
const CostBreakdown = dynamic(
  () => import("@/components/calculator/cost-breakdown"),
  { ssr: false },
);

const WINDOWS = [7, 30, 90] as const;

function NumberInput({
  label,
  value,
  onChange,
  min = 1,
  step = 1,
  hint,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  step?: number;
  hint?: string;
}) {
  return (
    <div className="space-y-1">
      <label className="block text-xs font-medium text-[var(--muted-foreground)]">{label}</label>
      <input
        type="number"
        min={0}
        step={step}
        value={value}
        onChange={(e) => {
          // Allow 0 as a transient typing state (clearing the field) so users can
          // retype values; min is enforced visually via the spinner only.
          const v = Number(e.target.value);
          if (!isNaN(v) && v >= 0) onChange(v);
        }}
        onBlur={(e) => {
          const v = Number(e.target.value);
          if (isNaN(v) || v < min) onChange(min);
        }}
        className="w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-sm tabular-nums focus:outline-none focus:ring-1 focus:ring-[var(--ring)]"
      />
      {hint ? (
        <p className="text-[11px] leading-snug text-[var(--muted-foreground)]/80">{hint}</p>
      ) : null}
    </div>
  );
}

export default function CalculatorPage() {
  const [windowDays, setWindowDays] = useState<7 | 30 | 90>(30);
  const stats = useCapacityStats(windowDays);

  const [inputs, setInputs] = useState<CalcInputs>({
    puskesmasCount: 10,
    dailyPatientsPerPuskesmas: 150,
    dailyMatchesPerPuskesmas: 10,
    runWindowHours: 2,
    concurrency: 2,
  });

  const set = <K extends keyof CalcInputs>(k: K) => (v: number) =>
    setInputs((prev) => ({ ...prev, [k]: v }));

  const result = useMemo(() => {
    if (!stats.data) return null;
    return derive(inputs, stats.data);
  }, [inputs, stats.data]);

  const recs = useMemo(() => {
    if (!result) return [];
    return recommend(result.requiredCores, result.peakRamMb);
  }, [result]);

  const noData =
    stats.data &&
    stats.data.scrape.sample_size === 0 &&
    stats.data.merge.sample_size === 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Kalkulator Kapasitas</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Perkirakan spesifikasi server dan biaya bulanan untuk deployment kamu.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="flex gap-1">
            {WINDOWS.map((w) => (
              <button
                key={w}
                onClick={() => setWindowDays(w)}
                className={`rounded px-2 py-0.5 text-xs transition-colors ${
                  windowDays === w
                    ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
                }`}
              >
                {w}d
              </button>
            ))}
          </div>
          <p className="text-[11px] text-[var(--muted-foreground)]/80">
            Jendela lookback telemetri
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px_1fr]">
        {/* ── Inputs ─────────────────────────────────────────────────── */}
        <Card className="h-fit lg:sticky lg:top-6">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Input</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <NumberInput
              label="Puskesmas"
              value={inputs.puskesmasCount}
              onChange={set("puskesmasCount")}
              hint="Berapa puskesmas yang dilayani deployment ini."
            />
            <NumberInput
              label="Pasien harian per puskesmas"
              value={inputs.dailyPatientsPerPuskesmas}
              onChange={set("dailyPatientsPerPuskesmas")}
              hint="Rata-rata pasien baru yang di-scrape tiap puskesmas per hari. Menentukan beban scrape."
            />
            <NumberInput
              label="Kecocokan harian per puskesmas"
              value={inputs.dailyMatchesPerPuskesmas}
              onChange={set("dailyMatchesPerPuskesmas")}
              hint="Rekam pasien yang di-merge LLM per hari per puskesmas. Subset dari pasien — hanya yang butuh pencocokan AI."
            />
            <NumberInput
              label="Target jendela run (jam)"
              value={inputs.runWindowHours}
              onChange={set("runWindowHours")}
              min={0.5}
              step={0.5}
              hint="Jam per hari yang tersedia untuk menyelesaikan pekerjaan hari itu. Jendela lebih pendek → butuh lebih banyak core."
            />
            <NumberInput
              label="Job paralel"
              value={inputs.concurrency}
              onChange={set("concurrency")}
              hint="Job yang berjalan paralel. Samakan dengan worker --concurrency. RAM tumbuh linear dengan angka ini."
            />

            {stats.data && (
              <p className="flex items-center gap-1 text-xs text-[var(--muted-foreground)]">
                <Info className="h-3 w-3 shrink-0" />
                Berdasarkan {stats.data.scrape.sample_size} job scrape &{" "}
                {stats.data.merge.sample_size} job merge dalam {windowDays}d terakhir.
              </p>
            )}
          </CardContent>
        </Card>

        {/* ── Results ────────────────────────────────────────────────── */}
        <div className="space-y-6">
          {noData ? (
            <EmptyState
              title="Belum ada data"
              description="Jalankan job scrape dan merge dulu. Hasil membaik dengan lebih banyak sampel."
            />
          ) : (
            <>
              {(result?.scrapeDataMissing && inputs.dailyPatientsPerPuskesmas > 0) ||
              (result?.mergeDataMissing && inputs.dailyMatchesPerPuskesmas > 0) ? (
                <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
                  {result.scrapeDataMissing && inputs.dailyPatientsPerPuskesmas > 0 && (
                    <p>Tidak ada telemetri scrape pada jendela ini — perhitungan scrape dilaporkan 0. Jalankan job scrape untuk mengisi.</p>
                  )}
                  {result.mergeDataMissing && inputs.dailyMatchesPerPuskesmas > 0 && (
                    <p>Tidak ada telemetri merge pada jendela ini — perhitungan merge dilaporkan 0. Jalankan job merge untuk mengisi.</p>
                  )}
                </div>
              ) : null}

              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                <StatCard
                  title="Pasien harian"
                  value={result?.dailyPatients.toLocaleString()}
                  loading={!result}
                />
                <StatCard
                  title="Kecocokan harian"
                  value={result?.dailyMatches.toLocaleString()}
                  loading={!result}
                />
                <StatCard
                  title="Core dibutuhkan"
                  value={result ? `≥ ${result.requiredCores}` : undefined}
                  subtext={`untuk selesai dalam ${inputs.runWindowHours}j`}
                  loading={!result}
                />
                <StatCard
                  title="RAM puncak"
                  value={
                    result
                      ? result.peakRamMb >= 1024
                        ? `${(result.peakRamMb / 1024).toFixed(1)} GB`
                        : `${result.peakRamMb.toFixed(0)} MB`
                      : undefined
                  }
                  subtext={`pada ${inputs.concurrency} paralel`}
                  loading={!result}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <StatCard
                  title="Biaya LLM harian"
                  value={result ? `$${result.dailyLlmCostUsd.toFixed(2)}` : undefined}
                  loading={!result}
                />
                <StatCard
                  title="Biaya LLM bulanan"
                  value={result ? `$${result.monthlyLlmCostUsd.toFixed(2)}` : undefined}
                  loading={!result}
                />
              </div>

              {result && (
                <>
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm">vCPU dibutuhkan vs paralel</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <ConcurrencyBars
                          data={result.coresByConc.map((d) => ({
                            label: `×${d.concurrency}`,
                            value: d.cores,
                          }))}
                          color="#6366f1"
                          unit="core"
                        />
                      </CardContent>
                    </Card>
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm">RAM puncak vs paralel</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <ConcurrencyBars
                          data={result.ramByConc.map((d) => ({
                            label: `×${d.concurrency}`,
                            value: Math.ceil(d.ramMb / 1024),
                          }))}
                          color="#f59e0b"
                          unit="GB"
                        />
                      </CardContent>
                    </Card>
                  </div>

                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm">Rincian biaya LLM bulanan</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <CostBreakdown
                        scrape={result.scrapeLlmShareUsd * 30}
                        merge={result.mergeLlmShareUsd * 30}
                      />
                    </CardContent>
                  </Card>

                  {recs.length > 0 && (
                    <Card>
                      <CardHeader className="pb-3">
                        <CardTitle className="text-sm">Rekomendasi tier server</CardTitle>
                        <p className="text-xs text-[var(--muted-foreground)]">
                          Tier termurah yang cukup per provider. Harga perkiraan — verifikasi sebelum membeli.
                        </p>
                      </CardHeader>
                      <CardContent>
                        <div className="overflow-x-auto">
                          <table className="w-full text-sm">
                            <thead>
                              <tr className="border-b text-left text-xs text-[var(--muted-foreground)]">
                                <th className="pb-2 pr-4">Provider</th>
                                <th className="pb-2 pr-4">SKU</th>
                                <th className="pb-2 pr-4">vCPU</th>
                                <th className="pb-2 pr-4">RAM</th>
                                <th className="pb-2">~$/bulan</th>
                              </tr>
                            </thead>
                            <tbody>
                              {recs.map((r) => (
                                <tr key={r.provider} className="border-b last:border-0">
                                  <td className="py-2 pr-4 font-medium">{r.provider}</td>
                                  <td className="py-2 pr-4 font-mono text-xs">{r.name}</td>
                                  <td className="py-2 pr-4">{r.vcpu}</td>
                                  <td className="py-2 pr-4">{r.ramGB} GB</td>
                                  <td className="py-2">${r.monthlyUsd}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </CardContent>
                    </Card>
                  )}

                  {recs.length === 0 && (result.requiredCores > 0 || result.peakRamMb > 0) && (
                    <Card>
                      <CardContent className="py-4 text-sm text-[var(--muted-foreground)]">
                        Kebutuhan melebihi tier yang terdaftar. Kamu butuh minimal{" "}
                        <strong>{result.requiredCores} vCPU</strong> dan{" "}
                        <strong>{(result.peakRamMb / 1024).toFixed(1)} GB RAM</strong>.
                        Pertimbangkan bare-metal atau instance kustom.
                      </CardContent>
                    </Card>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
