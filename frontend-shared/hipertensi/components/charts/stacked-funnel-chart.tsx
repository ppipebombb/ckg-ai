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
import { TOOLTIP_STYLE, fmtCount } from "./theme";

export interface FunnelSegment {
  label: string;
  value: number;
  fill: string;
}

export interface FunnelBar {
  name: string;
  /** 1 segment = a plain bar; 2 segments = a stacked/split bar (e.g. Ya/Tidak). */
  segments: FunnelSegment[];
}

type FunnelRow = { name: string; total: number } & Record<string, unknown>;

function toRows(bars: FunnelBar[], maxSegments: number): FunnelRow[] {
  return bars.map((b) => {
    const total = b.segments.reduce((s, seg) => s + seg.value, 0);
    // Only single-segment (standalone-count) bars carry a number above them —
    // CKG 2025 / CKG 2026 / Diperiksa CKG 2026. A split bar (Ya/Tidak, Kategori,
    // Diobati) leaves this null so the dataKey-based LabelList draws nothing for
    // it; its total just repeats an earlier bar and its breakdown is in the
    // tooltip. (dataKey-based, NOT an index-driven custom renderer: with
    // zero-height stacked segments recharts' label index does not map to the
    // category, which put the number on the wrong bar.)
    const displayTotal = b.segments.length === 1 ? total : null;
    const row: FunnelRow = { name: b.name, total, displayTotal };
    for (let i = 0; i < maxSegments; i++) {
      const seg = b.segments[i];
      row[`v${i}`] = seg ? seg.value : 0;
      row[`fill${i}`] = seg ? seg.fill : "transparent";
      row[`label${i}`] = seg ? seg.label : "";
    }
    return row;
  });
}

function FunnelTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { dataKey?: string; value?: number; payload?: FunnelRow }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const total = payload[0]?.payload?.total ?? 0;
  const segs = payload.filter((p) => Number(p.value) > 0);
  return (
    <div style={{ ...TOOLTIP_STYLE, padding: "6px 10px" }}>
      <div style={{ fontWeight: 600, color: "var(--foreground)" }}>{label}</div>
      {segs.length > 1 ? (
        segs.map((p) => {
          const idx = String(p.dataKey).replace("v", "");
          const segLabel = (p.payload?.[`label${idx}`] as string) || "Pasien";
          // Colour the row with the segment's own fill so the tooltip legend
          // maps 1:1 to the bar's colours (the in-bar labels were removed).
          const color = (p.payload?.[`fill${idx}`] as string) || "var(--foreground)";
          return (
            <div key={p.dataKey} style={{ display: "flex", justifyContent: "space-between", gap: 12, color, fontWeight: 600 }}>
              <span>{segLabel}</span>
              <span>{fmtCount(Number(p.value))}</span>
            </div>
          );
        })
      ) : (
        <div style={{ color: "var(--muted-foreground)" }}>{fmtCount(total)} Pasien</div>
      )}
    </div>
  );
}

// Generic stacked "funnel" chart: each x-axis category is one step; a step
// MAY be split into colored segments (e.g. Ya/Tidak) stacked inside its bar.
// Segment colours are per-CATEGORY, not per-series, so fills come from
// per-row <Cell>, not a single <Bar fill>.
export function StackedFunnelChart({ bars }: { bars: FunnelBar[] }) {
  const maxSegments = Math.max(1, ...bars.map((b) => b.segments.length));
  const rows = toRows(bars, maxSegments);

  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={rows} margin={{ top: 24, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="name" tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" interval={0} />
        <YAxis tick={{ fontSize: 12 }} stroke="var(--muted-foreground)" allowDecimals={false} />
        <Tooltip content={<FunnelTooltip />} />
        {Array.from({ length: maxSegments }, (_, i) => (
          <Bar key={i} dataKey={`v${i}`} stackId="stack" radius={i === maxSegments - 1 ? [4, 4, 0, 0] : undefined}>
            {rows.map((row, ri) => (
              <Cell key={ri} fill={row[`fill${i}`] as string} />
            ))}
            {/* Total sits above the first segment; for single-segment bars that
                IS the whole bar, and for split bars displayTotal is null → no
                label. */}
            {i === 0 && (
              <LabelList
                dataKey="displayTotal"
                position="top"
                offset={8}
                fill="var(--foreground)"
                fontSize={12}
                fontWeight={700}
                formatter={(value) => (value == null ? "" : fmtCount(Number(value)))}
              />
            )}
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
