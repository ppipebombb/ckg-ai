"use client";

import { Fragment, useMemo, useState } from "react";
import { format, parseISO, subDays } from "date-fns";
import dynamic from "next/dynamic";
import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/page-header";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { Pagination } from "@/components/common/pagination";
import { ErrorState } from "@/components/common/error-state";
import { EmptyState } from "@/components/common/empty-state";
import { useLlmLogs, useLlmUsage, useRetryMergeBulk } from "@/lib/hooks/use-llm";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { RetryMergeButton } from "@/components/llm/retry-merge-button";
import { asApiError } from "@/lib/api/client";
import { useQueryClient } from "@tanstack/react-query";
import { llmLogKeys } from "@/lib/hooks/use-llm";
import { mergeKeys } from "@/lib/hooks/use-merge";

const UsageChart = dynamic(
  () => import("@/components/llm/usage-chart").then((m) => m.UsageChart),
  { ssr: false, loading: () => <Skeleton className="h-72 w-full" /> },
);

type StatusFilter =
  | "all"
  | "ok"
  | "fail"
  | "fail-retried-ok"
  | "fail-not-retried";

export default function LlmLogsPage() {
  const today = format(new Date(), "yyyy-MM-dd");
  const [groupBy, setGroupBy] = useState<"day" | "month">("day");
  const [since, setSince] = useState(format(subDays(new Date(), 30), "yyyy-MM-dd"));
  const [until, setUntil] = useState(today);
  const [page, setPage] = useState(1);
  const [puskesmasId, setPuskesmasId] = useState<string | undefined>(undefined);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [source, setSource] = useState<string>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const qc = useQueryClient();
  const retryBulk = useRetryMergeBulk();
  const selectedPuskesmas = usePuskesmas(puskesmasId);

  const usageQuery = useMemo(
    () => ({
      group_by: groupBy,
      since: `${since}T00:00:00`,
      until: `${until}T23:59:59`,
    }),
    [groupBy, since, until],
  );
  const usage = useLlmUsage(usageQuery);

  const logsQuery = useMemo(() => {
    // Map UI status → backend (success, retry_status). "fail-*" variants all
    // imply success=false; retry_status only set on the sub-options. Backend
    // additionally constrains those to merge_patient_data rows.
    const successParam =
      status === "all"
        ? undefined
        : status === "ok"
          ? true
          : false;
    const retryStatusParam =
      status === "fail-retried-ok"
        ? ("retried_ok" as const)
        : status === "fail-not-retried"
          ? ("not_retried" as const)
          : undefined;
    return {
      page,
      size: 20,
      since: `${since}T00:00:00`,
      puskesmas_id: puskesmasId,
      success: successParam,
      retry_status: retryStatusParam,
      source: source === "all" ? undefined : source,
    };
  }, [page, since, puskesmasId, status, source]);
  const logs = useLlmLogs(logsQuery);

  const toggleExpanded = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const isRetryable = (l: {
    source: string;
    success: boolean;
    patient_id?: string | null;
    superseded_by_success?: boolean;
  }) =>
    l.source === "merge_patient_data" &&
    !l.success &&
    !!l.patient_id &&
    !l.superseded_by_success;

  const eligibleIds = useMemo(
    () => (logs.data?.items ?? []).filter(isRetryable).map((l) => l.id),
    [logs.data],
  );

  const allEligibleSelected =
    eligibleIds.length > 0 && eligibleIds.every((id) => selectedIds.has(id));

  const toggleSelected = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleSelectAll = () =>
    setSelectedIds((prev) => {
      if (allEligibleSelected) {
        const next = new Set(prev);
        for (const id of eligibleIds) next.delete(id);
        return next;
      }
      const next = new Set(prev);
      for (const id of eligibleIds) next.add(id);
      return next;
    });

  const resetSelection = () => setSelectedIds(new Set());

  const handleBulkRetry = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    try {
      const res = await retryBulk.mutateAsync(ids);
      const parts = [`${res.triggered} job merge dipicu`];
      if (res.skipped > 0) parts.push(`${res.skipped} dilewati`);
      toast.success(parts.join(", "));
      if (res.triggered > 0) {
        qc.invalidateQueries({ queryKey: mergeKeys.all });
      }
      qc.invalidateQueries({ queryKey: llmLogKeys.all });
      resetSelection();
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const totals = useMemo(() => {
    if (!usage.data) return null;
    return usage.data.reduce(
      (acc, b) => ({
        calls: acc.calls + b.calls,
        tokens: acc.tokens + b.input_tokens + b.output_tokens,
        cost: acc.cost + Number(b.total_cost ?? 0),
      }),
      { calls: 0, tokens: 0, cost: 0 },
    );
  }, [usage.data]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Log LLM"
        description="Penggunaan token dan biaya di seluruh panggilan LLM."
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Penggunaan</CardTitle>
          <CardDescription>
            {totals
              ? `${totals.calls.toLocaleString()} panggilan • ${totals.tokens.toLocaleString()} token • $${totals.cost.toFixed(4)}`
              : "—"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label htmlFor="since">Dari</Label>
              <Input
                id="since"
                type="date"
                value={since}
                onChange={(e) => setSince(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="until">Sampai</Label>
              <Input
                id="until"
                type="date"
                value={until}
                onChange={(e) => setUntil(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label>Kelompokkan per</Label>
              <Select value={groupBy} onValueChange={(v) => setGroupBy(v as "day" | "month")}>
                <SelectTrigger className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="day">Hari</SelectItem>
                  <SelectItem value="month">Bulan</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          {usage.isLoading ? (
            <Skeleton className="h-72 w-full" />
          ) : usage.data && usage.data.length > 0 ? (
            <UsageChart data={usage.data} groupBy={groupBy} />
          ) : (
            <EmptyState title="Tidak ada penggunaan pada rentang terpilih" />
          )}
        </CardContent>
      </Card>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Panggilan terbaru</h2>
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <Label>Puskesmas</Label>
            <AsyncCombobox
              value={puskesmasId}
              onChange={(id) => {
                setPuskesmasId(id);
                setPage(1);
                resetSelection();
              }}
              useOptions={usePuskesmasOptions}
              selectedLabel={selectedPuskesmas.data?.name}
              allOptionLabel="Semua puskesmas"
              placeholder="Semua puskesmas"
              className="w-64"
            />
          </div>
          <div className="space-y-1">
            <Label>Status</Label>
            <Select
              value={status}
              onValueChange={(v) => {
                setStatus(v as StatusFilter);
                setPage(1);
                resetSelection();
              }}
            >
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua</SelectItem>
                <SelectItem value="ok">Berhasil</SelectItem>
                <SelectItem value="fail">Gagal (semua)</SelectItem>
                <SelectItem value="fail-retried-ok">
                  Gagal → berhasil di-ulang
                </SelectItem>
                <SelectItem value="fail-not-retried">
                  Gagal → belum di-ulang
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label>Sumber</Label>
            <Select
              value={source}
              onValueChange={(v) => {
                setSource(v);
                setPage(1);
                resetSelection();
              }}
            >
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua</SelectItem>
                <SelectItem value="merge_patient_data">merge_patient_data</SelectItem>
                <SelectItem value="asik_captcha">asik_captcha</SelectItem>
                <SelectItem value="asik_sync_captcha">asik_sync_captcha</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        {selectedIds.size > 0 && (
          <div className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-2">
            <div className="text-sm">
              <span className="font-semibold">{selectedIds.size}</span> log merge
              gagal dipilih
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={resetSelection}>
                Bersihkan
              </Button>
              <Button
                size="sm"
                onClick={handleBulkRetry}
                disabled={retryBulk.isPending}
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Ulang {selectedIds.size} terpilih
              </Button>
            </div>
          </div>
        )}
        {logs.error && <ErrorState error={logs.error} />}
        <div className="rounded-lg border border-[var(--border)]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8">
                  <input
                    type="checkbox"
                    aria-label="Pilih semua yang bisa di-ulang di halaman ini"
                    checked={allEligibleSelected}
                    disabled={eligibleIds.length === 0}
                    onChange={toggleSelectAll}
                    className="h-4 w-4 cursor-pointer accent-[var(--primary)] disabled:cursor-not-allowed disabled:opacity-40"
                  />
                </TableHead>
                <TableHead className="w-8"></TableHead>
                <TableHead>Waktu</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Sumber</TableHead>
                <TableHead>Token (in/out)</TableHead>
                <TableHead>Biaya</TableHead>
                <TableHead>Latensi</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {logs.data?.items.map((l) => {
                const hasError = !!l.error;
                const isOpen = expanded.has(l.id);
                const retryable = isRetryable(l);
                const isSelected = selectedIds.has(l.id);
                return (
                  <Fragment key={l.id}>
                    <TableRow
                      className={hasError ? "cursor-pointer" : undefined}
                      onClick={hasError ? () => toggleExpanded(l.id) : undefined}
                    >
                      <TableCell
                        className="w-8 align-top"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {retryable ? (
                          <input
                            type="checkbox"
                            aria-label="Pilih untuk ulang massal"
                            checked={isSelected}
                            onChange={() => toggleSelected(l.id)}
                            className="h-4 w-4 cursor-pointer accent-[var(--primary)]"
                          />
                        ) : null}
                      </TableCell>
                      <TableCell className="w-8 align-top">
                        {hasError ? (
                          isOpen ? (
                            <ChevronDown className="h-4 w-4 text-[var(--muted-foreground)]" />
                          ) : (
                            <ChevronRight className="h-4 w-4 text-[var(--muted-foreground)]" />
                          )
                        ) : null}
                      </TableCell>
                      <TableCell className="text-xs text-[var(--muted-foreground)]">
                        {format(parseISO(l.created_at), "yyyy-MM-dd HH:mm:ss")}
                      </TableCell>
                      <TableCell className="font-medium">{l.model}</TableCell>
                      <TableCell>{l.source}</TableCell>
                      <TableCell className="tabular-nums">
                        {(l.input_tokens ?? 0).toLocaleString()} /{" "}
                        {(l.output_tokens ?? 0).toLocaleString()}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {l.total_cost != null
                          ? `$${Number(l.total_cost).toFixed(4)}`
                          : "—"}
                      </TableCell>
                      <TableCell className="text-xs text-[var(--muted-foreground)]">
                        {l.latency_ms ? `${l.latency_ms}ms` : "—"}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1.5">
                          {l.success ? (
                            <Badge variant="success">ok</Badge>
                          ) : (
                            <Badge variant="destructive">gagal</Badge>
                          )}
                          {l.superseded_by_success && (
                            <Badge
                              variant="secondary"
                              title="Percobaan ulang berikutnya untuk pasien ini berhasil"
                            >
                              berhasil di-ulang
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                    {hasError && isOpen && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell></TableCell>
                        <TableCell></TableCell>
                        <TableCell colSpan={7} className="py-3">
                          <div className="rounded-lg border border-red-200 bg-red-50 p-3">
                            <div className="mb-2 flex items-center justify-between gap-3">
                              <div className="text-xs font-bold uppercase tracking-wide text-red-700">
                                Error
                              </div>
                              {l.source === "merge_patient_data" &&
                                l.patient_id &&
                                !l.superseded_by_success && (
                                  <RetryMergeButton patientId={l.patient_id} />
                                )}
                            </div>
                            <pre className="whitespace-pre-wrap break-words text-xs leading-snug text-red-700">
                              {l.error}
                            </pre>
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
          {logs.data && logs.data.items.length === 0 && (
            <div className="p-6">
              <EmptyState title="Tidak ada entri log" />
            </div>
          )}
        </div>
        {logs.data && logs.data.items.length > 0 && (
          <Pagination
            page={logs.data.page}
            pages={logs.data.pages}
            total={logs.data.total}
            onPageChange={(p) => {
              setPage(p);
              resetSelection();
            }}
          />
        )}
      </div>
    </div>
  );
}
