"use client";

import dynamic from "next/dynamic";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { DmCharts } from "@/lib/api/dm-charts";
// The StackedFunnelChart + theme are generic (category x split bars), not
// hipertensi-specific — reused here from where they currently live rather than
// duplicated. Both apps render this DM grid identically, so it lives in
// frontend-shared like the hipertensi one.
import { COLORS } from "../../hipertensi/components/charts/theme";

const ChartFallback = () => (
  <div className="h-[300px] w-full animate-pulse rounded-md bg-[var(--muted)]" />
);
const StackedFunnelChart = dynamic(
  () =>
    import("../../hipertensi/components/charts/stacked-funnel-chart").then(
      (m) => m.StackedFunnelChart,
    ),
  { ssr: false, loading: ChartFallback },
);

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function DmChartsGrid({ data }: { data: DmCharts }) {
  const kohort = data.kohort_2tahun;
  const dm2026 = data.dm_2026;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <ChartCard title="Diabetes Melitus 2 Tahun Berturut-turut">
        <StackedFunnelChart
          bars={[
            { name: "DM CKG 2025", segments: [{ label: "", value: kohort.dm_2025, fill: COLORS.reg2025 }] },
            { name: "Diperiksa CKG 2026", segments: [{ label: "", value: kohort.diperiksa_2026, fill: COLORS.bothYears }] },
            {
              name: "DM 2026",
              segments: [
                { label: "Ya (≥ambang)", value: kohort.dm_2026_tinggi, fill: COLORS.tidakTercapai },
                { label: "Tidak (<ambang)", value: kohort.dm_2026_terkendali, fill: COLORS.tercapai },
              ],
            },
            {
              name: "Diobati",
              segments: [
                { label: "Ya (≥ambang) - Diobati", value: kohort.tinggi_diobati, fill: COLORS.tinggiDiobati },
                { label: "Ya (≥ambang) - Tidak Diobati", value: kohort.tinggi_tidak_diobati, fill: COLORS.tinggiTidakDiobati },
                { label: "Tidak (<ambang) - Diobati", value: kohort.terkendali_diobati, fill: COLORS.terkendaliDiobati },
                { label: "Tidak (<ambang) - Tidak Diobati", value: kohort.terkendali_tidak_diobati, fill: COLORS.terkendaliTidakDiobati },
              ],
            },
          ]}
        />
      </ChartCard>

      <ChartCard title="Diabetes Melitus CKG 2026">
        <StackedFunnelChart
          bars={[
            { name: "DM CKG 2026", segments: [{ label: "", value: dm2026.dm_2026, fill: COLORS.reg2025 }] },
            {
              name: "Kategori Pasien",
              segments: [
                { label: "Pasien Baru", value: dm2026.pasien_baru, fill: COLORS.currentMonth },
                { label: "Sudah DM", value: dm2026.sudah_dm, fill: COLORS.bothYears },
              ],
            },
            {
              name: "Diobati",
              segments: [
                { label: "Pasien Baru - Diobati", value: dm2026.baru_diobati, fill: COLORS.baruDiobati },
                { label: "Pasien Baru - Tidak Diobati", value: dm2026.baru_tidak_diobati, fill: COLORS.baruTidakDiobati },
                { label: "Sudah DM - Diobati", value: dm2026.sudah_diobati, fill: COLORS.sudahDiobati },
                { label: "Sudah DM - Tidak Diobati", value: dm2026.sudah_tidak_diobati, fill: COLORS.sudahTidakDiobati },
              ],
            },
          ]}
        />
      </ChartCard>
    </div>
  );
}
