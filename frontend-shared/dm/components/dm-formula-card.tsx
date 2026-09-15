"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Calculator } from "lucide-react";

/** Collapsible "Cara Membaca" explainer for the Registri Diabetes Melitus.
 * Mirrors the "Formula & Logika" sheet in the Excel export
 * (backend/app/services/dm_registry_export.py) — keep both in sync, and keep
 * the chatbot pack chatbot/knowledge/registri-diabetes-melitus.md in sync too
 * (CLAUDE.md §10: these three surfaces must never contradict each other).
 * Wording is deliberately plain, non-technical Indonesian — read by puskesmas
 * staff. */

const DRUG_FAMILIES: [string, string][] = [
  ["Biguanid", "Metformin"],
  ["Sulfonilurea", "Glibenklamid, Glimepirid, Gliklazid, Glipizid, Glikuidon"],
  ["Penghambat alfa-glukosidase", "Akarbose"],
  ["Tiazolidindion", "Pioglitazon, Rosiglitazon"],
  ["Penghambat DPP-4", "Sitagliptin, Vildagliptin, Linagliptin, Saxagliptin, Alogliptin"],
  ["Penghambat SGLT-2", "Dapagliflozin, Empagliflozin, Kanagliflozin"],
  ["Agonis GLP-1", "Liraglutid, Semaglutid, Exenatid"],
  ["Insulin", "Semua sediaan insulin (Glargine, Aspart, Detemir, Novorapid, Lantus, dll.)"],
];

const REFERENCES: [string, string][] = [
  [
    "Juknis CKG — KMK 84/2026 (skrining gula darah pada CKG)",
    "https://kesprimkom.kemkes.go.id/assets/uploads/contents/others/2026kepmenkes084.pdf",
  ],
  [
    "Formularium Nasional — KMK 1199/2025 (daftar obat diabetes di puskesmas)",
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

export function DmFormulaCard() {
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
            menjawab: <i>berapa gula darah pasien saat skrining CKG?</i> Kolom Follow
            Up menjawab: <i>pada bulan-bulan setelahnya, apakah gula darahnya sudah
            mencapai target?</i> Karena pertanyaannya berbeda, labelnya bisa berbeda —
            dan itu memang benar, bukan error.
          </div>
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Section title="1 · Siapa yang masuk daftar ini?">
              <p>
                Pasien masuk daftar jika memenuhi <b>salah satu</b>:
              </p>
              <p>
                <b>(1) Sudah tercatat sebagai pasien DM</b> — ada diagnosis diabetes di
                ePuskesmas, atau pasien menjawab &quot;Ya&quot; saat ditanya &quot;pernah
                dinyatakan diabetes atau kencing manis oleh dokter?&quot; di skrining CKG
                → kolom Riwayat DM = Ya.
              </p>
              <p>
                <b>(2) Hasil gula darahnya memenuhi ambang diagnosis</b> — GDP 126 mg/dL
                ke atas, GD2PP 200 mg/dL ke atas, atau GDS ke-2 200 mg/dL ke atas.
              </p>
              <p>
                Pasien <b>Prediabetes</b> juga ikut ditampilkan supaya bisa dipantau
                lebih awal. Yang tidak ditampilkan: gula darah Normal <b>dan</b> tidak
                pernah didiagnosis diabetes.
              </p>
            </Section>

            <Section title="2 · Arti singkatan">
              <p>
                <b>GDS</b> — Gula Darah Sewaktu, diperiksa kapan saja tanpa puasa.
              </p>
              <p>
                <b>GDS 2</b> — pemeriksaan GDS <i>kedua</i>, untuk memastikan hasil GDS 1
                yang tinggi.
              </p>
              <p>
                <b>GDP</b> — Gula Darah Puasa (biasanya setelah puasa 8 jam).
              </p>
              <p>
                <b>GD2PP</b> — Gula Darah 2 jam setelah makan (Post Prandial).
              </p>
              <p>
                <b>HbA1C</b> — rata-rata gula darah ±3 bulan terakhir, dalam persen.
              </p>
            </Section>

            <Section title="3 · Arti label Interpretasi (saat kunjungan CKG)">
              <p>
                Kalau <b>Riwayat DM = Ya</b> → selalu &quot;Diabetes Melitus&quot;, berapa pun
                hasilnya hari itu. Diagnosis tidak hilang karena satu hasil ukur yang bagus.
              </p>
              <p>
                <b>Diabetes Melitus</b>: GDP ≥ 126, <i>atau</i> GD2PP ≥ 200, <i>atau</i>{" "}
                GDS 2 ≥ 200 mg/dL. Cukup salah satu.
              </p>
              <p>
                <b>Prediabetes</b>: GDP 100–125, <i>atau</i> GD2PP 140–199, <i>atau</i>{" "}
                GDS 1 140–199 mg/dL.
              </p>
              <p>
                <b>Normal</b>: di bawah ambang Prediabetes.
              </p>
            </Section>

            <Section title="4 · Kapan hasil dianggap tidak valid?">
              <p>
                <b>GD2PP tanpa GDP</b> — GD2PP hanya bisa dibaca kalau ada GDP-nya.
                Tanpa itu, angkanya tidak dipakai menyimpulkan.
              </p>
              <p>
                <b>GDS 2 tanpa GDS 1</b> — GDS 2 adalah konfirmasi; tanpa GDS 1 angkanya
                tidak dipakai menyimpulkan.
              </p>
              <p>
                Hasil lain yang sah tetap dipakai. Contoh: GDS 1 = 150 dan ada GD2PP tanpa
                GDP → GD2PP diabaikan, GDS 1 tetap dibaca → <b>Prediabetes</b>. Label{" "}
                <b>&quot;Tidak dapat diinterpretasikan&quot;</b> hanya muncul kalau tidak ada
                satu pun hasil yang sah.
              </p>
            </Section>

            <Section title="5 · Cara baca Follow Up">
              <p>
                Mulai <b>bulan setelah</b> bulan skrining CKG. Bulan skrining tidak
                diulang karena sudah ada di bagian hasil pemeriksaan.
              </p>
              <p>
                <b>Target tercapai</b>: HbA1C &lt; 7%, <i>atau</i> GDP 80–130,{" "}
                <i>atau</i> GD2PP &lt; 180 mg/dL.
              </p>
              <p>
                <b>Target tidak tercapai</b>: HbA1C ≥ 7%, <i>atau</i> GDP &gt; 130,{" "}
                <i>atau</i> GD2PP ≥ 180 mg/dL. GDP <b>di bawah 80</b> juga dihitung tidak
                tercapai — gula darah terlalu rendah (hipoglikemia) bukan kondisi
                terkendali.
              </p>
              <p>
                <b>Kolom GDS tidak menentukan status.</b> Format dirjen tidak menetapkan
                batas target untuk GDS, jadi kunjungan yang hanya punya GDS dibiarkan{" "}
                <b>kosong</b> — bukan berarti gagal.
              </p>
              <p>
                Bulan lewat tanpa pemeriksaan = <b>Pasien Missed Visit</b>. Bulan yang
                belum terjadi dibiarkan kosong. Kalau pasien datang beberapa kali dalam
                sebulan, semua kunjungannya ditampilkan.
              </p>
            </Section>

            <Section title="6 · Kenapa banyak kolom Follow Up yang kosong?">
              <p>
                Karena pemeriksaan gula darah <b>jarang dicatat di ePuskesmas</b>. Berbeda
                dengan tekanan darah yang hampir selalu diukur tiap kunjungan, gula darah
                hanya tercatat pada sebagian kecil kunjungan.
              </p>
              <p>
                Kolom kosong berarti pemeriksaannya <b>tidak tercatat</b> — bukan kesalahan
                sistem. Justru inilah yang perlu diperbaiki: makin lengkap pencatatan gula
                darah di ePuskesmas, makin berguna kertas kerja ini.
              </p>
              <p>
                <b>HbA1C paling sering kosong</b> — pemeriksaannya jarang tersedia di
                puskesmas. Kolomnya tetap disediakan sesuai format dirjen dan akan terisi
                otomatis begitu datanya masuk.
              </p>
            </Section>

            <Section title="7 · Kolom Jenis Obat — hanya obat diabetes">
              <p>
                Hanya obat diabetes yang ditampilkan, sesuai kolom dirjen
                &quot;List_obat_dm&quot;. Vitamin, antibiotik, obat darah tinggi, dan obat
                lain sengaja tidak ditampilkan.
              </p>
              <ul className="list-disc space-y-0.5 pl-4">
                {DRUG_FAMILIES.map(([fam, drugs]) => (
                  <li key={fam}>
                    <b>{fam}</b>: {drugs}
                  </li>
                ))}
              </ul>
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
                  Target pengendalian (HbA1C &lt; 7%, GDP 80–130, GD2PP &lt; 180) dan
                  format registri: dokumen dirjen &quot;Register Sheet Pasien HT, DM,
                  Dislipidemia dan Obesitas&quot;, sheet &quot;Diabetes Melitus&quot;.
                </li>
              </ul>
            </Section>
          </div>
        </div>
      )}
    </div>
  );
}
