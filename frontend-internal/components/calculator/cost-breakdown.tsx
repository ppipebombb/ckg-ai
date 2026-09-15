"use client";

import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
  type TooltipValueType,
} from "recharts";

interface Props {
  scrape: number;
  merge: number;
}

const COLORS = ["#6366f1", "#f59e0b"];

function toFiniteNumber(value: TooltipValueType | undefined) {
  const rawValue = Array.isArray(value) ? value[0] : value;
  const numericValue = typeof rawValue === "number" ? rawValue : Number(rawValue);

  return Number.isFinite(numericValue) ? numericValue : 0;
}

export default function CostBreakdown({ scrape, merge }: Props) {
  const data = [
    { name: "Scrape (CAPTCHA)", value: Math.round(scrape * 10000) / 10000 },
    { name: "Merge (LLM)", value: Math.round(merge * 10000) / 10000 },
  ].filter((d) => d.value > 0);

  if (data.length === 0) {
    return (
      <div className="flex h-52 items-center justify-center text-sm text-[var(--muted-foreground)]">
        Belum ada data biaya LLM.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={208}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          cx="50%"
          cy="45%"
          outerRadius={70}
          label={({ name, percent }) => {
            const pct = typeof percent === "number" ? percent : 0;

            return `${name ?? ""} ${(pct * 100).toFixed(0)}%`;
          }}
          labelLine={false}
        >
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          formatter={(value: TooltipValueType | undefined) => [
            `$${toFiniteNumber(value).toFixed(4)}`,
            "bulanan",
          ]}
          contentStyle={{ fontSize: 12 }}
        />
        <Legend iconSize={10} wrapperStyle={{ fontSize: 12 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}
