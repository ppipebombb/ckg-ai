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
import { SchoolCronConfigCreate, type SchoolCronConfig } from "@/lib/api/types";
import {
  useCreateSchoolCronConfig,
  useUpdateSchoolCronConfig,
} from "@/lib/hooks/use-school-cron";
import { applyApiErrorToForm } from "@/lib/api/form-errors";

type FormValues = { hour: number; minute: number; enabled: boolean };

const KNOWN_FIELDS = ["hour", "minute", "enabled"] as const;

export function SchoolCronFormDialog({
  open,
  onOpenChange,
  puskesmasId,
  existing,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  puskesmasId: string;
  existing: SchoolCronConfig | null;
}) {
  const create = useCreateSchoolCronConfig(puskesmasId);
  const update = useUpdateSchoolCronConfig(puskesmasId);

  const form = useForm<FormValues>({
    resolver: zodResolver(SchoolCronConfigCreate),
    defaultValues: { hour: 7, minute: 0, enabled: true },
  });

  useEffect(() => {
    if (open) {
      form.reset(
        existing
          ? { hour: existing.hour, minute: existing.minute, enabled: existing.enabled }
          : { hour: 7, minute: 0, enabled: true },
      );
    }
  }, [open, existing, form]);

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      if (existing) {
        await update.mutateAsync(values);
        toast.success("Cron sekolah diperbarui");
      } else {
        await create.mutateAsync(values);
        toast.success("Cron sekolah dibuat");
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
            {existing ? "Edit cron CKG Sekolah" : "Buat cron CKG Sekolah"}
          </DialogTitle>
          <DialogDescription>
            Menjalankan scrape CKG Sekolah penuh (setiap sekolah × kelas) setiap
            hari pada waktu Jakarta yang dipilih. Tanpa tanggal — tidak ada langkah merge.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="scron-hour">Jam (0–23)</Label>
              <Input
                id="scron-hour"
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
              <Label htmlFor="scron-minute">Menit (0–59)</Label>
              <Input
                id="scron-minute"
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

          <div className="flex items-center gap-2">
            <input id="scron-enabled" type="checkbox" {...form.register("enabled")} />
            <Label htmlFor="scron-enabled" className="cursor-pointer">
              Aktif
            </Label>
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
