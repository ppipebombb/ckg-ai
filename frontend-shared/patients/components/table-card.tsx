"use client";

import { Card, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { PatientTable } from "@shared/patients/raw-patient";

export function TableCard({ table }: { table: PatientTable }) {
  return (
    <Card className="shadow-sm overflow-hidden p-0 gap-0">
      <CardHeader className="py-3 px-5 bg-[var(--muted)]/50 border-b border-[var(--border)]">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <h3 className="font-semibold text-[var(--foreground)] text-sm">
            {table.tabLabel} &gt; {table.tableLabel}
          </h3>
          <span className="text-xs font-medium rounded px-2 py-0.5 bg-blue-100 text-blue-800">
            {table.rows.length} baris
          </span>
        </div>
      </CardHeader>
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[var(--muted)]/30">
              {table.headers.map((h) => (
                <th
                  key={h}
                  className="text-left px-4 py-2 text-xs font-semibold text-[var(--muted-foreground)] border-b border-[var(--border)] whitespace-nowrap"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, idx) => (
              <tr
                key={idx}
                className="border-b border-[var(--border)] last:border-0"
              >
                {table.headers.map((h) => {
                  const v = row[h];
                  const isEmpty = v === null || v === "";
                  return (
                    <td
                      key={h}
                      className={cn(
                        "px-4 py-2 align-top",
                        isEmpty
                          ? "text-[var(--muted-foreground)] italic"
                          : "text-[var(--foreground)]",
                      )}
                    >
                      {isEmpty ? "—" : v}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
