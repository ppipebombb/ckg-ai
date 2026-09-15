"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ArrowRight, FileQuestion } from "lucide-react";
import { PageHeader } from "@/components/common/page-header";
import { StatCard } from "@/components/common/stat-card";
import { Pagination } from "@/components/common/pagination";
import { ErrorState } from "@/components/common/error-state";
import { EmptyState } from "@/components/common/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import {
  useMappingForms,
  useMappingOverview,
} from "@/lib/hooks/use-mapping";
import { useMappingListStore } from "@/lib/stores/mapping-list-store";

export default function MappingReferencePage() {
  const page = useMappingListStore((s) => s.page);
  const q = useMappingListStore((s) => s.q);
  const coverage = useMappingListStore((s) => s.coverage);
  const hasAudit = useMappingListStore((s) => s.hasAudit);
  const setPage = useMappingListStore((s) => s.setPage);
  const setQ = useMappingListStore((s) => s.setQ);
  const setCoverage = useMappingListStore((s) => s.setCoverage);
  const setHasAudit = useMappingListStore((s) => s.setHasAudit);
  const reset = useMappingListStore((s) => s.reset);

  const debounced = useDebouncedValue(q);
  const overview = useMappingOverview();

  const params = useMemo(
    () => ({
      page,
      size: 20,
      q: debounced.trim() || undefined,
      coverage: (coverage || undefined) as
        | "covered"
        | "partial"
        | "none"
        | undefined,
      has_audit:
        hasAudit === "yes" ? true : hasAudit === "no" ? false : undefined,
    }),
    [page, debounced, coverage, hasAudit],
  );

  const list = useMappingForms(params);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Referensi Pemetaan"
        description="Metadata pertanyaan EPUS / ASIK. Cari form atau kode field mana pun, telusuri untuk debug pemetaan per-pertanyaan."
      />

      {/* Overview cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          title="Total form"
          value={overview.data?.form_count}
          loading={overview.isLoading}
        />
        <StatCard
          title="Pertanyaan"
          value={overview.data?.question_count}
          subtext={
            overview.data
              ? `${overview.data.covered_question_count} tercakup converter`
              : undefined
          }
          loading={overview.isLoading}
        />
        <StatCard
          title="Form terverifikasi audit"
          value={overview.data?.audit_form_count}
          subtext="Live SurveyJS dump 2026-04-29"
          loading={overview.isLoading}
        />
        <StatCard
          title="Jalur sumber EPUS"
          value={overview.data?.epus_path_count}
          subtext="Bisa dipetakan balik"
          loading={overview.isLoading}
        />
      </div>

      {/* Filters */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Filter</CardTitle>
          <CardDescription>
            Cari berdasarkan nama paket, kode FRM, modul, atau layanan. Filter
            tetap tersimpan saat menelusuri halaman detail.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 md:grid-cols-12">
            <div className="md:col-span-6 space-y-1">
              <Label htmlFor="q">Cari</Label>
              <Input
                id="q"
                placeholder="mis. Sistolik, Tekanan Darah, FRM000180, PPM00000203, PTM > Periksa Fisik…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
              <p className="text-[11px] text-[var(--muted-foreground)]">
                Cocok dengan nama paket, kode FRM, modul, layanan, plus
                label pertanyaan, kode PPV/PPM, pilihan, jalur EPUS, dan
                opsi ASIK live.
              </p>
            </div>
            <div className="md:col-span-3 space-y-1">
              <Label>Cakupan converter</Label>
              <Select
                value={coverage || "all"}
                onValueChange={(v) =>
                  setCoverage(
                    v === "all"
                      ? ""
                      : (v as "covered" | "partial" | "none"),
                  )
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Semua</SelectItem>
                  <SelectItem value="covered">Tercakup penuh</SelectItem>
                  <SelectItem value="partial">Tercakup sebagian</SelectItem>
                  <SelectItem value="none">Tidak tercakup</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="md:col-span-3 space-y-1">
              <Label>Audit live</Label>
              <Select
                value={hasAudit || "all"}
                onValueChange={(v) =>
                  setHasAudit(v === "all" ? "" : (v as "yes" | "no"))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Semua</SelectItem>
                  <SelectItem value="yes">Ada di audit</SelectItem>
                  <SelectItem value="no">Padanan-saja</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={reset}
              className="text-xs text-[var(--muted-foreground)] underline-offset-2 hover:underline"
            >
              Reset filter
            </button>
          </div>
        </CardContent>
      </Card>

      {/* List */}
      {list.error && <ErrorState error={list.error} />}
      {list.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : list.data && list.data.items.length === 0 ? (
        <EmptyState
          title="Tidak ada form yang cocok"
          description="Coba hapus filter atau perluas pencarian."
        />
      ) : (
        <div className="grid gap-3">
          {list.data?.items.map((f) => {
            const total = f.question_count;
            const covered = f.covered_question_count;
            const ratio =
              total > 0 ? Math.round((covered / total) * 100) : 0;
            const fullyCovered = total > 0 && covered === total;
            const noCoverage = covered === 0;
            return (
              <Link
                key={`${f.frm_code}-${f.paket_name}`}
                href={`/mapping-reference/${encodeURIComponent(f.frm_code ?? f.paket_name)}`}
                prefetch={false}
                className="group rounded-lg border border-[var(--border)] bg-[var(--card)] p-4 transition-colors hover:border-[var(--primary)]/40 hover:bg-[var(--accent)]/30"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-medium leading-tight">
                        {f.paket_name}
                      </h3>
                      {f.frm_code && (
                        <code className="rounded bg-[var(--muted)] px-1.5 py-0.5 text-xs font-mono text-[var(--muted-foreground)]">
                          {f.frm_code}
                        </code>
                      )}
                    </div>
                    {(f.modul || f.layanan_name) && (
                      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                        {[f.modul, f.layanan_name]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    )}
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <Badge
                        variant={
                          fullyCovered
                            ? "success"
                            : noCoverage
                              ? "outline"
                              : "secondary"
                        }
                      >
                        {covered}/{total} tercakup ({ratio}%)
                      </Badge>
                      {f.in_audit ? (
                        <Badge variant="outline">Audit</Badge>
                      ) : (
                        <Badge variant="outline" className="opacity-60">
                          Tanpa audit
                        </Badge>
                      )}
                      {f.in_converter_breadcrumbs && (
                        <Badge variant="outline">Converter</Badge>
                      )}
                      {f.demos_union.length > 0 && (
                        <Badge variant="outline">
                          {f.demos_union.length} klaster
                        </Badge>
                      )}
                      {f.matched_questions.length > 0 && (
                        <Badge variant="secondary">
                          {f.matched_questions.length} pertanyaan cocok
                        </Badge>
                      )}
                    </div>
                    {f.matched_questions.length > 0 && (
                      <div className="mt-2 space-y-0.5 border-l-2 border-[var(--border)] pl-2.5 text-xs text-[var(--muted-foreground)]">
                        {f.matched_questions.slice(0, 3).map((label, i) => (
                          <p key={i} className="truncate">
                            <span className="text-[var(--muted-foreground)]/70">
                              ↳
                            </span>{" "}
                            {label}
                          </p>
                        ))}
                        {f.matched_questions.length > 3 && (
                          <p className="text-[var(--muted-foreground)]/70">
                            +{f.matched_questions.length - 3} lainnya
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                  <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-[var(--muted-foreground)] transition-transform group-hover:translate-x-1" />
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {list.data && list.data.items.length > 0 && (
        <Pagination
          page={list.data.page}
          pages={list.data.pages}
          total={list.data.total}
          onPageChange={setPage}
        />
      )}
    </div>
  );
}
