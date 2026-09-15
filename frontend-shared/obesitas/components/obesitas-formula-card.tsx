"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Calculator } from "lucide-react";

/** Collapsible "Cara Membaca" explainer for the Registri Obesitas.
 * Mirrors the "Formula & Logika" sheet in the Excel export
 * (backend/app/services/obesitas_registry_export.py) — keep both in sync, and
 * keep the chatbot pack for this page in sync too (CLAUDE.md §10: these three
 * surfaces must never contradict each other).
 * Every claim here is read off backend/app/services/obesitas_registry_scan.py —
 * do not write a rule from general medical knowledge, the code wins.
 * Wording is deliberately plain, non-technical Indonesian — read by puskesmas
 * staff. */

const REFERENCES: [string, string][] = [
  [
    "Juknis CKG — KMK 84/2026 (pengukuran berat & tinggi badan pada CKG)",
    "https://kesprimkom.kemkes.go.id/assets/uploads/contents/others/2026kepmenkes084.pdf",
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

export function ObesitasFormulaCard() {
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
            menjawab: <i>seberapa berat pasien saat skrining CKG?</i> Kolom Follow
            Up menjawab: <i>pada kontrol 3–6 bulan setelahnya, apakah berat
            badannya sudah turun cukup banyak?</i> Karena pertanyaannya berbeda,
            labelnya juga berbeda — dan itu memang benar, bukan error.
          </div>
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Section title="1 · Siapa yang masuk daftar ini?">
              <p>
                Pasien masuk daftar jika punya kunjungan CKG di tahun itu{" "}
                <b>dan</b> IMT-nya mencapai ambang berikut:
              </p>
              <ul className="list-disc space-y-0.5 pl-4">
                <li>
                  <b>Obesitas I</b> — IMT 25 sampai di bawah 30 (25 sudah masuk)
                </li>
                <li>
                  <b>Obesitas II</b> — IMT 30 ke atas
                </li>
              </ul>
              <p>
                Pasien dengan IMT di bawah 25 tidak ditampilkan. Begitu juga pasien
                yang berat <i>atau</i> tinggi badannya tidak tercatat — tanpa
                keduanya IMT tidak bisa dihitung.
              </p>
              <p>
                Format dirjen untuk registri ini <b>berlaku mulai 1 Januari 2026</b>.
                Tahun sebelumnya tetap bisa dipilih, tapi pencatatannya biasanya
                jauh lebih sedikit.
              </p>
            </Section>

            <Section title="2 · Bagaimana IMT dihitung?">
              <p>
                <b>IMT = berat badan (kg) ÷ kuadrat tinggi badan (meter).</b>{" "}
                Contoh: BB 78 kg, TB 165 cm = 1,65 m → 78 ÷ (1,65 × 1,65) ={" "}
                <b>28,7</b>. Dibulatkan 1 angka di belakang koma.
              </p>
              <p>
                Angka IMT ini <b>dihitung sendiri oleh sistem</b>, bukan diambil
                dari ASIK maupun ePuskesmas: ASIK hanya menyimpan berat dan tinggi
                badan untuk dewasa, dan ePuskesmas hanya menyimpan kategori
                teksnya. Di file Excel kolom IMT juga berupa rumus hidup — kalau BB
                atau TB dikoreksi, IMT dan labelnya ikut berubah.
              </p>
              <p>
                Pembulatan dilakukan <i>sebelum</i> label ditentukan, supaya label
                selalu cocok dengan angka yang tertulis di sebelahnya.
              </p>
            </Section>

            <Section title="3 · Arti label Interpretasi (saat kunjungan CKG)">
              <p>
                <b>Obesitas I</b>: IMT 25 sampai di bawah 30 kg/m².
              </p>
              <p>
                <b>Obesitas II</b>: IMT 30 kg/m² ke atas.
              </p>
              <p>
                <b>Normal</b>: sudah diukur, tapi IMT-nya masih di bawah 25. Pasien
                seperti ini <i>tidak</i> muncul di daftar. Label ini hanya berarti
                &quot;di bawah ambang obesitas&quot; — format dirjen tidak membagi
                lagi wilayah di bawah 25, jadi kurus dan berat badan lebih tidak
                dibedakan di sini.
              </p>
              <p>
                <b>Kosong</b>: berat atau tinggi badan tidak tercatat, jadi tidak
                bisa disimpulkan.
              </p>
            </Section>

            <Section title="4 · Kolom Riwayat HT & Riwayat DM — dilaporkan, bukan penyaring">
              <p>
                Sama seperti Registri Dislipidemia dan berbeda dengan Registri
                Hipertensi / Diabetes Melitus: di sini riwayat diagnosis{" "}
                <b>tidak</b> menentukan siapa yang masuk daftar, dan <b>tidak</b>{" "}
                memaksa label Interpretasi.
              </p>
              <p>
                Syarat masuk daftar murni dari hasil pengukuran. Pasien dengan IMT
                32 tetap muncul walau tidak punya riwayat HT/DM sama sekali, dan
                pasien dengan Riwayat HT = Ya tapi IMT 22 tidak muncul.
              </p>
              <p>
                Kedua kolom itu tetap ditampilkan karena format dirjen memintanya
                sebagai <i>informasi</i> — bukan sebagai filter.
              </p>
            </Section>

            <Section title="5 · Cara baca Follow Up — kontrolnya 3–6 bulan">
              <p>
                Format dirjen menilai target &quot;penurunan BB pada 3-6 bulan
                berikutnya&quot;, jadi bulan kontrolnya adalah bulan ke-<b>3, 4, 5,
                dan 6</b> setelah bulan skrining CKG. Contoh: skrining bulan Januari
                → bulan kontrolnya April, Mei, Juni, dan Juli.
              </p>
              <p>
                <b>Target tercapai</b>: berat badan turun <b>lebih dari 5%</b>{" "}
                dibanding berat saat skrining CKG. Perhatikan: penurunan tepat 5,0%{" "}
                <i>belum</i> dihitung tercapai; harus lebih dari itu.
              </p>
              <p>
                <b>Target tidak tercapai</b>: penurunan 5% atau kurang — termasuk
                kalau beratnya tetap atau justru naik.
              </p>
              <p>
                Pembandingnya <b>selalu berat saat skrining CKG</b>, bukan berat
                kunjungan sebelumnya. Jadi persentasenya bisa dibandingkan antar
                bulan. Kolom <b>Δ BB vs CKG</b> di panel detail menampilkan angka
                itu langsung.
              </p>
              <p>
                <b>Pasien Missed Visit</b> hanya muncul di <b>bulan kontrol</b>{" "}
                (bulan ke-3 s/d ke-6) yang terlewat tanpa pemeriksaan. Bulan ke-1,
                ke-2, dan bulan ke-7 ke atas dibiarkan <b>kosong begitu saja</b> —
                bukan berarti pasien absen, memang tidak ada kontrol yang
                dijadwalkan di bulan itu. Bulan kontrol yang belum tiba juga
                dibiarkan kosong.
              </p>
              <p>
                Kunjungan yang membawa hasil timbang tetap ditampilkan di bulannya
                masing-masing, walaupun bukan bulan kontrol. Kunjungan yang hanya
                mencatat tinggi badan juga ditampilkan, tapi Interpretasinya
                dibiarkan kosong — tanpa berat badan tidak ada penurunan yang bisa
                dihitung.
              </p>
            </Section>

            <Section title="6 · Kenapa banyak kolom Follow Up yang kosong?">
              <p>
                Karena berat badan <b>jarang ditimbang ulang di kunjungan biasa</b>.
                Saat skrining CKG hampir semua peserta diukur BB dan TB-nya, tapi
                pada kunjungan berobat berikutnya sering tidak dicatat lagi di
                ePuskesmas.
              </p>
              <p>
                Kolom kosong berarti pengukurannya <b>tidak tercatat</b> — bukan
                kesalahan sistem. Justru inilah yang perlu diperbaiki: makin rutin
                berat badan ditimbang dan dicatat, makin berguna kertas kerja ini.
              </p>
            </Section>

            <Section title="7 · Dari mana angkanya diambil?">
              <p>
                <b>ASIK (skrining CKG) adalah sumber utama</b> untuk identitas,
                berat badan, tinggi badan, dan kedua kolom Riwayat. Nilai dari
                ePuskesmas dipakai untuk mengisi bagian yang kosong di ASIK — per
                kolom, bukan semua-atau-tidak.
              </p>
              <p>
                <b>Follow Up selalu dari ePuskesmas</b>, karena kunjungan setelah
                CKG dicatat di sana.
              </p>
              <p>
                Angka yang tidak masuk akal <b>diabaikan</b>: berat di luar 20–400
                kg atau tinggi di luar 80–250 cm dianggap salah ketik dan
                diperlakukan sebagai &quot;tidak terukur&quot; — bukan dipaksa masuk
                ke perhitungan.
              </p>
              <p>
                Tanda kecil <b>ASIK</b> / <b>ePus</b> di panel detail menunjukkan
                sumber tiap nilai. IMT tidak punya tanda sumber karena dihitung
                sendiri.
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
                  Ambang Obesitas I (IMT 25) dan Obesitas II (IMT 30), target
                  penurunan BB &gt;5%, jadwal kontrol 3–6 bulan, catatan
                  &quot;cut off mulai 1 Jan 2026&quot;, dan format registri:
                  dokumen dirjen &quot;Register Sheet Pasien HT, DM, Dislipidemia
                  dan Obesitas&quot;, sheet &quot;Obesitas&quot;.
                </li>
              </ul>
            </Section>
          </div>
        </div>
      )}
    </div>
  );
}
