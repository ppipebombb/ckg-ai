"use client";

import { useMemo } from "react";
import { format, parseISO } from "date-fns";
import { Download, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { asApiError } from "@/lib/api/client";
import { PageHeader } from "@/components/common/page-header";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Pagination } from "@/components/common/pagination";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { WarmProgress } from "@/components/common/warm-progress";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { Button } from "@/components/ui/button";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import { BayiRegistryTable } from "@shared/bayi/components/bayi-registry-table";
import { BayiFormulaCard } from "@shared/bayi/components/bayi-formula-card";
import { useBayiReportListStore } from "@shared/bayi/bayi-report-list-store";
import {
  useBayiRegistry,
  useClearBayiRegistryCache,
  useExportBayiRegistry,
} from "@shared/bayi/use-bayi";
import type { BayiSheet } from "@shared/bayi/types";

const _NOW_YEAR = new Date().getFullYear();
const YEAR_OPTIONS = Array.from({ length: 6 }, (_, i) => _NOW_YEAR - i);

// Shared presentational registry view for both Bayi Kuning sheets. `sheet`
// selects the band (Ikterus vs Ikterus Berat); the Ikterus sheet also shows the
// Pemantauan columns. App-specific differences (title, description,
// showClearCache, export label/filename) are passed in.
export function BayiRegistryView({
  sheet,
  title,
  description,
  showClearCache,
  exportLabel,
  exportFilenamePrefix,
}: {
  sheet: BayiSheet;
  title: string;
  description: string;
  showClearCache: boolean;
  exportLabel: string;
  exportFilenamePrefix: string;
}) {
  const puskesmasId = useBayiReportListStore((s) => s.puskesmasId);
  const year = useBayiReportListStore((s) => s.year);
  const q = useBayiReportListStore((s) => s.q);
  const page = useBayiReportListStore((s) => s.page);
  const setPuskesmasId = useBayiReportListStore((s) => s.setPuskesmasId);
  const setYear = useBayiReportListStore((s) => s.setYear);
  const setQ = useBayiReportListStore((s) => s.setQ);
  const setPage = useBayiReportListStore((s) => s.setPage);

  const pkDetail = usePuskesmas(puskesmasId || undefined);
  const debouncedQ = useDebouncedValue(q);

  const registryQuery = useMemo(
    () => ({
      puskesmas_id: puskesmasId,
      year,
      sheet,
      q: debouncedQ.trim() || undefined,
      page,
      size: 20,
    }),
    [puskesmasId, year, sheet, debouncedQ, page],
  );
  const registry = useBayiRegistry(registryQuery, !!puskesmasId);
  const clearCache = useClearBayiRegistryCache();
  const exportRegistry = useExportBayiRegistry();

  const computing = !!registry.data?.computing;
  const loading =
    !!puskesmasId &&
    (registry.isLoading ||
      computing ||
      (registry.isFetching && !registry.isPlaceholderData));
  const refreshing =
    !!puskesmasId && !loading && (registry.isFetching || clearCache.isPending);

  const isBerat = sheet === "ikterus_berat";

  return (
    <div className="space-y-8">
      <PageHeader title={title} description={description} />

      <section className="space-y-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="space-y-2">
            <Label>Puskesmas</Label>
            <AsyncCombobox
              value={puskesmasId || undefined}
              onChange={(v) => setPuskesmasId(v ?? "")}
              useOptions={usePuskesmasOptions}
              selectedLabel={pkDetail.data?.name}
              placeholder="Select a puskesmas…"
            />
          </div>
          <div className="space-y-2">
            <Label>Tahun Pelaporan</Label>
            <Select value={String(year)} onValueChange={(v) => setYear(Number(v))}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {YEAR_OPTIONS.map((y) => (
                  <SelectItem key={y} value={String(y)}>
                    {y}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Search Nama / NIK</Label>
            <Input
              placeholder="Search…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
        </div>

        {!puskesmasId && (
          <EmptyState
            title="Pick a puskesmas"
            description="The registry groups one puskesmas at a time."
          />
        )}
        {registry.error && <ErrorState error={registry.error} />}

        {puskesmasId && registry.data && !computing && registry.data.computed_at && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
            <span>
              <span className="font-medium text-[var(--foreground)]">
                {registry.data.total.toLocaleString()}
              </span>{" "}
              {isBerat ? "bayi ikterus berat" : "bayi kuning"}
              {!isBerat && (
                <>
                  {" "}
                  · di antaranya Ikterus berat{" "}
                  {registry.data.ikterus_berat.toLocaleString()}
                </>
              )}
            </span>
            <span className="inline-flex items-center gap-2">
              <span>
                Computed{" "}
                {format(parseISO(registry.data.computed_at!), "yyyy-MM-dd HH:mm")}
                {registry.data.cache_hit ? " · cached" : " · fresh"}
                {refreshing && (
                  <span className="ml-2 inline-flex items-center gap-1">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    refreshing…
                  </span>
                )}
              </span>
              {showClearCache && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-6 gap-1 px-2 text-xs"
                  onClick={() => clearCache.mutate({ puskesmasId, year })}
                  disabled={clearCache.isPending}
                >
                  <RefreshCw
                    className={`h-3 w-3 ${clearCache.isPending ? "animate-spin" : ""}`}
                  />
                  Clear cache
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                className="h-6 gap-1 px-2 text-xs"
                onClick={() =>
                  exportRegistry.mutate(
                    {
                      puskesmasId,
                      year,
                      sheet,
                      filename: `${exportFilenamePrefix} - ${pkDetail.data?.name ?? "Puskesmas"} - ${year}.xlsx`,
                    },
                    { onError: (err) => toast.error(asApiError(err).message) },
                  )
                }
                disabled={
                  loading || registry.data.total === 0 || exportRegistry.isPending
                }
              >
                {exportRegistry.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Download className="h-3 w-3" />
                )}
                {exportLabel}
              </Button>
            </span>
          </div>
        )}

        {loading && (
          <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-[var(--border)] py-16 text-sm text-[var(--muted-foreground)]">
            <Loader2 className="h-6 w-6 animate-spin" />
            <div className="text-center">
              <div className="font-medium text-[var(--foreground)]">
                Loading registri bayi kuning…
              </div>
              <div className="text-xs">
                First-time computation decrypts EPUS records for this puskesmas +
                year. Result is cached for 30 hours.
              </div>
            </div>
            {registry.data?.progress && (
              <WarmProgress
                progress={registry.data.progress}
                label={null}
                className="max-w-xs"
              />
            )}
          </div>
        )}

        {puskesmasId && !loading && registry.data && (
          <>
            <div className="mb-4">
              <BayiFormulaCard />
            </div>
            <BayiRegistryTable
              items={registry.data.items}
              showPemantauan={!isBerat}
            />
            <Pagination
              page={registry.data.page}
              pages={registry.data.pages}
              total={registry.data.total}
              onPageChange={setPage}
            />
          </>
        )}
      </section>
    </div>
  );
}
