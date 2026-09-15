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
import { format, parseISO } from "date-fns";
import type { LlmUsageBucketT } from "@/lib/api/types";

export function UsageChart({
  data,
  groupBy,
}: {
  data: LlmUsageBucketT[];
  groupBy: "day" | "month";
}) {
  const fmt = (s: string) =>
    format(parseISO(s), groupBy === "day" ? "MMM d" : "MMM yyyy");

  const chartData = data.map((d) => ({
    bucket: d.bucket,
    label: fmt(d.bucket),
    cost: Number(d.total_cost ?? 0),
    tokens: (d.input_tokens ?? 0) + (d.output_tokens ?? 0),
  }));

  return (
    <ResponsiveContainer width="100%" height={288}>
      <AreaChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="cost" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="oklch(0.205 0 0)" stopOpacity={0.3} />
              <stop offset="100%" stopColor="oklch(0.205 0 0)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="label" tick={{ fontSize: 12 }} stroke="var(--muted-foreground)" />
          <YAxis tick={{ fontSize: 12 }} stroke="var(--muted-foreground)" />
          <Tooltip
            contentStyle={{
              background: "var(--popover)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(v, name) => {
              const num = Number(v);
              return name === "cost"
                ? [`$${num.toFixed(4)}`, "Biaya"]
                : [num.toLocaleString(), "Token"];
            }}
          />
          <Area
            type="monotone"
            dataKey="cost"
            stroke="oklch(0.205 0 0)"
            fill="url(#cost)"
            strokeWidth={2}
          />
        </AreaChart>
    </ResponsiveContainer>
  );
}
