"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Eye, EyeOff } from "lucide-react";
import { CredIn, type CredInput } from "@/lib/api/types";
import {
  useClearCredentials,
  useDecryptCredentials,
  useSetCredentials,
} from "@/lib/hooks/use-puskesmas";
import { asApiError } from "@/lib/api/client";
import { applyApiErrorToForm } from "@/lib/api/form-errors";
import type { CredKind } from "@/lib/api/puskesmas";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ConfirmDialog } from "@/components/common/confirm-dialog";

export function CredentialsDialog({
  open,
  onOpenChange,
  puskesmasId,
  kind,
  isCredSet,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  puskesmasId: string;
  kind: CredKind;
  isCredSet: boolean;
}) {
  const [reveal, setReveal] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const set = useSetCredentials();
  const clear = useClearCredentials();
  const decrypt = useDecryptCredentials();

  const form = useForm<CredInput>({
    resolver: zodResolver(CredIn),
    defaultValues: { email: "", password: "" },
  });

  const handleReveal = async () => {
    try {
      const data = await decrypt.mutateAsync({ id: puskesmasId, kind });
      form.reset({ email: data.email, password: data.password });
      setReveal(true);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      await set.mutateAsync({ id: puskesmasId, kind, input: values });
      toast.success(`Kredensial ${kind.toUpperCase()} disimpan`);
      onOpenChange(false);
    } catch (err) {
      applyApiErrorToForm(err, form.setError, ["email", "password"] as const);
    }
  });

  const handleClear = async () => {
    try {
      await clear.mutateAsync({ id: puskesmasId, kind });
      toast.success("Kredensial dihapus");
      form.reset({ email: "", password: "" });
      setConfirmClear(false);
      onOpenChange(false);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  return (
    <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Kredensial {kind.toUpperCase()}</DialogTitle>
          <DialogDescription>
            Disimpan terenkripsi. Tampilkan untuk melihat, simpan untuk memperbarui.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="cred-email">Email</Label>
            <Input id="cred-email" autoComplete="off" {...form.register("email")} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cred-password">Kata Sandi</Label>
            <div className="flex gap-2">
              <Input
                id="cred-password"
                type={reveal ? "text" : "password"}
                autoComplete="off"
                {...form.register("password")}
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={() => setReveal((v) => !v)}
                aria-label="Alihkan visibilitas"
              >
                {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </Button>
            </div>
          </div>
          <DialogFooter className="flex-row justify-between sm:justify-between">
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={handleReveal}
                disabled={!isCredSet || decrypt.isPending}
              >
                {decrypt.isPending ? "Memuat…" : "Tampilkan"}
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={() => setConfirmClear(true)}
                disabled={!isCredSet || clear.isPending}
              >
                Hapus
              </Button>
            </div>
            <Button type="submit" disabled={set.isPending}>
              {set.isPending ? "Menyimpan…" : "Simpan"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
    <ConfirmDialog
      open={confirmClear}
      onOpenChange={setConfirmClear}
      title={`Hapus kredensial ${kind.toUpperCase()}?`}
      description="Ini akan menghapus kredensial tersimpan secara permanen dan tidak bisa dibatalkan."
      confirmLabel="Hapus"
      destructive
      loading={clear.isPending}
      onConfirm={handleClear}
    />
    </>
  );
}
