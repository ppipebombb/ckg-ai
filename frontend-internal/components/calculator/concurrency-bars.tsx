"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  type TooltipValueType,
} from "recharts";

interface Props {
  data: { label: string; value: number }[];
  color: string;
  unit: string;
}

function formatTooltipValue(value: TooltipValueType | undefined) {
  if (Array.isArray(value)) {
    return value.join(" - ");
  }

  return value ?? 0;
}

export default function ConcurrencyBars({ data, color, unit }: Props) {
  return (
    <ResponsiveContainer width="100%" height={192}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
        <XAxis dataKey="label" tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} width={36} />
        <Tooltip
          formatter={(value: TooltipValueType | undefined) => [
            `${formatTooltipValue(value)} ${unit}`,
            "dibutuhkan",
          ]}
          contentStyle={{ fontSize: 12 }}
        />
        <Bar dataKey="value" fill={color} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
