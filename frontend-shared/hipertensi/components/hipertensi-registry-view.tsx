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
import { HipertensiRegistryTable } from "@shared/hipertensi/components/hipertensi-registry-table";
import { HipertensiFormulaCard } from "@shared/hipertensi/components/hipertensi-formula-card";
import { useHipertensiReportListStore } from "@shared/hipertensi/hipertensi-report-list-store";
import {
  useClearHipertensiRegistryCache,
  useExportHipertensiRegistry,
  useHipertensiRegistry,
} from "@shared/hipertensi/use-hipertensi";

const _NOW_YEAR = new Date().getFullYear();
const YEAR_OPTIONS = Array.from({ length: 6 }, (_, i) => _NOW_YEAR - i);

// Shared presentational registry view: filters + formula card + table +
// pagination + registry export. App-specific differences are passed in:
// `title`/`description` for the page header, `showClearCache` to gate the
// clear-cache control (internal=true, dashboard=false), and `exportLabel`/
// `exportFilenamePrefix` for the export button text + downloaded filename.
export function HipertensiRegistryView({
  title,
  description,
  showClearCache,
  exportLabel,
  exportFilenamePrefix,
}: {
  title: string;
  description: string;
  showClearCache: boolean;
  exportLabel: string;
  exportFilenamePrefix: string;
}) {
  const puskesmasId = useHipertensiReportListStore((s) => s.puskesmasId);
  const year = useHipertensiReportListStore((s) => s.year);
  const q = useHipertensiReportListStore((s) => s.q);
  const page = useHipertensiReportListStore((s) => s.page);
  const setPuskesmasId = useHipertensiReportListStore((s) => s.setPuskesmasId);
  const setYear = useHipertensiReportListStore((s) => s.setYear);
  const setQ = useHipertensiReportListStore((s) => s.setQ);
  const setPage = useHipertensiReportListStore((s) => s.setPage);

  const pkDetail = usePuskesmas(puskesmasId || undefined);
  const debouncedQ = useDebouncedValue(q);

  const registryQuery = useMemo(
    () => ({
      puskesmas_id: puskesmasId,
      year,
      q: debouncedQ.trim() || undefined,
      page,
      size: 20,
    }),
    [puskesmasId, year, debouncedQ, page],
  );
  const registry = useHipertensiRegistry(registryQuery, !!puskesmasId);
  const clearCache = useClearHipertensiRegistryCache();
  const exportRegistry = useExportHipertensiRegistry();

  const computing = !!registry.data?.computing;
  const loading =
    !!puskesmasId &&
    (registry.isLoading ||
      computing ||
      (registry.isFetching && !registry.isPlaceholderData));
  const refreshing =
    !!puskesmasId &&
    !loading &&
    (registry.isFetching || clearCache.isPending);

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

        {puskesmasId &&
          registry.data &&
          !computing &&
          registry.data.computed_at && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
              <span>
                <span className="font-medium text-[var(--foreground)]">
                  {registry.data.total.toLocaleString()}
                </span>{" "}
                pasien (CKG) ·{" "}
                {registry.data.total_hipertensi.toLocaleString()} hipertensi ·{" "}
                {registry.data.total_pre_hipertensi.toLocaleString()} pre-hipertensi
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
                Loading registri hipertensi…
              </div>
              <div className="text-xs">
                First-time computation decrypts EPUS + ASIK records for this
                puskesmas + year. Result is cached for 30 hours.
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
              <HipertensiFormulaCard />
            </div>
            <HipertensiRegistryTable items={registry.data.items} />
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
