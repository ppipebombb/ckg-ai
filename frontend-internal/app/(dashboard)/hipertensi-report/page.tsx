"use client";

import { useMemo, useState } from "react";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Pagination } from "@/components/common/pagination";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { Button } from "@/components/ui/button";
import { HipertensiDiagnoseTable } from "@/components/hipertensi/hipertensi-diagnose-table";
import { HipertensiRegistryView } from "@shared/hipertensi/components/hipertensi-registry-view";
import { useHipertensiReportListStore } from "@shared/hipertensi/hipertensi-report-list-store";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import {
  useExportHipertensiDiagnose,
  useHipertensiDashboard,
} from "@/lib/hooks/use-hipertensi";

const _NOW_YEAR = new Date().getFullYear();
const YEAR_OPTIONS = Array.from({ length: 6 }, (_, i) => _NOW_YEAR - i);

// Internal-only Full Review Diagnose tab. Shares the registry filter store so the
// puskesmas/year/search picked on either tab stay in sync; reuses the legacy
// per-day dashboard aggregate.
function HipertensiDiagnoseView() {
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

  const diagnoseQuery = useMemo(
    () => ({
      puskesmas_id: puskesmasId,
      year,
      q: debouncedQ.trim() || undefined,
      page,
      size: 20,
    }),
    [puskesmasId, year, debouncedQ, page],
  );
  const diagnose = useHipertensiDashboard(diagnoseQuery, !!puskesmasId);
  const exportDiagnose = useExportHipertensiDiagnose();

  return (
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
      {diagnose.error && <ErrorState error={diagnose.error} />}

      {puskesmasId && diagnose.data && diagnose.data.computed_at && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
          <span>
            <span className="font-medium text-[var(--foreground)]">
              {diagnose.data.total.toLocaleString()}
            </span>{" "}
            pasien hipertensi (CKG)
          </span>
          <span className="inline-flex items-center gap-2">
            <span>
              Computed{" "}
              {format(parseISO(diagnose.data.computed_at!), "yyyy-MM-dd HH:mm")}
              {diagnose.data.cache_hit ? " · cached" : " · fresh"}
            </span>
            <Button
              size="sm"
              variant="outline"
              className="h-6 gap-1 px-2 text-xs"
              onClick={() =>
                exportDiagnose.mutate(
                  {
                    puskesmasId,
                    year,
                    filename: `Full Review Diagnosa Hipertensi - ${pkDetail.data?.name ?? "Puskesmas"} - ${year}.xlsx`,
                  },
                  { onError: (err) => toast.error(asApiError(err).message) },
                )
              }
              disabled={exportDiagnose.isPending}
            >
              {exportDiagnose.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Download className="h-3 w-3" />
              )}
              Export Full Review Diagnose
            </Button>
          </span>
        </div>
      )}

      {puskesmasId && diagnose.isLoading ? (
        <div className="flex items-center justify-center gap-2 py-12 text-sm text-[var(--muted-foreground)]">
          <Loader2 className="h-5 w-5 animate-spin" /> Loading…
        </div>
      ) : diagnose.data ? (
        <>
          <HipertensiDiagnoseTable items={diagnose.data.items} />
          <Pagination
            page={diagnose.data.page}
            pages={diagnose.data.pages}
            total={diagnose.data.total}
            onPageChange={setPage}
          />
        </>
      ) : null}
    </section>
  );
}

export default function HipertensiReportPage() {
  // Tab state is internal-only (the dashboard has no Diagnose tab). No detail
  // route navigates away from this page, so plain useState is enough.
  const [tab, setTab] = useState<"registri" | "diagnose">("registri");

  return (
    <Tabs value={tab} onValueChange={(v) => setTab(v as "registri" | "diagnose")}>
      <TabsList>
        <TabsTrigger value="registri">Registri Hipertensi</TabsTrigger>
        <TabsTrigger value="diagnose">Full Review Diagnose</TabsTrigger>
      </TabsList>
      <TabsContent value="registri">
        <HipertensiRegistryView
          title="Kertas Kerja Hipertensi"
          description="Registri Hipertensi (V8juni2026): identitas, hasil pemeriksaan TD pada tanggal berkunjung CKG, dan follow-up tekanan darah per bulan."
          showClearCache
          exportLabel="Export Registri Hipertensi"
          exportFilenamePrefix="Registri Hipertensi"
        />
      </TabsContent>
      <TabsContent value="diagnose">
        <HipertensiDiagnoseView />
      </TabsContent>
    </Tabs>
  );
}
