"use client";

import { useMemo } from "react";
import { format, parseISO } from "date-fns";
import { Download, Loader2 } from "lucide-react";
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
import { GapTatalaksanaTable } from "@shared/hipertensi/components/gap-tatalaksana-table";
import { useHipertensiGapListStore } from "@shared/hipertensi/hipertensi-gap-list-store";
import {
  useExportHipertensiGap,
  useHipertensiGap,
} from "@shared/hipertensi/use-hipertensi";

const _NOW_YEAR = new Date().getFullYear();
const YEAR_OPTIONS = Array.from({ length: 6 }, (_, i) => _NOW_YEAR - i);
const ALL_YEARS = "all";

// Shared Gap Tatalaksana view — the drill-down behind the gap in the dashboard
// chart "Pasien Hipertensi Tertatalaksana": every registry member who has never
// been prescribed an antihypertensive, with the contact details a puskesmas
// needs to follow them up. Rendered identically by both apps; each app supplies
// only the page header wording.
export function GapTatalaksanaView({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  const puskesmasId = useHipertensiGapListStore((s) => s.puskesmasId);
  const year = useHipertensiGapListStore((s) => s.year);
  const q = useHipertensiGapListStore((s) => s.q);
  const page = useHipertensiGapListStore((s) => s.page);
  const setPuskesmasId = useHipertensiGapListStore((s) => s.setPuskesmasId);
  const setYear = useHipertensiGapListStore((s) => s.setYear);
  const setQ = useHipertensiGapListStore((s) => s.setQ);
  const setPage = useHipertensiGapListStore((s) => s.setPage);

  const pkDetail = usePuskesmas(puskesmasId || undefined);
  const debouncedQ = useDebouncedValue(q);

  const gapQuery = useMemo(
    () => ({
      puskesmas_id: puskesmasId,
      year,
      q: debouncedQ.trim() || undefined,
      page,
      size: 20,
    }),
    [puskesmasId, year, debouncedQ, page],
  );
  const gap = useHipertensiGap(gapQuery, !!puskesmasId);
  const exportGap = useExportHipertensiGap();

  const computing = !!gap.data?.computing;
  const loading =
    !!puskesmasId &&
    (gap.isLoading || computing || (gap.isFetching && !gap.isPlaceholderData));
  const refreshing = !!puskesmasId && !loading && gap.isFetching;

  const yearLabel = year ? String(year) : "Semua Tahun";

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
            <Label>Tahun Masuk Registri</Label>
            <Select
              value={year ? String(year) : ALL_YEARS}
              onValueChange={(v) => setYear(v === ALL_YEARS ? undefined : Number(v))}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_YEARS}>Semua tahun</SelectItem>
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
            description="Daftar gap tatalaksana dihitung per puskesmas."
          />
        )}
        {gap.error && <ErrorState error={gap.error} />}

        {puskesmasId && gap.data && !computing && gap.data.computed_at && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
            <span>
              <span className="font-medium text-[var(--foreground)]">
                {gap.data.total.toLocaleString()}
              </span>{" "}
              pasien hipertensi belum tertatalaksana
            </span>
            <span className="inline-flex items-center gap-2">
              <span>
                Computed {format(parseISO(gap.data.computed_at!), "yyyy-MM-dd HH:mm")}
                {gap.data.cache_hit ? " · cached" : " · fresh"}
                {refreshing && (
                  <span className="ml-2 inline-flex items-center gap-1">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    refreshing…
                  </span>
                )}
              </span>
              <Button
                size="sm"
                variant="outline"
                className="h-6 gap-1 px-2 text-xs"
                onClick={() =>
                  exportGap.mutate(
                    {
                      puskesmasId,
                      year,
                      // The file must match what is on screen, so the export
                      // carries the same (debounced) search the table used.
                      q: debouncedQ.trim() || undefined,
                      filename: `Gap Tatalaksana Hipertensi - ${pkDetail.data?.name ?? "Puskesmas"} - ${yearLabel}.xlsx`,
                    },
                    { onError: (err) => toast.error(asApiError(err).message) },
                  )
                }
                disabled={loading || gap.data.total === 0 || exportGap.isPending}
              >
                {exportGap.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Download className="h-3 w-3" />
                )}
                Export Gap Tatalaksana
              </Button>
            </span>
          </div>
        )}

        {loading && (
          <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-[var(--border)] py-16 text-sm text-[var(--muted-foreground)]">
            <Loader2 className="h-6 w-6 animate-spin" />
            <div className="text-center">
              <div className="font-medium text-[var(--foreground)]">
                Loading gap tatalaksana…
              </div>
              <div className="text-xs">
                First-time computation decrypts EPUS + ASIK records for this
                puskesmas. Result is cached for 30 hours.
              </div>
            </div>
            {gap.data?.progress && (
              <WarmProgress
                progress={gap.data.progress}
                label={null}
                className="max-w-xs"
              />
            )}
          </div>
        )}

        {puskesmasId && !loading && gap.data && (
          <>
            <GapTatalaksanaTable items={gap.data.items} />
            <Pagination
              page={gap.data.page}
              pages={gap.data.pages}
              total={gap.data.total}
              onPageChange={setPage}
            />
          </>
        )}
      </section>
    </div>
  );
}
