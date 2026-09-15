"use client";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export type FieldRow = {
  label: string;
  value: string | null;
};

export type FormBlock = {
  name: string;
  filled: number;
  total: number;
  rows: FieldRow[];
};

export function formatValue(v: unknown): string | null {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "boolean") return v ? "Ya" : "Tidak";
  if (typeof v === "number") return String(v);
  if (typeof v === "string") return v.trim() || null;
  return JSON.stringify(v);
}

export function FormCard({
  block,
  emptyHint,
}: {
  block: FormBlock;
  emptyHint?: string;
}) {
  const empty = block.rows.length === 0;
  return (
    <Card className="shadow-sm overflow-hidden p-0 gap-0">
      <CardHeader className="py-3 px-5 bg-[var(--muted)]/50 border-b border-[var(--border)]">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <h3 className="font-semibold text-[var(--foreground)] text-sm">
            {block.name}
          </h3>
          <span
            className={cn(
              "text-xs font-medium rounded px-2 py-0.5",
              block.filled === 0
                ? "bg-[var(--muted)] text-[var(--muted-foreground)]"
                : block.filled === block.total
                  ? "bg-green-100 text-green-800"
                  : "bg-yellow-100 text-yellow-800",
            )}
          >
            {empty ? "Tidak ada field" : `${block.filled} / ${block.total} terisi`}
          </span>
        </div>
      </CardHeader>
      {empty ? (
        <CardContent className="py-4 text-xs text-[var(--muted-foreground)]">
          {emptyHint ?? "Tidak ada data."}
        </CardContent>
      ) : (
        <div className="divide-y divide-[var(--border)]">
          {block.rows.map((row, idx) => (
            <div
              key={`${row.label}-${idx}`}
              className="grid gap-4 px-5 py-2.5 items-start"
              // 2fr/1fr set inline (not the grid-cols-[2fr_1fr] arbitrary
              // utility) so the label|value 2-column layout is guaranteed even
              // if Tailwind ever fails to emit that one arbitrary class.
              style={{ gridTemplateColumns: "2fr 1fr" }}
            >
              <span className="text-xs text-[var(--muted-foreground)]">
                {row.label}
              </span>
              <span
                className={cn(
                  "text-sm",
                  row.value === null
                    ? "text-[var(--muted-foreground)] italic"
                    : "font-medium text-[var(--foreground)]",
                )}
              >
                {row.value ?? "—"}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

const STAT_TONE: Record<"green" | "amber" | "blue", string> = {
  green: "bg-green-100 text-green-800",
  amber: "bg-amber-100 text-amber-800",
  blue: "bg-blue-100 text-blue-800",
};

export function StatPill({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: number;
  hint?: string;
  tone: "green" | "amber" | "blue";
}) {
  return (
    <div
      className={cn(
        "min-w-[72px] rounded-md px-3 py-1.5 text-center",
        STAT_TONE[tone],
      )}
    >
      <div className="text-base font-bold leading-tight">
        {value}
        {hint && (
          <span className="text-[11px] font-medium ml-0.5 opacity-70">
            {hint}
          </span>
        )}
      </div>
      <div className="text-[10px] uppercase tracking-wide font-medium leading-tight">
        {label}
      </div>
    </div>
  );
}
