"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Calculator } from "lucide-react";

/** Collapsible "Cara Membaca" explainer for the Registri Dislipidemia.
 * Mirrors the "Formula & Logika" sheet in the Excel export
 * (backend/app/services/lipid_registry_export.py) — keep both in sync, and keep
 * the chatbot pack for this page in sync too (CLAUDE.md §10: these three
 * surfaces must never contradict each other).
 * Every claim here is read off backend/app/services/lipid_registry_scan.py —
 * do not write a rule from general medical knowledge, the code wins.
 * Wording is deliberately plain, non-technical Indonesian — read by puskesmas
 * staff. */

const DRUG_FAMILIES: [string, string][] = [
  [
    "Statin",
    "Simvastatin, Atorvastatin, Rosuvastatin, Pravastatin, Lovastatin, Fluvastatin",
  ],
  ["Fibrat", "Gemfibrozil, Fenofibrat"],
  // Family names kept byte-identical to the export's _LIPID_DRUG_FAMILIES and
  // the chatbot pack (CLAUDE.md §10 — the three surfaces must agree).
  ["Penghambat penyerapan kolesterol", "Ezetimib"],
  ["Pengikat asam empedu", "Kolestiramin (Cholestyramine)"],
];

const REFERENCES: [string, string][] = [
  [
    "Juknis CKG — KMK 84/2026 (skrining profil lipid pada CKG)",
    "https://kesprimkom.kemkes.go.id/assets/uploads/contents/others/2026kepmenkes084.pdf",
  ],
  [
    "Formularium Nasional — KMK 1199/2025 (daftar obat penurun lipid di puskesmas)",
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

export function LipidFormulaCard() {
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
            menjawab: <i>bagaimana profil lipid pasien saat skrining CKG?</i> Kolom
            Follow Up menjawab: <i>pada kontrol 3 bulanan setelahnya, apakah
            lemak darahnya sudah mencapai target?</i> Karena pertanyaannya berbeda,
            labelnya bisa berbeda — dan itu memang benar, bukan error.
          </div>
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Section title="1 · Siapa yang masuk daftar ini?">
              <p>
                Pasien masuk daftar jika punya kunjungan CKG di tahun itu{" "}
                <b>dan</b> hasil profil lipidnya memenuhi <b>salah satu</b> ambang
                berikut:
              </p>
              <ul className="list-disc space-y-0.5 pl-4">
                <li>
                  <b>Kolesterol Total ≥ 200 mg/dL</b> (200 sudah masuk)
                </li>
                <li>
                  <b>HDL &lt; 40 mg/dL</b> (40 belum masuk)
                </li>
                <li>
                  <b>LDL ≥ 130 mg/dL</b> (130 sudah masuk)
                </li>
                <li>
                  <b>Trigliserida &gt; 150 mg/dL</b> — perhatikan: <b>lebih dari</b>,
                  bukan &quot;150 ke atas&quot;. Tepat 150 mg/dL masih normal, 151
                  sudah masuk.
                </li>
              </ul>
              <p>
                Cukup satu terpenuhi. Pasien dengan seluruh hasil normal, atau yang
                tidak diperiksa lipidnya sama sekali, tidak ditampilkan.
              </p>
            </Section>

            <Section title="2 · Arti singkatan">
              <p>
                <b>Kolesterol Total</b> — jumlah seluruh kolesterol dalam darah.
              </p>
              <p>
                <b>LDL</b> — kolesterol &quot;jahat&quot;; makin tinggi makin
                berisiko.
              </p>
              <p>
                <b>HDL</b> — kolesterol &quot;baik&quot;; di sini <i>rendah</i> yang
                dianggap tidak normal, kebalikan dari tiga kolom lainnya.
              </p>
              <p>
                <b>Trigliserida</b> — lemak darah lain, ikut dinilai sebagai bagian
                profil lipid.
              </p>
              <p>Semua satuannya mg/dL. Urutan kolom mengikuti format dirjen: Kolesterol Total, LDL, HDL, Trigliserida.</p>
            </Section>

            <Section title="3 · Arti label Interpretasi (saat kunjungan CKG)">
              <p>
                <b>Dislipidemia</b>: ada <b>minimal satu</b> hasil yang melewati
                ambang di bagian 1. Semua baris di daftar ini berlabel Dislipidemia —
                memang itu syarat masuknya.
              </p>
              <p>
                <b>Normal</b>: profil lipid diperiksa dan tidak ada satu pun yang
                melewati ambang. Pasien seperti ini <i>tidak</i> muncul di daftar.
              </p>
              <p>
                <b>Kosong</b>: tidak ada satu pun nilai lipid yang terekam, jadi tidak
                bisa disimpulkan.
              </p>
              <p>
                Tidak ada kategori tengah di sini. Format dirjen hanya menetapkan satu
                ambang per pemeriksaan — tidak ada padanan &quot;Pre-Hipertensi&quot;
                atau &quot;Prediabetes&quot;.
              </p>
            </Section>

            <Section title="4 · Kolom Riwayat HT & Riwayat DM — dilaporkan, bukan penyaring">
              <p>
                Berbeda dengan Registri Hipertensi dan Registri Diabetes Melitus:
                di sini riwayat diagnosis <b>tidak</b> menentukan siapa yang masuk
                daftar, dan <b>tidak</b> memaksa label Interpretasi.
              </p>
              <p>
                Syarat masuk daftar murni dari hasil pengukuran. Jadi pasien dengan
                Riwayat HT = Ya tetapi profil lipidnya bersih tidak akan muncul, dan
                pasien dengan LDL 190 tetap muncul walau tidak punya riwayat HT/DM
                sama sekali.
              </p>
              <p>
                Kedua kolom itu tetap ditampilkan karena format dirjen memintanya
                sebagai <i>informasi</i> — bukan sebagai filter.
              </p>
            </Section>

            <Section title="5 · Cara baca Follow Up — kontrolnya per 3 bulan">
              <p>
                <b>Ini bedanya yang paling penting dengan registri DM.</b> Format
                dirjen menilai target &quot;pada kunjungan 3 bulan berikutnya&quot;,
                jadi kontrol di sini <b>triwulanan</b>, bukan bulanan.
              </p>
              <p>
                Bulan kontrol = bulan kunjungan CKG <b>+3, +6, +9, +12</b>. Contoh:
                skrining CKG bulan Februari → bulan kontrolnya Mei, Agustus, dan
                November.
              </p>
              <p>
                <b>Target tercapai</b>: Kolesterol Total &lt; 200 <i>dan</i> HDL ≥ 40{" "}
                <i>dan</i> LDL &lt; 130 <i>dan</i> Trigliserida ≤ 150 mg/dL — semuanya
                harus lolos.
              </p>
              <p>
                <b>Target tidak tercapai</b>: cukup <b>satu</b> yang melewati ambang
                (Kolesterol Total ≥ 200, HDL &lt; 40, LDL ≥ 130, atau Trigliserida
                &gt; 150).
              </p>
              <p>
                <b>Pasien Missed Visit</b> hanya muncul di <b>bulan kontrol</b> yang
                terlewat tanpa pemeriksaan. Bulan lain yang kosong dibiarkan{" "}
                <b>kosong begitu saja</b> — bukan berarti pasien absen, memang tidak
                ada kontrol yang dijadwalkan di bulan itu. Bulan kontrol yang belum
                tiba juga dibiarkan kosong.
              </p>
              <p>
                Kunjungan yang membawa hasil lipid tetap ditampilkan di bulannya
                masing-masing, walaupun bukan bulan kontrol. Kalau pasien datang
                beberapa kali dalam sebulan, semua kunjungannya ditampilkan dan
                dinilai sendiri-sendiri.
              </p>
            </Section>

            <Section title="6 · Kenapa banyak kolom Follow Up yang kosong?">
              <p>
                Karena pemeriksaan profil lipid <b>jarang dicatat di ePuskesmas</b>.
                Berbeda dengan tekanan darah yang hampir selalu diukur tiap kunjungan,
                lipid hanya tercatat pada sebagian kecil kunjungan.
              </p>
              <p>
                Di ASIK sendiri formulirnya memang dibatasi:{" "}
                <i>POCT Lipid Panel (khusus usia ≥ 40 tahun dan penyandang HT
                dan/atau DM)</i>. Jadi tidak semua peserta CKG diperiksa lipidnya.
              </p>
              <p>
                Kolom kosong berarti pemeriksaannya <b>tidak tercatat</b> — bukan
                kesalahan sistem. Justru inilah yang perlu diperbaiki: makin lengkap
                pencatatan profil lipid di ePuskesmas, makin berguna kertas kerja ini.
              </p>
            </Section>

            <Section title="7 · Kolom Jenis Obat — hanya obat dislipidemia">
              <p>
                Hanya obat penurun lemak darah yang ditampilkan, sesuai kolom dirjen
                &quot;List Obat Dislipidemia&quot;. Vitamin, antibiotik, obat darah
                tinggi, obat diabetes, dan obat lain sengaja tidak ditampilkan.
              </p>
              <ul className="list-disc space-y-0.5 pl-4">
                {DRUG_FAMILIES.map(([fam, drugs]) => (
                  <li key={fam}>
                    <b>{fam}</b>: {drugs}
                  </li>
                ))}
              </ul>
            </Section>

            <Section title="8 · Dari mana angkanya diambil?">
              <p>
                <b>ASIK (skrining CKG) adalah sumber utama</b> untuk identitas, empat
                nilai lipid, kedua kolom Riwayat, dan Jenis Obat. Nilai dari
                ePuskesmas dipakai untuk mengisi bagian yang kosong di ASIK — per
                kolom, bukan semua-atau-tidak.
              </p>
              <p>
                <b>Follow Up selalu dari ePuskesmas</b>, karena kunjungan setelah CKG
                dicatat di sana.
              </p>
              <p>
                Tanda kecil <b>ASIK</b> / <b>ePus</b> di panel detail menunjukkan
                sumber tiap nilai.
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
                <li>
                  Ambang syarat registri (Kolesterol Total ≥ 200, HDL &lt; 40, LDL ≥
                  130, Trigliserida &gt; 150 mg/dL), target kontrol 3 bulanan, dan
                  format registri: dokumen dirjen &quot;Register Sheet Pasien HT, DM,
                  Dislipidemia dan Obesitas&quot;, sheet &quot;Dislipidemia&quot;.
                </li>
              </ul>
            </Section>
          </div>
        </div>
      )}
    </div>
  );
}
