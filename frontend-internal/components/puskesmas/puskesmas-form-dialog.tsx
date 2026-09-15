"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import {
  PuskesmasCreate,
  type Puskesmas,
  type PuskesmasCreateInput,
} from "@/lib/api/types";
import {
  useCreatePuskesmas,
  useUpdatePuskesmas,
} from "@/lib/hooks/use-puskesmas";
import { applyApiErrorToForm } from "@/lib/api/form-errors";
import { AlamatCascade } from "@/components/puskesmas/alamat-cascade";
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

export function PuskesmasFormDialog({
  open,
  onOpenChange,
  puskesmas,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  puskesmas?: Puskesmas;
}) {
  const isEdit = !!puskesmas;
  const create = useCreatePuskesmas();
  const update = useUpdatePuskesmas();

  const form = useForm<PuskesmasCreateInput>({
    resolver: zodResolver(PuskesmasCreate),
    defaultValues: {
      name: "",
      epus_url: "",
      asik_url: "",
      asik_default_alamat: null,
    },
  });

  useEffect(() => {
    if (open) {
      form.reset({
        name: puskesmas?.name ?? "",
        epus_url: puskesmas?.epus_url ?? "",
        asik_url: puskesmas?.asik_url ?? "",
        asik_default_alamat: puskesmas?.asik_default_alamat ?? null,
      });
    }
  }, [open, puskesmas, form]);

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      if (isEdit) {
        await update.mutateAsync({ id: puskesmas!.id, input: values });
        toast.success("Puskesmas diperbarui");
      } else {
        await create.mutateAsync(values);
        toast.success("Puskesmas dibuat");
      }
      onOpenChange(false);
    } catch (err) {
      applyApiErrorToForm(err, form.setError, ["name", "epus_url", "asik_url"] as const);
    }
  });

  const submitting = create.isPending || update.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Puskesmas" : "Puskesmas Baru"}</DialogTitle>
          <DialogDescription>
            {isEdit ? "Perbarui nama dan URL dasar puskesmas ini." : "Daftarkan puskesmas baru dengan domain dasar EPUS dan ASIK."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">Nama</Label>
            <Input id="name" {...form.register("name")} />
            {form.formState.errors.name && (
              <p className="text-xs text-[var(--destructive)]">
                {form.formState.errors.name.message}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="epus_url">EPUS URL (domain) *</Label>
            <Input
              id="epus_url"
              placeholder="epuskesmas.example.id"
              {...form.register("epus_url")}
            />
            {form.formState.errors.epus_url && (
              <p className="text-xs text-[var(--destructive)]">
                {form.formState.errors.epus_url.message}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="asik_url">ASIK URL (domain) *</Label>
            <Input
              id="asik_url"
              placeholder="asik.example.id"
              {...form.register("asik_url")}
            />
            {form.formState.errors.asik_url && (
              <p className="text-xs text-[var(--destructive)]">
                {form.formState.errors.asik_url.message}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label>Alamat Default (ASIK buat pasien)</Label>
            <p className="text-xs text-[var(--muted-foreground)]">
              Domisili cadangan untuk alur ASIK &ldquo;buat pasien baru&rdquo;, dipilih
              dari daftar milik ASIK sendiri. Pilih keempat tingkat, atau biarkan kosong.
            </p>
            <AlamatCascade
              key={puskesmas?.id ?? "new"}
              initialValue={puskesmas?.asik_default_alamat ?? null}
              onChange={(v) =>
                form.setValue("asik_default_alamat", v, { shouldDirty: true })
              }
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Batal
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Menyimpan…" : isEdit ? "Simpan" : "Buat"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
