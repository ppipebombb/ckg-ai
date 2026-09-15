"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Calculator } from "lucide-react";

/** Collapsible "Cara Membaca" explainer for the Registri Hipertensi.
 * Mirrors the "Formula & Logika" sheet in the Excel export — keep both in
 * sync. Wording is deliberately plain, non-technical Indonesian (read by
 * puskesmas staff); the technical detail lives in
 * documents/KERTAS_KERJA_HIPERTENSI_LOGIC.md. */

const DRUG_FAMILIES: [string, string][] = [
  ["Antagonis kalsium (CCB)", "Amlodipin, Nifedipin, Felodipin, Nikardipin, Lerkanidipin, Diltiazem, Verapamil"],
  ["ACE inhibitor", "Kaptopril (Captopril), Lisinopril, Ramipril, Enalapril, Perindopril, Imidapril"],
  ["ARB (sartan)", "Kandesartan, Losartan, Valsartan, Irbesartan, Telmisartan, Olmesartan"],
  ["Diuretik", "Hidroklorotiazid (HCT) & tiazid lain, Furosemid, Spironolakton, Indapamid, Klortalidon"],
  ["Beta-blocker", "Bisoprolol, Atenolol, Propranolol, Metoprolol, Carvedilol, Nebivolol"],
  ["Lainnya", "Metildopa, Klonidin, Doksazosin, Terazosin, Prazosin, Hidralazin, Minoxidil"],
];

const REFERENCES: [string, string][] = [
  [
    "Juknis CKG — KMK 84/2026 (batas Normal/Pre-Hipertensi/Hipertensi + aturan rata-rata 2x ukur)",
    "https://kesprimkom.kemkes.go.id/assets/uploads/contents/others/2026kepmenkes084.pdf",
  ],
  [
    "PNPK Hipertensi Dewasa — KMK 4634/2021 (klasifikasi hipertensi)",
    "https://kemkes.go.id/id/pnpk-2021---tata-laksana-hipertensi-dewasa",
  ],
  [
    "Pedoman Pengendalian Hipertensi di FKTP 2024 ('terkendali' = di bawah 140/90 pada kunjungan terakhir)",
    "https://diskes.badungkab.go.id/storage/diskes/file/Buku%20Pedoman%20Hipertensi%202024.pdf",
  ],
  [
    "Permenkes 4/2019 — SPM (kontrol tensi minimal 1x/bulan)",
    "https://peraturan.bpk.go.id/Details/111713/permenkes-no-4-tahun-2019",
  ],
  [
    "Formularium Nasional — KMK 1199/2025 (daftar obat darah tinggi di puskesmas)",
    "https://farmalkes.kemkes.go.id/en/unduh/keputusan-menteri-kesehatan-republik-indonesia-nomor-hk-01-07-menkes-1199-2025-tentang-formularium-nasional/",
  ],
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs font-semibold uppercase tracking-wide text-[var(--foreground)]">
        {title}
      </div>
      <div className="space-y-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
        {children}
      </div>
    </div>
  );
}

export function HipertensiFormulaCard() {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-[var(--border)]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-sm font-medium text-[var(--foreground)] hover:bg-[var(--muted)]/40"
      >
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <Calculator className="h-4 w-4" />
        Cara Membaca Kertas Kerja Ini
        <span className="ml-auto text-xs font-normal text-[var(--muted-foreground)]">
          juga ada sebagai sheet &quot;Formula &amp; Logika&quot; di file export
        </span>
      </button>
      {open && (
        <div className="space-y-5 border-t border-[var(--border)] p-4">
          <div className="rounded-md bg-[var(--muted)]/40 p-3 text-xs leading-relaxed text-[var(--foreground)]">
            <b>Intinya — satu daftar, dua pertanyaan.</b> Kolom hasil pemeriksaan
            menjawab: <i>berapa tensi pasien saat skrining CKG?</i> Kolom Follow Up
            menjawab: <i>pada bulan-bulan setelahnya, apakah tensinya sudah di bawah
            140/90?</i> Karena pertanyaannya berbeda, labelnya bisa berbeda — dan itu
            memang benar, bukan error.
          </div>
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Section title="1 · Siapa yang masuk daftar ini?">
              <p>
                Pasien masuk daftar jika memenuhi <b>salah satu</b>:
              </p>
              <p>
                <b>(1) Sudah tercatat sebagai pasien hipertensi</b> — ada diagnosis
                hipertensi di ePuskesmas, atau pasien menjawab &quot;Ya&quot; saat ditanya
                &quot;pernah dinyatakan tekanan darah tinggi?&quot; di skrining CKG → kolom
                Riwayat = Ya.
              </p>
              <p>
                <b>(2) Tensinya di atas normal saat skrining CKG</b> — rata-rata
                pengukuran 130/85 ke atas → kolom Interpretasi = Hipertensi (140/90 ke
                atas) atau Pre-Hipertensi (130–139/85–89).
              </p>
              <p>
                Pasien yang tensinya Normal (di bawah 130/85) <b>dan</b> tidak pernah
                didiagnosis tidak ditampilkan — belum perlu dipantau di sini.
              </p>
            </Section>
            <Section title="2 · Dari mana angka tensinya?">
              <p>
                <b>TD 1</b>: pemeriksaan di ePuskesmas pada hari kunjungan CKG.
              </p>
              <p>
                <b>TD 2</b>: dari data skrining CKG (ASIK). Sering kosong — artinya
                petugas hanya mengukur satu kali. Itu normal, bukan error.
              </p>
              <p>
                <b>Rerata</b> = (TD1 + TD2) ÷ 2. Kalau TD2 kosong, rerata = TD1 saja.
                Di file export, rumusnya tertanam langsung di sel — klik sel Rerata /
                Interpretasi untuk melihatnya.
              </p>
              <p>
                <b>Sumber tiap nilai (ASIK / ePus)</b>: ASIK = data skrining CKG
                (sumber utama); ePus = ePuskesmas (pelengkap saat ASIK kosong). Buka
                baris pasien untuk melihat tag pada TD, Riwayat HT, dan Obat — TD 1
                kadang justru dari ASIK. Follow Up selalu dari ePuskesmas.
              </p>
            </Section>
            <Section title="3 · Arti label">
              <p>
                <b>Interpretasi (saat kunjungan CKG)</b>: kalau pasien sudah punya
                diagnosis hipertensi (Riwayat HT = Ya) → selalu Hipertensi, berapa pun
                tensinya. Kalau Riwayat HT = Tidak, dinilai dari tensinya: 140/90 ke atas
                → Hipertensi · 130–139 / 85–89 → Pre-Hipertensi · di bawah itu → Normal.
                Cukup <b>satu angka</b> yang tinggi: 137/100 = Hipertensi karena angka
                bawahnya (100) sudah ≥ 90, walau angka atasnya belum 140. Batas sesuai
                aturan resmi Kemenkes untuk CKG.
              </p>
              <p>
                Yang dinilai adalah <b>rata-rata</b> (kolom Rerata). Kalau hanya ada
                satu kali ukur (tidak ada TD 2), rata-ratanya = TD 1 — jadi satu kali
                ukur yang tinggi sudah cukup untuk Hipertensi.
              </p>
              <p>
                <b>Status Follow Up (tiap bulan)</b>: di bawah 140/90 → &quot;Pasien
                hipertensi terkendali (target tercapai)&quot; · 140/90 ke atas → &quot;Pasien
                hipertensi tidak terkendali (target tidak tercapai)&quot; · tidak ada
                pemeriksaan bulan itu → &quot;Pasien Missed Visit&quot;.
              </p>
            </Section>
            <Section title="4 · Cara baca Follow Up">
              <p>
                Mulai <b>bulan setelah</b> bulan skrining CKG (bulan skrining tidak
                diulang — sudah ada di kolom hasil pemeriksaan).
              </p>
              <p>
                <b>Semua kunjungan ditampilkan</b>: kalau pasien datang beberapa kali
                dalam sebulan, semua kunjungannya ditampilkan berurutan —
                masing-masing dengan tanggal, hasil tensi, dan statusnya sendiri.
              </p>
              <p>
                Bulan lewat tanpa pemeriksaan tensi = Missed Visit. Bulan yang belum
                terjadi dibiarkan kosong.
              </p>
            </Section>
            <Section title="5 · Jenis Obat — hanya obat darah tinggi">
              <p>
                Vitamin, antibiotik, obat gula, dan obat lain sengaja tidak
                ditampilkan (sesuai kolom dirjen &quot;List Obat Hipertensi&quot;). Yang
                dihitung obat darah tinggi:
              </p>
              <ul className="list-disc space-y-0.5 pl-4">
                {DRUG_FAMILIES.map(([fam, drugs]) => (
                  <li key={fam}>
                    <b>{fam}</b>: {drugs}
                  </li>
                ))}
              </ul>
            </Section>
            <Section title="6 · Kalau labelnya terlihat 'bertentangan'">
              <p>
                <b>&quot;Hipertensi&quot; di awal, lalu &quot;terkendali&quot;</b>: saat skrining tensinya
                tinggi (itulah alasan dia masuk daftar), lalu bulan-bulan berikutnya
                sudah di bawah 140/90. Justru kabar baik — skrining berhasil
                menemukan, kontrolnya berhasil. Label awal tidak berubah karena ia
                mencatat kondisi saat skrining.
              </p>
              <p>
                <b>Interpretasi &quot;Hipertensi&quot; padahal tensinya hari itu bagus</b>:
                pasien ini sudah punya diagnosis hipertensi (Riwayat = Ya), jadi tetap
                berlabel Hipertensi walau tensinya di bawah 140/90 — diagnosisnya tidak
                hilang karena satu hasil ukur yang bagus. Kalau sudah terkontrol, Follow
                Up bulan berikutnya menyebutnya &quot;terkendali&quot;.
              </p>
              <p>
                <b>Riwayat &quot;Tidak&quot; tapi Interpretasi &quot;Hipertensi&quot;</b>:
                Riwayat = pernah didiagnosis <i>sebelumnya</i>. Pasien yang baru
                ketahuan saat skrining memang riwayatnya &quot;Tidak&quot; — dia pasien
                hipertensi yang baru ditemukan.
              </p>
              <p>
                <b>Interpretasi &quot;Pre-Hipertensi&quot; tapi di Follow Up disebut &quot;pasien
                hipertensi&quot;</b>: pasien Pre-Hipertensi (130–139/85–89, belum
                didiagnosis) ikut dipantau lebih awal. Tulisan &quot;Pasien hipertensi
                terkendali/tidak terkendali&quot; itu istilah baku format dirjen — bacalah
                sebagai: target di bawah 140/90 tercapai atau tidak.
              </p>
            </Section>
            <Section title="Dasar aturan (untuk yang ingin memeriksa)">
              <ul className="list-disc space-y-0.5 pl-4">
                {REFERENCES.map(([label, url]) => (
                  <li key={url}>
                    <a
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      className="underline decoration-dotted underline-offset-2 hover:text-[var(--foreground)]"
                    >
                      {label}
                    </a>
                  </li>
                ))}
              </ul>
            </Section>
          </div>
        </div>
      )}
    </div>
  );
}
