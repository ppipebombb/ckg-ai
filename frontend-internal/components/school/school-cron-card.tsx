"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { GraduationCap, PlayCircle, Pencil, Trash2 } from "lucide-react";
import { format, parseISO } from "date-fns";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { SchoolCronFormDialog } from "./school-cron-form-dialog";
import {
  useSchoolCronConfig,
  useDeleteSchoolCronConfig,
  useRunSchoolCronNow,
  useUpdateSchoolCronConfig,
} from "@/lib/hooks/use-school-cron";
import { asApiError } from "@/lib/api/client";

function pad(n: number) {
  return n.toString().padStart(2, "0");
}

export function SchoolCronCard({ puskesmasId }: { puskesmasId: string }) {
  const cfgQuery = useSchoolCronConfig(puskesmasId);
  const update = useUpdateSchoolCronConfig(puskesmasId);
  const del = useDeleteSchoolCronConfig(puskesmasId);
  const runNow = useRunSchoolCronNow(puskesmasId);
  const router = useRouter();
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [runNowOpen, setRunNowOpen] = useState(false);

  const cfg = cfgQuery.data;

  const onToggleEnabled = async () => {
    if (!cfg) return;
    try {
      await update.mutateAsync({ enabled: !cfg.enabled });
      toast.success(cfg.enabled ? "Cron sekolah dinonaktifkan" : "Cron sekolah diaktifkan");
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const onRunNow = async () => {
    try {
      const job = await runNow.mutateAsync();
      toast.success("Scrape CKG Sekolah dimulai");
      setRunNowOpen(false);
      router.push(`/scrape-jobs/${job.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const onDelete = async () => {
    try {
      await del.mutateAsync();
      toast.success("Cron sekolah dihapus");
      setDeleteOpen(false);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  if (cfgQuery.isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Cron CKG Sekolah</CardTitle>
          <CardDescription>Memuat…</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (!cfg) {
    return (
      <>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Cron CKG Sekolah</CardTitle>
            <CardDescription>
              Belum ada jadwal CKG Sekolah untuk puskesmas ini. Sekali run
              men-scrape setiap sekolah × kelas (tanpa tanggal).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
              <GraduationCap className="h-4 w-4" />
              Atur cron sekolah
            </Button>
          </CardContent>
        </Card>
        <SchoolCronFormDialog
          open={editOpen}
          onOpenChange={setEditOpen}
          puskesmasId={puskesmasId}
          existing={null}
        />
      </>
    );
  }

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base">Cron CKG Sekolah</CardTitle>
              <CardDescription>
                Harian pukul {pad(cfg.hour)}:{pad(cfg.minute)} (Asia/Jakarta) ·{" "}
                {cfg.enabled ? "Aktif" : "Nonaktif"} · men-scrape setiap sekolah × kelas
              </CardDescription>
            </div>
            <Button
              variant={cfg.enabled ? "outline" : "default"}
              size="sm"
              onClick={onToggleEnabled}
              disabled={update.isPending}
            >
              {cfg.enabled ? "Nonaktifkan" : "Aktifkan"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-2 text-xs text-[var(--muted-foreground)]">
            <div>
              <span className="font-medium">Jalan berikutnya: </span>
              {format(parseISO(cfg.next_run_at), "yyyy-MM-dd HH:mm")}
            </div>
            <div>
              <span className="font-medium">Terakhir dijalankan: </span>
              {cfg.last_fired_at
                ? format(parseISO(cfg.last_fired_at), "yyyy-MM-dd HH:mm")
                : "—"}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setRunNowOpen(true)} disabled={runNow.isPending}>
              <PlayCircle className="h-4 w-4" />
              Jalankan sekarang
            </Button>
            <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
              <Pencil className="h-4 w-4" />
              Edit
            </Button>
            <Button variant="outline" size="sm" onClick={() => setDeleteOpen(true)}>
              <Trash2 className="h-4 w-4" />
              Hapus
            </Button>
          </div>
        </CardContent>
      </Card>

      <SchoolCronFormDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        puskesmasId={puskesmasId}
        existing={cfg}
      />

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Hapus cron CKG Sekolah?"
        description="Jadwal akan berhenti berjalan. Pasien sekolah hasil scrape tetap disimpan."
        confirmLabel="Hapus"
        destructive
        loading={del.isPending}
        onConfirm={onDelete}
      />

      <ConfirmDialog
        open={runNowOpen}
        onOpenChange={setRunNowOpen}
        title="Jalankan scrape CKG Sekolah sekarang?"
        description="Men-scrape setiap sekolah × kelas untuk puskesmas ini sekarang juga (bisa lama). Memakan waktu scraper."
        confirmLabel="Jalankan sekarang"
        loading={runNow.isPending}
        onConfirm={onRunNow}
      />
    </>
  );
}
