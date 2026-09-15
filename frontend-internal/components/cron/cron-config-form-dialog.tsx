"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  CronConfigCreate,
  type CronConfig,
  type CronMergeModeT,
  type CronSyncModeT,
} from "@/lib/api/types";
import {
  useCreateCronConfig,
  useUpdateCronConfig,
} from "@/lib/hooks/use-cron-config";
import { applyApiErrorToForm } from "@/lib/api/form-errors";

type FormValues = {
  hour: number;
  minute: number;
  target_offset_days: number;
  lookback_days: number;
  enabled: boolean;
  merge_mode: CronMergeModeT;
  sync_mode: CronSyncModeT;
  create_new: boolean;
};

const KNOWN_FIELDS = [
  "hour",
  "minute",
  "target_offset_days",
  "lookback_days",
  "enabled",
  "merge_mode",
  "sync_mode",
  "create_new",
] as const;

export function CronConfigFormDialog({
  open,
  onOpenChange,
  puskesmasId,
  existing,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  puskesmasId: string;
  existing: CronConfig | null;
}) {
  const create = useCreateCronConfig(puskesmasId);
  const update = useUpdateCronConfig(puskesmasId);

  const form = useForm<FormValues>({
    resolver: zodResolver(CronConfigCreate),
    defaultValues: {
      hour: 6,
      minute: 0,
      target_offset_days: -1,
      lookback_days: 3,
      enabled: true,
      merge_mode: "normal",
      sync_mode: "off",
      create_new: false,
    },
  });

  useEffect(() => {
    if (open) {
      if (existing) {
        form.reset({
          hour: existing.hour,
          minute: existing.minute,
          target_offset_days: existing.target_offset_days,
          lookback_days: existing.lookback_days,
          enabled: existing.enabled,
          merge_mode: existing.merge_mode,
          sync_mode: existing.sync_mode,
          create_new: existing.create_new,
        });
      } else {
        form.reset({
          hour: 6,
          minute: 0,
          target_offset_days: -1,
          lookback_days: 3,
          enabled: true,
          merge_mode: "normal",
          sync_mode: "off",
          create_new: false,
        });
      }
    }
  }, [open, existing, form]);

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      if (existing) {
        await update.mutateAsync(values);
        toast.success("Jadwal cron diperbarui");
      } else {
        await create.mutateAsync(values);
        toast.success("Jadwal cron dibuat");
      }
      onOpenChange(false);
    } catch (err) {
      applyApiErrorToForm(err, form.setError, KNOWN_FIELDS);
    }
  });

  const pending = create.isPending || update.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {existing ? "Edit jadwal cron" : "Buat jadwal cron"}
          </DialogTitle>
          <DialogDescription>
            Menjalankan scrape ASIK + EPUS dan Merge setiap hari pada waktu Jakarta yang dipilih.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="cron-hour">Jam (0–23)</Label>
              <Input
                id="cron-hour"
                type="number"
                min={0}
                max={23}
                {...form.register("hour", { valueAsNumber: true })}
              />
              {form.formState.errors.hour && (
                <p className="text-xs text-[var(--destructive)]">
                  {form.formState.errors.hour.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="cron-minute">Menit (0–59)</Label>
              <Input
                id="cron-minute"
                type="number"
                min={0}
                max={59}
                {...form.register("minute", { valueAsNumber: true })}
              />
              {form.formState.errors.minute && (
                <p className="text-xs text-[var(--destructive)]">
                  {form.formState.errors.minute.message}
                </p>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <Label>Tanggal target</Label>
            <Select
              value={String(form.watch("target_offset_days"))}
              onValueChange={(v) =>
                form.setValue("target_offset_days", Number(v), {
                  shouldDirty: true,
                })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="-1">Kemarin (D-1)</SelectItem>
                <SelectItem value="0">Hari ini (D)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="cron-lookback">Jendela lookback (hari)</Label>
            <Input
              id="cron-lookback"
              type="number"
              min={1}
              max={14}
              {...form.register("lookback_days", { valueAsNumber: true })}
            />
            {form.formState.errors.lookback_days && (
              <p className="text-xs text-[var(--destructive)]">
                {form.formState.errors.lookback_days.message}
              </p>
            )}
            <p className="text-xs text-[var(--muted-foreground)]">
              Tiap run memproses ulang N hari terakhir hingga tanggal target,
              sehingga ePus/ASIK yang datang terlambat — yang baru cocok dengan
              tanggal lampau setelah kedua sisi tersedia — tetap ter-scrape +
              ter-merge. 1 = hanya tanggal target. Default 3.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <input
              id="cron-enabled"
              type="checkbox"
              {...form.register("enabled")}
            />
            <Label htmlFor="cron-enabled" className="cursor-pointer">
              Aktif
            </Label>
          </div>

          <div className="space-y-2">
            <Label>Mode merge</Label>
            <Select
              value={form.watch("merge_mode")}
              onValueChange={(v) =>
                form.setValue("merge_mode", v as CronMergeModeT, {
                  shouldDirty: true,
                })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="normal">Normal (merge pasien baru)</SelectItem>
                <SelectItem value="force_remerge">
                  Merge ulang paksa (merge ulang semua)
                </SelectItem>
                <SelectItem value="no_merge">
                  Tanpa merge (scrape saja — lewati merge)
                </SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-[var(--muted-foreground)]">
              Merge ulang paksa menjalankan ulang LLM pada pasien yang sudah
              di-merge (biaya tambahan). Tanpa merge hanya scrape — pakai saat
              provider LLM sedang down, lalu merge kemudian.
            </p>
          </div>

          {/* ASIK: fill toggle (sync_mode) + create toggle (create_new).
              "isi pemeriksaan" checked ⟺ sync_mode !== "off"; the force
              sub-option maps normal↔force_resync. */}
          <div className="space-y-3">
            <Label>ASIK (setelah merge)</Label>

            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <input
                  id="cron-create-missing"
                  type="checkbox"
                  checked={form.watch("sync_mode") !== "off"}
                  onChange={(e) => {
                    if (e.target.checked) {
                      form.setValue("sync_mode", "normal", { shouldDirty: true });
                    } else {
                      // Off clears the force sub-option and create-new — both
                      // require sync on (the backend rejects create_new + sync off).
                      form.setValue("sync_mode", "off", { shouldDirty: true });
                      form.setValue("create_new", false, { shouldDirty: true });
                    }
                  }}
                />
                <Label htmlFor="cron-create-missing" className="cursor-pointer">
                  Sekaligus isi pemeriksaan pasien yang sudah ada di ASIK
                </Label>
              </div>
              <p className="text-xs text-[var(--muted-foreground)]">
                Isi pemeriksaan ASIK untuk pasien yang sudah ada di ASIK (NIK
                cocok ePus + ASIK). Diabaikan saat mode merge adalah Tanpa merge.
              </p>
              {form.watch("sync_mode") !== "off" && (
                <div className="ml-6 flex items-center gap-2">
                  <input
                    id="cron-sync-force"
                    type="checkbox"
                    checked={form.watch("sync_mode") === "force_resync"}
                    onChange={(e) =>
                      form.setValue(
                        "sync_mode",
                        e.target.checked ? "force_resync" : "normal",
                        { shouldDirty: true },
                      )
                    }
                  />
                  <Label
                    htmlFor="cron-sync-force"
                    className="cursor-pointer text-sm"
                  >
                    Isi ulang pasien yang sudah tersinkron (sinkron ulang paksa)
                  </Label>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <input
                  id="cron-create-new"
                  type="checkbox"
                  disabled={form.watch("sync_mode") === "off"}
                  {...form.register("create_new")}
                />
                <Label htmlFor="cron-create-new" className="cursor-pointer">
                  Sekaligus buat pasien baru di ASIK
                </Label>
              </div>
              {form.formState.errors.create_new && (
                <p className="text-xs text-[var(--destructive)]">
                  {form.formState.errors.create_new.message}
                </p>
              )}
              <p className="text-xs text-[var(--muted-foreground)]">
                Daftarkan pasien ePus-saja yang bertanda Tandai-CKG dan belum ada
                di ASIK — membuatnya dari awal, lalu mengisi pemeriksaannya.
                Membutuhkan &ldquo;isi pemeriksaan&rdquo; aktif dan alamat
                default terpasang pada puskesmas ini.
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={pending}
            >
              Batal
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? "Menyimpan…" : existing ? "Simpan" : "Buat"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
