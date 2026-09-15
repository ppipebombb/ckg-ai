"use client";

import { use, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, KeyRound, PlayCircle } from "lucide-react";
import { format, parseISO } from "date-fns";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Pagination } from "@/components/common/pagination";
import { ErrorState } from "@/components/common/error-state";
import { EmptyState } from "@/components/common/empty-state";
import { CredentialsDialog } from "@/components/puskesmas/credentials-dialog";
import { StartScrapeDialog } from "@/components/scrape/start-scrape-dialog";
import { ScrapeStatusBadge } from "@/components/scrape/scrape-status-badge";
import { CronConfigCard } from "@/components/cron/cron-config-card";
import { SchoolCronCard } from "@/components/school/school-cron-card";
import { usePuskesmas } from "@/lib/hooks/use-puskesmas";
import { useScrapeJobList } from "@/lib/hooks/use-scrape";
import type { CredKind } from "@/lib/api/puskesmas";

export default function PuskesmasDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [credKind, setCredKind] = useState<CredKind | null>(null);
  const [scrapeOpen, setScrapeOpen] = useState(false);
  const [page, setPage] = useState(1);

  const detail = usePuskesmas(id);
  const jobsQuery = useMemo(
    () => ({ page, size: 10, puskesmas_id: id }),
    [page, id],
  );
  const jobs = useScrapeJobList(jobsQuery);

  if (detail.error) return <ErrorState error={detail.error} />;

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="h-8 -ml-2 px-2">
        <Link href="/puskesmas" prefetch={false}>
          <ArrowLeft className="h-4 w-4" />
          Kembali
        </Link>
      </Button>

      <PageHeader
        title={detail.data?.name ?? "Memuat…"}
        description="Kelola kredensial dan jalankan scrape."
        actions={
          <Button onClick={() => setScrapeOpen(true)} disabled={!detail.data}>
            <PlayCircle className="h-4 w-4" />
            Mulai scrape
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {(["epus", "asik"] as const).map((kind) => {
          const isCredSet = detail.data
            ? kind === "epus"
              ? detail.data.is_epus_cred_set
              : detail.data.is_asik_cred_set
            : undefined;
          return (
            <Card key={kind}>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <CardTitle className="text-base">{kind.toUpperCase()}</CardTitle>
                  {isCredSet !== undefined && (
                    <span
                      className={`text-xs font-medium px-1.5 py-0.5 rounded-md ${
                        isCredSet
                          ? "bg-green-100 text-green-700"
                          : "bg-[var(--muted)] text-[var(--muted-foreground)]"
                      }`}
                    >
                      {isCredSet ? "Terisi" : "Belum diisi"}
                    </span>
                  )}
                </div>
                <CardDescription>
                  {kind === "epus" ? detail.data?.epus_url : detail.data?.asik_url}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setCredKind(kind)}
                >
                  <KeyRound className="h-4 w-4" />
                  Kredensial
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <CronConfigCard puskesmasId={id} />
        <SchoolCronCard puskesmasId={id} />
      </div>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Job scrape terbaru</h2>
        {jobs.error && <ErrorState error={jobs.error} />}
        <div className="rounded-lg border border-[var(--border)]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Tanggal</TableHead>
                <TableHead>Jenis</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Jumlah</TableHead>
                <TableHead>Dimulai</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.data?.items.map((j) => (
                <TableRow key={j.id}>
                  <TableCell className="font-medium">{j.date_filter}</TableCell>
                  <TableCell className="uppercase">{j.kind}</TableCell>
                  <TableCell>
                    <ScrapeStatusBadge status={j.status} />
                  </TableCell>
                  <TableCell className="text-xs text-[var(--muted-foreground)]">
                    {j.scraped_count != null
                      ? `${j.scraped_count} ter-scrape • ${j.inserted_count ?? 0}+/${j.updated_count ?? 0}~`
                      : "—"}
                  </TableCell>
                  <TableCell className="text-xs text-[var(--muted-foreground)]">
                    {j.started_at
                      ? format(parseISO(j.started_at), "yyyy-MM-dd HH:mm")
                      : "—"}
                  </TableCell>
                  <TableCell>
                    <Button variant="ghost" size="sm" asChild>
                      <Link href={`/scrape-jobs/${j.id}`} prefetch={false}>
                        Buka
                      </Link>
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {jobs.data && jobs.data.items.length === 0 && (
            <div className="p-6">
              <EmptyState title="Belum ada job scrape" />
            </div>
          )}
        </div>
        {jobs.data && jobs.data.items.length > 0 && (
          <Pagination
            page={jobs.data.page}
            pages={jobs.data.pages}
            total={jobs.data.total}
            onPageChange={setPage}
          />
        )}
      </div>

      {credKind && (
        <CredentialsDialog
          open={!!credKind}
          onOpenChange={(v) => !v && setCredKind(null)}
          puskesmasId={id}
          kind={credKind}
          isCredSet={
            detail.data
              ? credKind === "epus"
                ? detail.data.is_epus_cred_set
                : detail.data.is_asik_cred_set
              : false
          }
        />
      )}
      <StartScrapeDialog
        open={scrapeOpen}
        onOpenChange={setScrapeOpen}
        puskesmasId={id}
      />
    </div>
  );
}
