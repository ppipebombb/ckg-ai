"use client";

import { useState, useEffect } from "react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useLoopConfig, useUpdateLoopConfig } from "@/lib/hooks/use-loop";
import type { LoopMergeModeValue } from "@/lib/api/types";
import { asApiError } from "@/lib/api/client";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
        {title}
      </p>
      {children}
    </div>
  );
}

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor?: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">{hint}</p>
    </div>
  );
}

export function LoopSettingsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const cfg = useLoopConfig(open);
  const save = useUpdateLoopConfig();

  const [mergeMode, setMergeMode] = useState<LoopMergeModeValue>("manual");
  const [maxFix, setMaxFix] = useState("5");
  const [budget, setBudget] = useState("20");
  const [maxRev, setMaxRev] = useState("3");
  const [nightly, setNightly] = useState<"on" | "off">("off");
  const [openPr, setOpenPr] = useState<"on" | "off">("on");

  useEffect(() => {
    if (open && cfg.data) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMergeMode(cfg.data.merge_mode);
      setMaxFix(String(cfg.data.max_fix_iterations));
      setBudget(String(cfg.data.nightly_budget));
      setMaxRev(String(cfg.data.max_review_iterations));
      setNightly(cfg.data.nightly_enabled ? "on" : "off");
      setOpenPr(cfg.data.auto_open_pr ? "on" : "off");
    }
  }, [open, cfg.data]);

  const onSubmit = async () => {
    try {
      await save.mutateAsync({
        merge_mode: mergeMode,
        auto_open_pr: openPr === "on",
        nightly_budget: Number(budget),
        max_fix_iterations: Number(maxFix),
        max_review_iterations: Number(maxRev),
        nightly_enabled: nightly === "on",
      });
      toast.success("Pengaturan disimpan");
      onOpenChange(false);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Pengaturan Loop Agent</DialogTitle>
          <DialogDescription>
            Mengatur cara kerja agent pemelihara scraper. Model & API key dipilih
            per peran di menu Konfigurasi LLM.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-5">
          <Section title="Hasil perbaikan">
            <Field
              label="Cara merge hasil perbaikan"
              hint="Agent selalu membuat Pull Request di GitHub. Manual: Anda yang
                menekan tombol merge. Otomatis: di-merge sendiri, tapi hanya jika
                reviewer menyetujui DAN semua pemeriksaan lolos — dan tetap tidak
                pernah deploy ke server."
            >
              <Select
                value={mergeMode}
                onValueChange={(v) => setMergeMode(v as LoopMergeModeValue)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="manual">Manual — saya yang merge</SelectItem>
                  <SelectItem value="auto">Otomatis — merge sendiri bila lolos semua</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field
              label="Buka PR otomatis"
              hint="Aktif: setiap perbaikan langsung membuka Pull Request.
                Nonaktif: perubahan tetap di-commit dan branch-nya di-push ke
                GitHub (tidak pernah hilang), run berstatus Perubahan siap,
                dan PR dibuka lewat tombol Buat PR di halaman run — supaya
                daftar PR tidak menumpuk."
            >
              <Select value={openPr} onValueChange={(v) => setOpenPr(v as "on" | "off")}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="on">Aktif — PR langsung dibuka</SelectItem>
                  <SelectItem value="off">Nonaktif — PR dibuka manual</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </Section>

          <Section title="Batas percobaan">
            <div className="grid grid-cols-2 gap-3">
              <Field
                label="Maks siklus perbaikan"
                htmlFor="loop-maxfix"
                hint="Satu siklus = cek portal → agent perbaiki kode → cek
                  ulang. Diulang sampai portal tercakup penuh. Angka ini batas
                  pengaman — loop selalu berhenti begitu hijau; naikkan untuk
                  mencoba lebih lama (keseluruhan run juga dibatasi timeout 4
                  jam). Habis = run gagal, laporan gap tetap tersimpan."
              >
                <Input
                  id="loop-maxfix"
                  type="number"
                  min={1}
                  value={maxFix}
                  onChange={(e) => setMaxFix(e.target.value)}
                />
              </Field>
              <Field
                label="Maks putaran review"
                htmlFor="loop-maxrev"
                hint="Setelah lolos cek, reviewer AI menilai hasil perbaikan.
                  Ditolak = agent memperbaiki lagi lalu ditinjau ulang. Habis
                  batasnya, Pull Request tetap dibuka lengkap dengan catatan
                  reviewer agar kamu yang putuskan."
              >
                <Input
                  id="loop-maxrev"
                  type="number"
                  min={1}
                  value={maxRev}
                  onChange={(e) => setMaxRev(e.target.value)}
                />
              </Field>
            </div>
          </Section>

          <Section title="Jadwal otomatis (malam)">
            <div className="grid grid-cols-2 gap-3">
              <Field
                label="Jalan tiap tengah malam"
                hint="Setiap 00:00 WIB. Memeriksa puskesmas yang belum tuntas:
                  gagal login, dibatalkan, error, atau belum ada datanya diulang;
                  yang sudah selesai (covered, menunggu review, merged) tidak
                  diulang. Kamu juga bisa menjalankan kapan saja lewat tombol
                  Jalankan."
              >
                <Select value={nightly} onValueChange={(v) => setNightly(v as "on" | "off")}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="off">Nonaktif</SelectItem>
                    <SelectItem value="on">Aktif</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <Field
                label="Maks puskesmas per malam"
                htmlFor="loop-budget"
                hint="Batas jumlah pemeriksaan per malam agar beban server dan
                  biaya tetap terkendali."
              >
                <Input
                  id="loop-budget"
                  type="number"
                  min={1}
                  value={budget}
                  onChange={(e) => setBudget(e.target.value)}
                />
              </Field>
            </div>
          </Section>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={save.isPending}
          >
            Batal
          </Button>
          <Button onClick={onSubmit} disabled={save.isPending || cfg.isLoading}>
            {save.isPending ? "Menyimpan…" : "Simpan"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
