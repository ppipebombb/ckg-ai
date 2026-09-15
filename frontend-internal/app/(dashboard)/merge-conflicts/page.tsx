"use client";

import { Fragment, useMemo, useState } from "react";
import { format, parseISO } from "date-fns";
import { ChevronDown, ChevronRight, Loader2, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/common/page-header";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import {
  useClearMergeConflictCache,
  useMergeConflictSummary,
} from "@/lib/hooks/use-merge-conflicts";
import { Button } from "@/components/ui/button";

const TOP_OPTIONS = [10, 20, 50] as const;

export default function MergeConflictsPage() {
  const [puskesmasId, setPuskesmasId] = useState<string | undefined>(undefined);
  const [top, setTop] = useState<number>(50);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const pkDetail = usePuskesmas(puskesmasId);

  const query = useMemo(
    () => ({ puskesmas_id: puskesmasId, top }),
    [puskesmasId, top],
  );
  const summary = useMergeConflictSummary(query);
  const data = summary.data;
  const clearCache = useClearMergeConflictCache();
  // computing = backend is recomputing in the background (cold cache / refresh);
  // treat it as loading so we never render the empty placeholder payload.
  const computing = !!data?.computing;
  const summaryLoading =
    summary.isLoading ||
    computing ||
    (summary.isFetching && !summary.isPlaceholderData);
  const summaryRefreshing =
    !summaryLoading && (summary.isFetching || clearCache.isPending);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Conflict Analysis"
        description="Questions where the merged data shows a real disagreement between ePuskesmas and ASIK answers."
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label>Puskesmas</Label>
          <AsyncCombobox
            value={puskesmasId}
            onChange={(v) => setPuskesmasId(v)}
            useOptions={usePuskesmasOptions}
            selectedLabel={pkDetail.data?.name}
            placeholder="Select a puskesmas…"
            allOptionLabel="All puskesmas"
          />
        </div>
        <div className="space-y-2">
          <Label>Top</Label>
          <Select
            value={String(top)}
            onValueChange={(v) => setTop(Number(v))}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TOP_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)}>
                  Top {n}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {data && !computing && data.computed_at && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
          <span>
            <span className="font-medium text-[var(--foreground)]">
              {data.total_patients.toLocaleString()}
            </span>{" "}
            matched patients (last 12 months)
          </span>
          <span className="inline-flex items-center gap-2">
            <span>
              Computed{" "}
              {format(parseISO(data.computed_at!), "yyyy-MM-dd HH:mm")}
              {data.cache_hit ? " · cached" : " · fresh"}
              {summaryRefreshing && (
                <span className="ml-2 inline-flex items-center gap-1">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  refreshing…
                </span>
              )}
            </span>
            {data.cache_hit && (
              <Button
                size="sm"
                variant="outline"
                className="h-6 gap-1 px-2 text-xs"
                onClick={() => clearCache.mutate(puskesmasId)}
                disabled={clearCache.isPending}
              >
                <RefreshCw
                  className={`h-3 w-3 ${clearCache.isPending ? "animate-spin" : ""}`}
                />
                Clear cache
              </Button>
            )}
          </span>
        </div>
      )}

      {summary.error && <ErrorState error={summary.error} />}

      {summaryLoading && (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-[var(--border)] py-16 text-sm text-[var(--muted-foreground)]">
          <Loader2 className="h-6 w-6 animate-spin" />
          <div className="text-center">
            <div className="font-medium text-[var(--foreground)]">
              Loading conflict analysis…
            </div>
            <div className="text-xs">
              First-time computation scans every matched patient&apos;s merged
              data for the selected scope. Result is cached for 24 hours.
            </div>
          </div>
        </div>
      )}

      {!summaryLoading && data && (
        <div className="rounded-lg border border-[var(--border)]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8"></TableHead>
                <TableHead>Section</TableHead>
                <TableHead>Merged Key</TableHead>
                <TableHead className="text-right">Affected Patients</TableHead>
                <TableHead className="text-right">%</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.conflicts.map((c) => {
                const id = `${c.section}::${c.merged_key}`;
                const isOpen = expanded.has(id);
                return (
                  <Fragment key={id}>
                    <TableRow
                      className="cursor-pointer"
                      onClick={() => toggle(id)}
                    >
                      <TableCell className="w-8 align-top">
                        {isOpen ? (
                          <ChevronDown className="h-4 w-4 text-[var(--muted-foreground)]" />
                        ) : (
                          <ChevronRight className="h-4 w-4 text-[var(--muted-foreground)]" />
                        )}
                      </TableCell>
                      <TableCell className="align-top font-medium">
                        {c.section_label}
                      </TableCell>
                      <TableCell className="align-top">{c.merged_key}</TableCell>
                      <TableCell className="text-right align-top tabular-nums">
                        {c.conflict_count.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right align-top tabular-nums">
                        {c.conflict_pct.toFixed(2)}%
                      </TableCell>
                    </TableRow>
                    {isOpen && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell></TableCell>
                        <TableCell colSpan={4} className="py-3">
                          <div className="overflow-hidden rounded-lg border border-[var(--border)] text-sm">
                            <div className="grid grid-cols-2 divide-x divide-[var(--border)]">
                              <div className="bg-blue-50 p-3">
                                <div className="mb-1 text-xs font-bold uppercase tracking-wide text-blue-700">
                                  ASIK
                                </div>
                                <div className="break-words text-xs leading-snug text-blue-500">
                                  {c.asik_question ?? "—"}
                                </div>
                              </div>
                              <div className="bg-emerald-50 p-3">
                                <div className="mb-1 text-xs font-bold uppercase tracking-wide text-emerald-700">
                                  EPUS
                                </div>
                                <div className="break-words text-xs leading-snug text-emerald-600">
                                  {c.epus_question ?? "—"}
                                </div>
                              </div>
                            </div>
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
          {data.conflicts.length === 0 && (
            <div className="p-6">
              <EmptyState
                title="No conflicts found"
                description={
                  data.total_patients === 0
                    ? "No matched patients with merged data in the selected scope."
                    : "All matched patients agree on every question for this scope."
                }
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
