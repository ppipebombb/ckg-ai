"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { HipertensiCharts } from "@/lib/api/hipertensi-charts";
import { GapTatalaksanaLink } from "./gap-tatalaksana-link";
import { COLORS, TEXT_COLORS, fmtCount, fmtYm, pct } from "./charts/theme";

// The 8-chart Hipertensi grid, rendered identically by both apps. Everything a
// reader sees — titles, colours, denominators, the wording of every headline —
// lives here and only here, so the two apps cannot drift. Each app supplies its
// own page chrome (header, puskesmas picker, cache controls) around it.

// Heavy recharts widgets: never on SSR — recharts v3 renders nothing
// server-side, so SSR would only cost bundle weight (README rule 4).
const ChartFallback = () => (
  <div className="h-[300px] w-full animate-pulse rounded-md bg-[var(--muted)]" />
);
const CascadeChart = dynamic(
  () => import("./charts/cascade-chart").then((m) => m.CascadeChart),
  { ssr: false, loading: ChartFallback },
);
const TertatalaksanaChart = dynamic(
  () => import("./charts/tertatalaksana-chart").then((m) => m.TertatalaksanaChart),
  { ssr: false, loading: ChartFallback },
);
const MonthlyAreaChart = dynamic(
  () => import("./charts/monthly-area-chart").then((m) => m.MonthlyAreaChart),
  { ssr: false, loading: ChartFallback },
);
const ProporsiChart = dynamic(
  () => import("./charts/proporsi-chart").then((m) => m.ProporsiChart),
  { ssr: false, loading: ChartFallback },
);
const StackedFunnelChart = dynamic(
  () => import("./charts/stacked-funnel-chart").then((m) => m.StackedFunnelChart),
  { ssr: false, loading: ChartFallback },
);

function ChartCard({
  title,
  titleColor,
  description,
  action,
  children,
}: {
  title: string;
  titleColor?: string;
  /** Omitted on the two cascade-style cards, which read from their own bars. */
  description?: React.ReactNode;
  /** Optional control in the header's top-right (e.g. a drill-down link). */
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base" style={titleColor ? { color: titleColor } : undefined}>
            {title}
          </CardTitle>
          {action}
        </div>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

/**
 * Headline under a time-series card's title (charts 2-5): the last shown
 * month's share in large type in the series colour, then that month's absolute
 * count. Charts 3-5 plot a share, so the card is where their raw count is
 * stated; chart 2 plots counts and the card is where its share is stated.
 */
function ChartStat({
  color,
  percent,
  count,
  noun,
}: {
  color: string;
  percent: number;
  count: number;
  noun: string;
}) {
  return (
    <>
      <div className="text-2xl font-bold" style={{ color }}>
        {percent}%
      </div>
      <div className="text-[var(--foreground)]">
        {fmtCount(count)} {noun}
      </div>
    </>
  );
}

export function HipertensiChartsGrid({
  data,
  puskesmasId,
}: {
  data: HipertensiCharts;
  /** Carried into the Gap Tatalaksana filter by the "Lihat Detail" link. */
  puskesmasId: string;
}) {
  // Computed across all months from Feb 2025, displayed only for the trailing 12.
  const view = useMemo(() => data.monthly.slice(-12), [data.monthly]);
  const currentMonthLabel = data.current_month ? fmtYm(data.current_month) : "bulan berjalan";
  // Headline stats on the time-series cards read from the last month shown.
  const last = view.length ? view[view.length - 1] : undefined;

  const kohort2Tahun = data.kohort_2tahun;
  const ht2026 = data.hipertensi_2026;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <ChartCard title="Hipertensi 2 Tahun Berturut-turut">
        <StackedFunnelChart
          bars={[
            { name: "Hipertensi CKG 2025", segments: [{ label: "", value: kohort2Tahun.hipertensi_2025, fill: COLORS.reg2025 }] },
            { name: "Diperiksa CKG 2026", segments: [{ label: "", value: kohort2Tahun.diperiksa_2026, fill: COLORS.bothYears }] },
            {
              name: "Hipertensi 2026",
              segments: [
                { label: "Ya (≥140/90)", value: kohort2Tahun.td_2026_tinggi, fill: COLORS.tidakTercapai },
                { label: "Tidak (<140/90)", value: kohort2Tahun.td_2026_terkendali, fill: COLORS.tercapai },
              ],
            },
            {
              name: "Diobati",
              segments: [
                { label: "Ya (≥140/90) - Diobati", value: kohort2Tahun.tinggi_diobati, fill: COLORS.tinggiDiobati },
                { label: "Ya (≥140/90) - Tidak Diobati", value: kohort2Tahun.tinggi_tidak_diobati, fill: COLORS.tinggiTidakDiobati },
                { label: "Tidak (<140/90) - Diobati", value: kohort2Tahun.terkendali_diobati, fill: COLORS.terkendaliDiobati },
                { label: "Tidak (<140/90) - Tidak Diobati", value: kohort2Tahun.terkendali_tidak_diobati, fill: COLORS.terkendaliTidakDiobati },
              ],
            },
          ]}
        />
      </ChartCard>

      <ChartCard title="Hipertensi CKG 2026">
        <StackedFunnelChart
          bars={[
            { name: "Hipertensi CKG 2026", segments: [{ label: "", value: ht2026.hipertensi_2026, fill: COLORS.reg2025 }] },
            {
              name: "Kategori Pasien",
              segments: [
                { label: "Pasien Baru", value: ht2026.pasien_baru, fill: COLORS.currentMonth },
                { label: "Sudah Hipertensi", value: ht2026.sudah_hipertensi, fill: COLORS.bothYears },
              ],
            },
            {
              name: "Diobati",
              segments: [
                { label: "Pasien Baru - Diobati", value: ht2026.baru_diobati, fill: COLORS.baruDiobati },
                { label: "Pasien Baru - Tidak Diobati", value: ht2026.baru_tidak_diobati, fill: COLORS.baruTidakDiobati },
                { label: "Sudah Hipertensi - Diobati", value: ht2026.sudah_diobati, fill: COLORS.sudahDiobati },
                { label: "Sudah Hipertensi - Tidak Diobati", value: ht2026.sudah_tidak_diobati, fill: COLORS.sudahTidakDiobati },
              ],
            },
          ]}
        />
      </ChartCard>

      <ChartCard title="Cascade Hipertensi">
        <CascadeChart cascade={data.cascade} />
      </ChartCard>

      <ChartCard title="Proporsi Target Tercapai">
        <ProporsiChart proporsi={data.proporsi} currentMonthLabel={currentMonthLabel} />
      </ChartCard>

      <div className="lg:col-span-2">
        <ChartCard
          title="Pasien Hipertensi Tertatalaksana"
          titleColor={TEXT_COLORS.treated}
          // The gap between this card's two lines is a list of real patients —
          // this is the way in to it.
          action={<GapTatalaksanaLink puskesmasId={puskesmasId} />}
          description={
            last && (
              <ChartStat
                color={TEXT_COLORS.treated}
                percent={pct(last.treated_cumulative, last.registered_cumulative)}
                count={last.treated_cumulative}
                noun="pasien hipertensi tertatalaksana"
              />
            )
          }
        >
          <TertatalaksanaChart data={view} />
        </ChartCard>
      </div>

      <ChartCard
        title="Pasien Hipertensi Target Tercapai"
        titleColor={TEXT_COLORS.tercapai}
        description={
          last && (
            <ChartStat
              color={TEXT_COLORS.tercapai}
              percent={pct(last.tercapai, last.treated_cumulative)}
              count={last.tercapai}
              noun="pasien dengan tekanan darah <140/90"
            />
          )
        }
      >
        <MonthlyAreaChart data={view} metric="tercapai" color={COLORS.tercapai} label="Target Tercapai" />
      </ChartCard>

      <ChartCard
        title="Pasien Hipertensi Target Tidak Tercapai"
        titleColor={TEXT_COLORS.tidakTercapai}
        description={
          last && (
            <ChartStat
              color={TEXT_COLORS.tidakTercapai}
              percent={pct(last.tidak_tercapai, last.treated_cumulative)}
              count={last.tidak_tercapai}
              noun="pasien dengan tekanan darah ≥140/90"
            />
          )
        }
      >
        <MonthlyAreaChart data={view} metric="tidak_tercapai" color={COLORS.tidakTercapai} label="Target Tidak Tercapai" />
      </ChartCard>

      <ChartCard
        title="Pasien Hipertensi Tidak Berkunjung"
        titleColor={TEXT_COLORS.tidakBerkunjung}
        description={
          last && (
            <ChartStat
              color={TEXT_COLORS.tidakBerkunjung}
              percent={pct(last.tidak_berkunjung, last.treated_cumulative)}
              count={last.tidak_berkunjung}
              noun="pasien tidak berkunjung ulang"
            />
          )
        }
      >
        <MonthlyAreaChart data={view} metric="tidak_berkunjung" color={COLORS.tidakBerkunjung} label="Tidak Berkunjung" />
      </ChartCard>
    </div>
  );
}
