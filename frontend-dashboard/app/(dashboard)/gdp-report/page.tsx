"use client";

import { useMemo } from "react";
import { format, parseISO } from "date-fns";
import { Check, Download, Loader2, RefreshCw } from "lucide-react";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Pagination } from "@/components/common/pagination";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { WarmProgress } from "@/components/common/warm-progress";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { GdpDiagnoseTable } from "@/components/gdp/gdp-diagnose-table";
import { MONTHS_ID, fmtGdp, gdpClass } from "@/lib/gdp-format";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useGdpReportListStore } from "@/lib/stores/gdp-report-list-store";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import {
  useClearGdpDashboardCache,
  useExportGdpDashboard,
  useExportGdpDiagnose,
  useGdpDashboard,
} from "@/lib/hooks/use-gdp";
import type { GdpReportRow } from "@/lib/api/types";

const _NOW_YEAR = new Date().getFullYear();
const YEAR_OPTIONS = Array.from({ length: 6 }, (_, i) => _NOW_YEAR - i);

const TERKENDALI_LABELS = [
  ["Terkendali Bulan Berjalan", "terkendali_bulan_berjalan"],
  ["Terkendali TW 1", "terkendali_tw1"],
  ["Terkendali TW 2", "terkendali_tw2"],
  ["Terkendali TW 3", "terkendali_tw3"],
  ["Terkendali TW 4", "terkendali_tw4"],
] as const;

function terkendaliClass(v: string) {
  switch (v) {
    case "Terkendali":
      return "bg-green-200 text-green-900";
    case "Tidak terkendali":
      return "bg-red-200 text-red-900";
    case "Belum 3 bulan":
      return "bg-yellow-100 text-yellow-900";
    case "Tidak ada kunjungan":
      return "bg-gray-100 text-gray-700";
    default:
      return "";
  }
}

function TertCheckbox({ checked }: { checked: boolean }) {
  return (
    <span
      role="img"
      aria-label={checked ? "Ya" : "Tidak"}
      className={`mx-auto flex h-5 w-5 items-center justify-center rounded-[5px] ${
        checked
          ? "bg-black text-white"
          : "border-2 border-[var(--foreground)] bg-transparent"
      }`}
    >
      {checked && <Check className="h-3 w-3" strokeWidth={3} />}
    </span>
  );
}

// Production build: clear-cache control hidden. Flip to true to re-enable.
const SHOW_CLEAR_CACHE = false;

export default function GdpReportPage() {
  const puskesmasId = useGdpReportListStore((s) => s.puskesmasId);
  const year = useGdpReportListStore((s) => s.year);
  const q = useGdpReportListStore((s) => s.q);
  const ckgOnly = useGdpReportListStore((s) => s.ckgOnly);
  const page = useGdpReportListStore((s) => s.page);
  const tab = useGdpReportListStore((s) => s.tab);
  const setPuskesmasId = useGdpReportListStore((s) => s.setPuskesmasId);
  const setYear = useGdpReportListStore((s) => s.setYear);
  const setQ = useGdpReportListStore((s) => s.setQ);
  const setCkgOnly = useGdpReportListStore((s) => s.setCkgOnly);
  const setPage = useGdpReportListStore((s) => s.setPage);
  const setTab = useGdpReportListStore((s) => s.setTab);

  const pkDetail = usePuskesmas(puskesmasId || undefined);
  const debouncedQ = useDebouncedValue(q);

  const dashboardQuery = useMemo(
    () => ({
      puskesmas_id: puskesmasId,
      year,
      q: debouncedQ.trim() || undefined,
      ckg_only: ckgOnly || undefined,
      page,
      size: 20,
    }),
    [puskesmasId, year, debouncedQ, ckgOnly, page],
  );
  const dashboard = useGdpDashboard(dashboardQuery, !!puskesmasId);
  const clearDashboardCache = useClearGdpDashboardCache();
  const exportDashboard = useExportGdpDashboard();
  const exportDiagnose = useExportGdpDiagnose();
  // computing = backend recomputing in the background (cold cache / refresh);
  // treat as loading so we never render the empty placeholder payload.
  const dashboardComputing = !!dashboard.data?.computing;
  const dashboardLoading =
    !!puskesmasId &&
    (dashboard.isLoading ||
      dashboardComputing ||
      (dashboard.isFetching && !dashboard.isPlaceholderData));
  const dashboardRefreshing =
    !!puskesmasId &&
    !dashboardLoading &&
    (dashboard.isFetching || clearDashboardCache.isPending);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Kertas Kerja DM Terkendali"
        description="ASIK NIKs cross-checked against EPUS over a date range. Monthly GDP per patient."
      />

      <section className="space-y-4">
        <h2 className="text-sm font-semibold text-[var(--muted-foreground)]">
          Dashboard
        </h2>
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
            <Select
              value={String(year)}
              onValueChange={(v) => setYear(Number(v))}
            >
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
        <label className="flex w-fit cursor-pointer items-center gap-2 text-sm">
          <Switch checked={ckgOnly} onCheckedChange={setCkgOnly} />
          <span>Hanya yang di Tandai CKG</span>
        </label>
        {!puskesmasId && (
          <EmptyState
            title="Pick a puskesmas"
            description="The dashboard groups one puskesmas at a time."
          />
        )}
        {dashboard.error && <ErrorState error={dashboard.error} />}
        {puskesmasId && dashboard.data && !dashboardComputing && dashboard.data.computed_at && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
            <span>
              <span className="font-medium text-[var(--foreground)]">
                {dashboard.data.total.toLocaleString()}
              </span>{" "}
              pasien dengan data GDP
            </span>
            <span className="inline-flex items-center gap-2">
              <span>
                Computed{" "}
                {format(parseISO(dashboard.data.computed_at!), "yyyy-MM-dd HH:mm")}
                {dashboard.data.cache_hit ? " · cached" : " · fresh"}
                {dashboardRefreshing && (
                  <span className="ml-2 inline-flex items-center gap-1">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    refreshing…
                  </span>
                )}
              </span>
              {SHOW_CLEAR_CACHE && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-6 gap-1 px-2 text-xs"
                  onClick={() =>
                    clearDashboardCache.mutate({ puskesmasId, year })
                  }
                  disabled={clearDashboardCache.isPending}
                >
                  <RefreshCw
                    className={`h-3 w-3 ${clearDashboardCache.isPending ? "animate-spin" : ""}`}
                  />
                  Clear cache
                </Button>
              )}
              {tab === "report" ? (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-6 gap-1 px-2 text-xs"
                  onClick={() =>
                    exportDashboard.mutate(
                      {
                        puskesmasId,
                        year,
                        ckgOnly,
                        filename: `GD Puasa - ${pkDetail.data?.name ?? "Puskesmas"} - ${year}.xlsx`,
                      },
                      {
                        onError: (err) =>
                          toast.error(asApiError(err).message),
                      },
                    )
                  }
                  disabled={
                    dashboardLoading ||
                    dashboardRefreshing ||
                    dashboard.data.total === 0 ||
                    exportDashboard.isPending
                  }
                >
                  {exportDashboard.isPending ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Download className="h-3 w-3" />
                  )}
                  Export Kertas Kerja DM Terkendali
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-6 gap-1 px-2 text-xs"
                  onClick={() =>
                    exportDiagnose.mutate(
                      {
                        puskesmasId,
                        year,
                        ckgOnly,
                        filename: `Full Review Diagnosa - ${pkDetail.data?.name ?? "Puskesmas"} - ${year}.xlsx`,
                      },
                      {
                        onError: (err) =>
                          toast.error(asApiError(err).message),
                      },
                    )
                  }
                  disabled={
                    dashboardLoading ||
                    dashboardRefreshing ||
                    dashboard.data.total === 0 ||
                    exportDiagnose.isPending
                  }
                >
                  {exportDiagnose.isPending ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Download className="h-3 w-3" />
                  )}
                  Export Full Review Diagnose
                </Button>
              )}
            </span>
          </div>
        )}
        {dashboardLoading && (
          <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-[var(--border)] py-16 text-sm text-[var(--muted-foreground)]">
            <Loader2 className="h-6 w-6 animate-spin" />
            <div className="text-center">
              <div className="font-medium text-[var(--foreground)]">
                Loading GDP dashboard…
              </div>
              <div className="text-xs">
                First-time computation decrypts every EPUS record for this
                puskesmas + year. Result is cached for 30 hours.
              </div>
            </div>
            {dashboard.data?.progress && (
              <WarmProgress
                progress={dashboard.data.progress}
                label={null}
                className="max-w-xs"
              />
            )}
          </div>
        )}
        {puskesmasId && !dashboardLoading && dashboard.data && (
          <Tabs
            value={tab}
            onValueChange={(v) => setTab(v as "report" | "diagnose")}
          >
            <TabsList>
              <TabsTrigger value="report">
                Kertas Kerja DM Terkendali
              </TabsTrigger>
              <TabsTrigger value="diagnose">Full Review Diagnose</TabsTrigger>
            </TabsList>
            <TabsContent value="report">
              <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
                <Table className="min-w-[2250px]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[200px]">Nama Puskesmas</TableHead>
                    <TableHead className="w-[80px]">Tahun Pelaporan</TableHead>
                    <TableHead className="w-[160px]">Nama Pasien</TableHead>
                    <TableHead className="w-[160px]">NIK</TableHead>
                    <TableHead className="w-[120px]">Tanggal Diagnosis</TableHead>
                    <TableHead className="w-[160px] text-center text-xs">
                      Tertatalaksana (Pemberian Obat)
                    </TableHead>
                    <TableHead className="w-[160px] text-center text-xs">
                      Tertatalaksana (Pemberian Edukasi)
                    </TableHead>
                    {MONTHS_ID.map((m) => (
                      <TableHead
                        key={m}
                        className="w-[110px] text-center text-xs"
                      >
                        Hasil GD {m}
                      </TableHead>
                    ))}
                    {TERKENDALI_LABELS.map(([label]) => (
                      <TableHead
                        key={label}
                        className="w-[150px] text-center text-xs"
                      >
                        {label}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dashboard.data.items.map((row: GdpReportRow) => (
                    <TableRow key={row.nik}>
                      <TableCell className="text-xs">
                        {row.puskesmas_name}
                      </TableCell>
                      <TableCell className="tabular-nums text-xs">
                        {row.tahun_pelaporan}
                      </TableCell>
                      <TableCell>{row.nama || "—"}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {row.nik}
                      </TableCell>
                      <TableCell className="text-xs">
                        {row.tanggal_diagnosis
                          ? format(
                              parseISO(row.tanggal_diagnosis),
                              "dd/MM/yyyy",
                            )
                          : "—"}
                      </TableCell>
                      <TableCell className="text-center">
                        <TertCheckbox checked={row.tertatalaksana_obat} />
                      </TableCell>
                      <TableCell className="text-center">
                        <TertCheckbox checked={row.tertatalaksana_edukasi} />
                      </TableCell>
                      {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
                        const v = row.gdp_by_month?.[String(m)] ?? null;
                        return (
                          <TableCell
                            key={m}
                            className={`text-center tabular-nums text-sm ${gdpClass(v)}`}
                          >
                            {fmtGdp(v)}
                          </TableCell>
                        );
                      })}
                      {TERKENDALI_LABELS.map(([label, key]) => {
                        const v = row[key];
                        return (
                          <TableCell
                            key={label}
                            className={`text-center text-xs ${terkendaliClass(v)}`}
                          >
                            {v || "—"}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
                {dashboard.data.items.length === 0 && (
                  <div className="p-6">
                    <EmptyState
                      title="No patients with GDP"
                      description="No patient in this puskesmas+year has any GDP reading."
                    />
                  </div>
                )}
              </div>
            </TabsContent>
            <TabsContent value="diagnose">
              <GdpDiagnoseTable items={dashboard.data.items} />
            </TabsContent>
            <Pagination
              page={dashboard.data.page}
              pages={dashboard.data.pages}
              total={dashboard.data.total}
              onPageChange={setPage}
            />
          </Tabs>
        )}
      </section>
    </div>
  );
}
