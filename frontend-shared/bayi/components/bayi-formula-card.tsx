"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Info } from "lucide-react";

// "Cara Membaca Kertas Kerja Ini" — kept in sync with the Excel "Formula &
// Logika" sheet (bayi_registry_export) and the ikterus derivation in
// bayi_registry_scan. Plain Indonesian for puskesmas staff.
export function BayiFormulaCard() {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--muted)]/20">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-[var(--foreground)]"
      >
        {open ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        <Info className="h-4 w-4 text-[var(--muted-foreground)]" />
        Cara Membaca Kertas Kerja Ini
      </button>
      {open && (
        <div className="space-y-4 px-4 pb-4 text-xs text-[var(--muted-foreground)]">
          <div>
            <div className="mb-1 font-semibold text-[var(--foreground)]">
              Siapa yang masuk daftar
            </div>
            <p>
              Bayi baru lahir (umur 0) yang dinilai kuning. Sheet{" "}
              <b>Ikterus</b> memuat bayi dengan klasifikasi <b>Ikterus</b> atau{" "}
              <b>Ikterus berat</b>; sheet <b>Ikterus Berat</b> hanya yang{" "}
              <b>Ikterus berat</b>.
            </p>
          </div>
          <div>
            <div className="mb-1 font-semibold text-[var(--foreground)]">
              Aturan klasifikasi (MTBM)
            </div>
            <ul className="list-disc space-y-0.5 pl-4">
              <li>
                <b>Tidak ada ikterus</b> — &quot;Apakah bayi kuning&quot; = Tidak.
              </li>
              <li>
                <b>Ikterus</b> — kuning, tanpa kriteria berat.
              </li>
              <li>
                <b>Ikterus berat</b> — kuning DAN salah satu: timbul &lt; 24 jam,
                ATAU &gt; 14 hari, ATAU kuning sampai telapak tangan/kaki.
              </li>
            </ul>
          </div>
          <div>
            <div className="mb-1 font-semibold text-[var(--foreground)]">
              Sumber klasifikasi (tanda EPUS / Hitung)
            </div>
            <p>
              Klasifikasi diambil dari isian EPUS bila tersedia (tanda{" "}
              <b>EPUS</b>); jika tidak, dihitung sistem dari kuesioner &quot;Memeriksa
              Ikterus&quot; (tanda <b>Hitung</b>). Diagnosis dan Rujuk Eksternal
              selalu dari EPUS.
            </p>
          </div>
          <div>
            <div className="mb-1 font-semibold text-[var(--foreground)]">Kolom</div>
            <ul className="list-disc space-y-0.5 pl-4">
              <li>
                <b>Tanggal Berkunjung</b> — kunjungan pertama (skrining) tempat
                ikterus dinilai.
              </li>
              <li>
                <b>Pemantauan</b> — kunjungan ikterus berikutnya (hanya di sheet
                Ikterus).
              </li>
              <li>
                <b>Rujuk Eksternal</b> — faskes tujuan rujukan pada kunjungan itu
                (dari tabel &quot;Data Rujukan External&quot; EPUS); kosong bila tidak
                dirujuk.
              </li>
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
