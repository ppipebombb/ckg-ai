"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
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
import { AsyncCombobox } from "@/components/ui/async-combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import { useLoopConfig, useStartLoopRun } from "@/lib/hooks/use-loop";
import { asApiError } from "@/lib/api/client";

export function StartLoopDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const router = useRouter();
  const [puskesmasId, setPuskesmasId] = useState("");
  const [pinRef, setPinRef] = useState("");
  const [openPr, setOpenPr] = useState<"default" | "on" | "off">("default");
  const pkDetail = usePuskesmas(puskesmasId || undefined);
  const cfg = useLoopConfig(open);
  const start = useStartLoopRun();

  useEffect(() => {
    if (open) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setPuskesmasId("");
      setPinRef("");
      setOpenPr("default");
    }
  }, [open]);

  const onSubmit = async () => {
    if (!puskesmasId) {
      toast.error("Pilih puskesmas dulu");
      return;
    }
    try {
      const run = await start.mutateAsync({
        puskesmas_id: puskesmasId,
        pin_ref: pinRef.trim() || undefined,
        open_pr: openPr === "default" ? undefined : openPr === "on",
      });
      toast.success("Loop run dimulai");
      onOpenChange(false);
      router.push(`/loop-runs/${run.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Jalankan Loop Agent</DialogTitle>
          <DialogDescription>
            Agen login ke portal ePuskesmas puskesmas ini, membandingkan hasil
            scraper dengan situs langsung, dan membuka PR jika ada yang terlewat.
            Tidak pernah deploy atau menulis ke ASIK.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Puskesmas</Label>
            <AsyncCombobox
              value={puskesmasId || undefined}
              onChange={(v) => setPuskesmasId(v ?? "")}
              useOptions={usePuskesmasOptions}
              selectedLabel={pkDetail.data?.name}
              placeholder="Pilih puskesmas…"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="loop-pin-ref">
              Pin git ref{" "}
              <span className="font-normal text-[var(--muted-foreground)]">
                (opsional — untuk tes penerimaan)
              </span>
            </Label>
            <Input
              id="loop-pin-ref"
              placeholder="mis. 10db694^ (kosongkan untuk master)"
              value={pinRef}
              onChange={(e) => setPinRef(e.target.value)}
            />
            <p className="text-xs text-[var(--muted-foreground)]">
              Container akan checkout ref ini sebelum berjalan. Dipakai tes WAF
              untuk mereproduksi kondisi sebelum perbaikan.
            </p>
          </div>
          <div className="space-y-2">
            <Label>Buka PR bila ada perbaikan</Label>
            <Select value={openPr} onValueChange={(v) => setOpenPr(v as "default" | "on" | "off")}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">
                  Ikuti pengaturan
                  {cfg.data
                    ? ` (${cfg.data.auto_open_pr ? "aktif" : "nonaktif"})`
                    : " (…)"}
                </SelectItem>
                <SelectItem value="on">Ya — buka PR otomatis</SelectItem>
                <SelectItem value="off">
                  Tidak — push branch saja, PR dibuka manual
                </SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-[var(--muted-foreground)]">
              Kalau tidak, perubahan tetap aman di GitHub dan run berstatus
              Perubahan siap — tombol Buat PR muncul di halaman run ini.
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={start.isPending}
          >
            Batal
          </Button>
          <Button onClick={onSubmit} disabled={start.isPending || !puskesmasId}>
            {start.isPending ? "Memulai…" : "Jalankan"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
