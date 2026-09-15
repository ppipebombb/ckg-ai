"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { HipertensiCharts } from "@/lib/api/hipertensi-charts";
import { COLORS, TOOLTIP_STYLE, fmtCount, pct } from "./theme";

// Chart 6 — Proporsi Pasien Hipertensi CKG 2025 dengan TD terkendali di CKG 2026.
// Bars: registri 2025 → juga di registri 2026 → terkendali saat CKG 2026 →
// terkendali bulan berjalan. % relative to Bar 1 (registri 2025).
export function ProporsiChart({
  proporsi,
  currentMonthLabel,
}: {
  proporsi: HipertensiCharts["proporsi"];
  currentMonthLabel: string;
}) {
  const base = proporsi.registry_2025;
  const data = [
    { name: "Hipertensi CKG 2025", value: proporsi.registry_2025, fill: COLORS.reg2025, label: `${proporsi.registry_2025}` },
    { name: "Diperiksa CKG 2026", value: proporsi.both_years, fill: COLORS.bothYears, label: `${proporsi.both_years} (${pct(proporsi.both_years, base)}%)` },
    { name: "Terkendali CKG 2026", value: proporsi.controlled_baseline_2026, fill: COLORS.baseline2026, label: `${proporsi.controlled_baseline_2026} (${pct(proporsi.controlled_baseline_2026, base)}%)` },
    { name: `Terkendali ${currentMonthLabel}`, value: proporsi.controlled_current_month, fill: COLORS.currentMonth, label: `${proporsi.controlled_current_month} (${pct(proporsi.controlled_current_month, base)}%)` },
  ];
  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={data} margin={{ top: 24, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="name" tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" interval={0} />
        <YAxis tick={{ fontSize: 12 }} stroke="var(--muted-foreground)" allowDecimals={false} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(v) => [fmtCount(Number(v)), "Pasien"]}
        />
        <Bar dataKey="value" radius={[4, 4, 0, 0]}>
          {data.map((d) => (
            <Cell key={d.name} fill={d.fill} />
          ))}
          <LabelList dataKey="label" position="top" fontSize={12} fill="var(--foreground)" />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
