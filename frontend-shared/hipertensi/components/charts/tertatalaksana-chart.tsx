"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartsMonthPoint } from "@/lib/api/hipertensi-charts";
import { ChartPointLabel, POINT_LABEL_HEADROOM } from "./chart-point-label";
import { COLORS, TOOLTIP_STYLE, fmtCount, fmtYm, pct } from "./theme";

// Chart 2 — Pasien Hipertensi Tertatalaksana (rolling 12-month time series).
// Line 1: cumulative registered. Line 2: cumulative treated (ever prescribed).
// Both plot ABSOLUTE cumulative counts, so neither line can fall. Treated is
// always <= registered, so its labels go below the point and registered's
// above: the two lines converge as coverage approaches 100% and same-side
// labels would overprint. The treated/registered share survives as the muted
// caption under each treated label and in the tooltip.
export function TertatalaksanaChart({ data }: { data: ChartsMonthPoint[] }) {
  const chartData = data.map((d) => {
    const registered = d.registered_cumulative;
    // Months before the puskesmas' first registration are not drawn at all:
    // null, so both lines start where the registry does rather than tracking
    // along zero and stepping up with no explanation.
    const hasRegistry = registered > 0;
    return {
      label: fmtYm(d.ym),
      registered: hasRegistry ? registered : null,
      treated: hasRegistry ? d.treated_cumulative : null,
      treatedPct: hasRegistry ? pct(d.treated_cumulative, registered) : null,
    };
  });
  // Each line plots its own count, so ChartPointLabel labels the plotted value
  // and only the treated caption has to be supplied.
  const treatedCaptions = chartData.map((d) => (d.treatedPct === null ? "" : `${d.treatedPct}%`));
  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart
        data={chartData}
        margin={{ top: POINT_LABEL_HEADROOM, right: 16, bottom: 0, left: 0 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        {/* Ticks are pushed clear of the axis line so a below-label on a
            near-zero treated point lands in the gap, not on the month text.
            The extra height covers the tick gap plus the rotated month text. */}
        <XAxis
          dataKey="label"
          tick={{ fontSize: 11 }}
          stroke="var(--muted-foreground)"
          interval={0}
          angle={-45}
          textAnchor="end"
          tickMargin={26}
          height={76}
          // Keep the first/last point's labels clear of the Y axis and the right edge.
          padding={{ left: 20, right: 10 }}
        />
        {/* Absolute counts. `width` is set explicitly because id-ID grouping
            ("28.900") overflows recharts' default 60px tick gutter. */}
        <YAxis
          tick={{ fontSize: 12 }}
          stroke="var(--muted-foreground)"
          allowDecimals={false}
          tickFormatter={fmtCount}
          width={68}
        />
        {/* Each Line carries its own `name`, so the legend text and the legend
            icon's accessible name agree. Branch on dataKey, never on `name`. */}
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(v, _n, item) => {
            if (item?.dataKey === "registered") {
              return [fmtCount(Number(v)), "Terdaftar (kumulatif)"];
            }
            const p = item?.payload as { treatedPct?: number | null } | undefined;
            return [
              `${fmtCount(Number(v))} (${p?.treatedPct ?? 0}% dari terdaftar)`,
              "Tertatalaksana (kumulatif)",
            ];
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line
          type="monotone"
          dataKey="registered"
          name="Pasien Hipertensi Kumulatif"
          stroke={COLORS.registered}
          strokeWidth={2}
          dot={{ r: 3 }}
          label={<ChartPointLabel hideZero />}
        />
        <Line
          type="monotone"
          dataKey="treated"
          name="Pasien Tertatalaksana"
          stroke={COLORS.treated}
          strokeWidth={2}
          dot={{ r: 3 }}
          label={<ChartPointLabel captions={treatedCaptions} hideZero below />}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
