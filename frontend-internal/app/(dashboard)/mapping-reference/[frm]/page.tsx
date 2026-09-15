"use client";

import Link from "next/link";
import { useState, use } from "react";
import { ArrowLeft, ChevronDown, ChevronRight, Search } from "lucide-react";
import { PageHeader } from "@/components/common/page-header";
import { ErrorState } from "@/components/common/error-state";
import { EmptyState } from "@/components/common/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useMappingForm } from "@/lib/hooks/use-mapping";
import { cn } from "@/lib/utils";
import type { MappingQuestion } from "@/lib/api/types";

export default function MappingFormDetailPage({
  params,
}: {
  params: Promise<{ frm: string }>;
}) {
  const { frm } = use(params);
  const decoded = decodeURIComponent(frm);
  const detail = useMappingForm(decoded);
  const [filter, setFilter] = useState("");

  const questions = detail.data?.questions ?? [];
  const filtered = filter.trim()
    ? questions.filter((q) => {
        const needle = filter.trim().toLowerCase();
        return (
          q.label.toLowerCase().includes(needle) ||
          q.parameter_codes.some((c) => c.toLowerCase().includes(needle)) ||
          q.choices.some((c) =>
            String(c.line ?? "")
              .toLowerCase()
              .includes(needle),
          ) ||
          q.live_options.some((o) => o.toLowerCase().includes(needle)) ||
          (q.epus_source ?? "").toLowerCase().includes(needle)
        );
      })
    : questions;

  return (
    <div className="space-y-6">
      <Link
        href="/mapping-reference"
        prefetch={false}
        className="inline-flex items-center gap-1 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Kembali ke daftar pemetaan
      </Link>

      {detail.error && <ErrorState error={detail.error} />}

      {detail.isLoading || !detail.data ? (
        <Skeleton className="h-32 w-full" />
      ) : (
        <>
          <PageHeader
            title={detail.data.paket_name}
            description={
              [
                detail.data.frm_code,
                detail.data.modul,
                detail.data.layanan_name,
              ]
                .filter(Boolean)
                .join(" · ") || undefined
            }
          />

          {/* Form-level metadata card */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Info form</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
              <KV label="Kode FRM" value={detail.data.frm_code} />
              <KV label="Kode layanan" value={detail.data.layanan_code} />
              <KV label="Modul" value={detail.data.modul} />
              <KV label="Nama form audit live" value={detail.data.audit_form_title} />
              <KV
                label="Cakupan"
                value={`${detail.data.covered_question_count}/${detail.data.question_count} pertanyaan terpetakan`}
              />
              <KV
                label="Sumber"
                value={
                  <div className="flex flex-wrap gap-1.5">
                    {detail.data.in_audit ? (
                      <Badge variant="success">Audit live</Badge>
                    ) : (
                      <Badge variant="outline">Tanpa audit</Badge>
                    )}
                    {detail.data.in_converter_breadcrumbs && (
                      <Badge variant="secondary">Converter tersambung</Badge>
                    )}
                  </div>
                }
              />
              {detail.data.demos_union.length > 0 && (
                <div className="md:col-span-2">
                  <p className="mb-1 text-xs text-[var(--muted-foreground)]">
                    Demografi (klaster) eligible
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {detail.data.demos_union.map((d) => (
                      <Badge key={d} variant="outline" className="font-normal">
                        {d}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Question search + list */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Pertanyaan ({filtered.length}/{questions.length})
              </CardTitle>
              <CardDescription>
                Ketuk pertanyaan untuk membuka. Tiap baris menampilkan opsi ASIK
                live, kode PPV Padanan, dan jalur sumber EPUS yang diambil
                converter.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
                <Input
                  placeholder="Filter berdasarkan label, kode PPV, teks pilihan, atau jalur EPUS…"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  className="pl-9"
                />
              </div>

              {filtered.length === 0 ? (
                <EmptyState
                  title="Tidak ada pertanyaan yang cocok dengan filter"
                  description="Bersihkan filter untuk melihat semua pertanyaan."
                />
              ) : (
                <div className="space-y-2">
                  {filtered.map((q, idx) => (
                    <QuestionRow
                      key={`${q.label}-${idx}`}
                      q={q}
                      index={idx + 1}
                      formName={detail.data.paket_name}
                      formFrm={detail.data.frm_code}
                      layananCode={detail.data.layanan_code}
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function KV({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs text-[var(--muted-foreground)]">{label}</p>
      <div className="mt-0.5 break-words text-sm">
        {value === null || value === undefined || value === "" ? (
          <span className="text-[var(--muted-foreground)]">—</span>
        ) : (
          value
        )}
      </div>
    </div>
  );
}

function CodeKV({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="rounded border border-[var(--border)] bg-[var(--background)] px-1.5 py-1">
      <p className="font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        {label}
      </p>
      <code className="mt-0.5 block truncate font-mono">
        {value ?? "—"}
      </code>
    </div>
  );
}

function QuestionRow({
  q,
  index,
  formName,
  formFrm,
  layananCode,
}: {
  q: MappingQuestion;
  index: number;
  formName: string;
  formFrm: string | null;
  layananCode: string | null;
}) {
  const [open, setOpen] = useState(false);
  const total = Math.max(q.choices.length, q.live_options.length);
  // Live SurveyJS name format: LPM|FRM|PPM|kind
  const liveParts = (q.live_name ?? "").split("|");
  const lpmFromLive = liveParts[0] || layananCode || null;
  const frmFromLive = liveParts[1] || formFrm || null;
  const ppmFromLive = liveParts[2] || (q.parameter_codes[0] ?? null);
  return (
    <div
      className={cn(
        "rounded-md border border-[var(--border)] bg-[var(--card)]",
        open && "shadow-sm",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start gap-3 p-3 text-left"
      >
        <span className="mt-0.5 inline-flex h-6 min-w-[1.5rem] shrink-0 items-center justify-center rounded bg-[var(--muted)] px-1 text-xs font-mono text-[var(--muted-foreground)]">
          {index}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium leading-snug">{q.label}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {q.parameter_codes.map((c) => (
              <code
                key={c}
                className="rounded bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-mono text-[var(--muted-foreground)]"
              >
                {c}
              </code>
            ))}
            {q.live_kind && (
              <Badge variant="outline" className="text-[10px] font-normal">
                {q.live_kind}
              </Badge>
            )}
            {q.tipe && (
              <Badge variant="outline" className="text-[10px] font-normal">
                {q.tipe}
              </Badge>
            )}
            {q.status_2026 && (
              <Badge
                variant={
                  q.status_2026 === "Baru"
                    ? "secondary"
                    : q.status_2026 === "Berubah"
                      ? "destructive"
                      : "outline"
                }
                className="text-[10px] font-normal"
              >
                {q.status_2026}
              </Badge>
            )}
            <Badge
              variant={q.covered_by_converter ? "success" : "outline"}
              className="text-[10px] font-normal"
            >
              {q.covered_by_converter ? "EPUS terpetakan" : "Tanpa sumber EPUS"}
            </Badge>
            {total > 0 && (
              <span className="text-[10px] text-[var(--muted-foreground)]">
                {total} opsi
              </span>
            )}
          </div>
        </div>
        {open ? (
          <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
        ) : (
          <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
        )}
      </button>

      {open && (
        <div className="grid gap-4 border-t border-[var(--border)] p-4 text-sm md:grid-cols-2">
          {/* EPUS source */}
          <div className="rounded-md border border-[var(--border)] bg-[var(--muted)]/30 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              Sumber EPUS
            </p>
            {q.epus_source ? (
              <code className="mt-2 inline-block break-all rounded bg-[var(--background)] px-2 py-1 font-mono text-xs">
                {q.epus_source}
              </code>
            ) : (
              <p className="mt-2 text-xs text-[var(--muted-foreground)]">
                Tidak terpetakan — nakes ASIK mengisi manual setelah sync.
              </p>
            )}
          </div>

          {/* ASIK source */}
          <div className="rounded-md border border-[var(--border)] bg-[var(--muted)]/30 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              Sumber ASIK
            </p>
            <code className="mt-2 inline-block break-all rounded bg-[var(--background)] px-2 py-1 font-mono text-xs">
              {formName} &gt; {q.label}
            </code>
            <div className="mt-2 grid grid-cols-3 gap-1.5 text-[10px]">
              <CodeKV label="LPM" value={lpmFromLive} />
              <CodeKV label="FRM" value={frmFromLive} />
              <CodeKV label="PPM" value={ppmFromLive} />
            </div>
            {q.live_kind && (
              <p className="mt-2 text-[11px] text-[var(--muted-foreground)]">
                Jenis field: <code className="font-mono">{q.live_kind}</code>
              </p>
            )}
          </div>

          {/* Live ASIK options */}
          {q.live_options.length > 0 && (
            <div className="md:col-span-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                Opsi ASIK live (audit 2026-04-29)
              </p>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {q.live_options.map((o) => (
                  <code
                    key={o}
                    className="rounded bg-[var(--accent)]/40 px-2 py-1 text-xs"
                  >
                    {o}
                  </code>
                ))}
              </div>
            </div>
          )}

          {/* Padanan choices with PPV codes */}
          {q.choices.length > 0 && (
            <div className="md:col-span-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                Pilihan Padanan (kode PPV + nilai poin)
              </p>
              <div className="mt-1 overflow-hidden rounded border border-[var(--border)]">
                <table className="w-full text-xs">
                  <thead className="bg-[var(--muted)]/40 text-[var(--muted-foreground)]">
                    <tr>
                      <th className="px-2 py-1.5 text-left font-medium">
                        Pilihan
                      </th>
                      <th className="px-2 py-1.5 text-left font-mono font-medium">
                        Kode
                      </th>
                      <th className="px-2 py-1.5 text-right font-medium">
                        Nilai Poin
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {q.choices.map((c, i) => (
                      <tr
                        key={i}
                        className="border-t border-[var(--border)] hover:bg-[var(--accent)]/20"
                      >
                        <td className="px-2 py-1.5">{String(c.line ?? "—")}</td>
                        <td className="px-2 py-1.5 font-mono text-[var(--muted-foreground)]">
                          {c.code ?? "—"}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums">
                          {c.nilai_poin ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Demos */}
          {q.demos.length > 0 && (
            <div className="md:col-span-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                Berlaku untuk klaster
              </p>
              <div className="mt-1 flex flex-wrap gap-1">
                {q.demos.map((d) => (
                  <Badge key={d} variant="outline" className="font-normal">
                    {d}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
