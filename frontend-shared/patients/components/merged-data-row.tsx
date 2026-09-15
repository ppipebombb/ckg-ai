"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  formatMergedValue,
  formatRawValue,
  getItemStatus,
  isEmptyValue,
  STATUS_LABEL,
  type MergedItem,
  type MergedItemStatus,
} from "@shared/patients/merged-patient";

const ROW_BG: Record<MergedItemStatus, string> = {
  match: "bg-green-100 hover:bg-green-200/70",
  same_answer: "bg-green-100 hover:bg-green-200/70",
  both_empty: "bg-[var(--card)] hover:bg-[var(--muted)]/40",
  one_source: "bg-yellow-100 hover:bg-yellow-200/70",
  conflict: "bg-red-100 hover:bg-red-200/70",
};

const STATUS_BADGE: Record<MergedItemStatus, string> = {
  match: "bg-green-100 text-green-800",
  same_answer: "bg-green-100 text-green-800",
  both_empty: "bg-gray-100 text-gray-600",
  one_source: "bg-yellow-100 text-yellow-800",
  conflict: "bg-red-100 text-red-800",
};

export function MergedDataRow({
  item,
  isLast,
}: {
  item: MergedItem;
  isLast: boolean;
}) {
  const [open, setOpen] = useState(false);
  const status = getItemStatus(item);
  const isSameMeaning = status === "same_answer";
  const value = formatMergedValue(item.merged_value);

  return (
    <div className={cn(!isLast && "border-b border-[var(--border)]/50")}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn("w-full text-left transition", ROW_BG[status])}
      >
        <div className="flex items-start gap-2 px-5 py-3 cursor-pointer select-none">
          <div className="flex-1 min-w-0 text-sm leading-snug">
            <div>
              <span className="text-[var(--muted-foreground)]">
                {item.merged_key}
              </span>
              <span className="text-[var(--muted-foreground)]/40 mx-1">:</span>
              {value === null ? (
                <em className="font-normal text-[var(--muted-foreground)] text-sm">
                  tidak ada data
                </em>
              ) : (
                <span className="text-[var(--foreground)] font-medium">
                  {value}
                </span>
              )}
            </div>
            {isSameMeaning && (
              <div className="mt-1 text-xs font-medium text-green-800">
                Jawaban berbeda, makna sama.
              </div>
            )}
          </div>
          <ChevronRight
            className={cn(
              "w-3.5 h-3.5 text-[var(--muted-foreground)] shrink-0 mt-1 transition-transform duration-150",
              open && "rotate-90",
            )}
          />
        </div>
      </button>

      {open && (
        <div className="px-5 pb-3 pt-1">
          <div className="rounded-lg border border-[var(--border)] overflow-hidden text-sm">
            <div className="grid grid-cols-2 divide-x divide-[var(--border)]">
              <div className="p-3 bg-blue-50">
                <div className="text-xs font-bold text-blue-700 uppercase tracking-wide mb-1">
                  ASIK
                </div>
                {item.asik_question && (
                  <div className="text-xs text-blue-500 mb-2 leading-snug break-words">
                    {item.asik_question}
                  </div>
                )}
                <div
                  className={cn(
                    "break-words",
                    isEmptyValue(item.asik_value)
                      ? "text-[var(--muted-foreground)] italic"
                      : "text-[var(--foreground)]",
                  )}
                >
                  {formatRawValue(item.asik_value)}
                </div>
              </div>
              <div className="p-3 bg-emerald-50">
                <div className="text-xs font-bold text-emerald-700 uppercase tracking-wide mb-1">
                  EPUS
                </div>
                {item.epus_question && (
                  <div className="text-xs text-emerald-600 mb-2 leading-snug break-words">
                    {item.epus_question}
                  </div>
                )}
                <div
                  className={cn(
                    "break-words",
                    isEmptyValue(item.epus_value)
                      ? "text-[var(--muted-foreground)] italic"
                      : "text-[var(--foreground)]",
                  )}
                >
                  {formatRawValue(item.epus_value)}
                </div>
              </div>
            </div>
            <div className="border-t border-[var(--border)] p-3 flex items-start gap-2 flex-wrap bg-[var(--card)]">
              <span
                className={cn(
                  "shrink-0 text-xs font-medium rounded px-2 py-0.5",
                  STATUS_BADGE[status],
                )}
              >
                {STATUS_LABEL[status]}
              </span>
              {isSameMeaning && (
                <span className="text-xs text-green-800">
                  ASIK dan ePus berisi jawaban berbeda, tetapi maknanya sama.
                </span>
              )}
              {item.reasoning && (
                <span className="text-xs text-[var(--muted-foreground)]">
                  {item.reasoning}
                </span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
