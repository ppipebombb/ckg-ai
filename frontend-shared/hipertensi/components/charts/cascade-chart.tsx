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

// Chart 1 — Cascade Hipertensi (current month). Bars: total registered →
// tertatalaksana (ever prescribed) → target tercapai (controlled this month).
// % is relative to Bar 1 (total registri hipertensi CKG); Bar 1 has no %.
export function CascadeChart({
  cascade,
}: {
  cascade: HipertensiCharts["cascade"];
}) {
  const base = cascade.registered;
  const data = [
    { name: "Pasien Hipertensi", value: cascade.registered, fill: COLORS.registered, label: `${cascade.registered}` },
    { name: "Tertatalaksana", value: cascade.treated, fill: COLORS.treated, label: `${cascade.treated} (${pct(cascade.treated, base)}%)` },
    { name: "Target Tercapai", value: cascade.controlled, fill: COLORS.controlled, label: `${cascade.controlled} (${pct(cascade.controlled, base)}%)` },
  ];
  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={data} margin={{ top: 24, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="name" tick={{ fontSize: 12 }} stroke="var(--muted-foreground)" />
        <YAxis tick={{ fontSize: 12 }} stroke="var(--muted-foreground)" allowDecimals={false} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(v) => [fmtCount(Number(v)), "Pasien"]}
        />
        <Bar dataKey="value" radius={[4, 4, 0, 0]}>
          {data.map((d) => (
            <Cell key={d.name} fill={d.fill} />
          ))}
          <LabelList
            dataKey="label"
            position="top"
            fontSize={12}
            fill="var(--foreground)"
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
