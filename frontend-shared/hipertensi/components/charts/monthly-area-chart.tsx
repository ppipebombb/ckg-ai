"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartsMonthPoint } from "@/lib/api/hipertensi-charts";
import { ChartPointLabel, POINT_LABEL_HEADROOM } from "./chart-point-label";
import { TOOLTIP_STYLE, fmtCount, fmtYm, pct } from "./theme";

type Metric = "tercapai" | "tidak_tercapai" | "tidak_berkunjung";

// Charts 3/4/5 — of the cumulative-treated cohort each month, the slice that is
// controlled / uncontrolled / did-not-visit. % is relative to that month's
// treated cohort ("the scope of the bar itself").
export function MonthlyAreaChart({
  data,
  metric,
  color,
  label,
}: {
  data: ChartsMonthPoint[];
  metric: Metric;
  color: string;
  label: string;
}) {
  const gradientId = `area-${metric}`;
  const chartData = data.map((d) => ({
    label: fmtYm(d.ym),
    value: d[metric],
    pct: pct(d[metric], d.treated_cumulative),
  }));
  // The area plots the share, so the bold label has to be fed the count.
  const counts = chartData.map((d) => d.value);
  const captions = chartData.map((d) => `${d.pct}%`);
  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart
        data={chartData}
        margin={{ top: POINT_LABEL_HEADROOM, right: 16, bottom: 0, left: 0 }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fontSize: 11 }}
          stroke="var(--muted-foreground)"
          interval={0}
          angle={-45}
          textAnchor="end"
          height={56}
          // Keep the first/last point's labels clear of the Y axis and the right edge.
          padding={{ left: 20, right: 10 }}
        />
        <YAxis
          tick={{ fontSize: 12 }}
          stroke="var(--muted-foreground)"
          domain={[0, 100]}
          ticks={[0, 25, 50, 75, 100]}
          tickFormatter={(v) => `${v}%`}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(v, _n, item) => {
            const abs = (item?.payload as { value?: number } | undefined)?.value ?? 0;
            return [`${fmtCount(abs)} (${Number(v)}% dari tertatalaksana)`, label];
          }}
        />
        <Area
          type="monotone"
          dataKey="pct"
          stroke={color}
          fill={`url(#${gradientId})`}
          strokeWidth={2}
          dot={{ r: 3, fill: color, strokeWidth: 0 }}
          label={<ChartPointLabel counts={counts} captions={captions} hideZero />}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
