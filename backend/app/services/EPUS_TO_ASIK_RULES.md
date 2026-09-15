# EPUS → ASIK Conversion Rules

Reference doc for `epus_to_asik.py`. Lists every rule the deterministic converter applies when turning a decrypted ePuskesmas patient blob into an ASIK CKG form-shaped dict. Use this to debug, audit, or extend the converter.

> Validated against 32 `matched` patients in local Postgres on 2026-04-29: **94 % categorical accuracy** (144 correct / 153 categorical comparisons; 9 self-report flips are real-world data drift, not converter bugs). Numeric drift (71 cases) reflects different visit timestamps, not conversion errors.
>
> **Form-name restructure 2026-05-08**: form names align with the CSV PROD list (`CKG vs ePus 2026.05.05.xlsx - Sheet1.csv`). See `.scratch/backend/app/services/EPUS_TO_ASIK_GAP_LIVE_2026-05-08.md` (archived) for the rename table. Re-run validation after this change before relying on the 94% number.

---

## 1. Patient demographics — required to emit anything

The converter reads `data_pasien` to derive **klaster** (which forms the patient is eligible for). If either field below is missing/unreadable, **the converter returns `{}`** (no forms).

| EPUS field | Used for | Accepted values |
|------------|----------|-----------------|
| `data_pasien."Jenis Kelamin"` | gender → form variant | `P` / `L` / `Perempuan` / `Laki-Laki` / `Wanita` / `Pria` (case-insensitive). Normalised to `Perempuan` / `Laki-laki`. |
| `data_pasien."Umur"` | age in years → form gating | First number-then-Tahun/Thn/T/Y. Examples: `"58 Tahun 1 Bulan 15 Hari"`, `"58 Thn 6 Bln 0 Hr"`, `"58 thn"`. |

---

## 2. Form-emission gating (klaster logic)

Form names below are the CSV PROD names (post-2026-05-08 restructure).

Forms always emitted (every adult/lansia patient):

- `Riwayat Hipertensi & Diabetes` — combined HT+DM parent radios + sistole/diastole + bulan-since-diagnosis
- `Skrining Gizi, Tekanan Darah, dan Gula Darah <Laki-laki|Perempuan>[ => 40 Tahun]` — combined per gender × age band. <40 carries BP+gula+gizi+IMT; ≥40 carries gula+gizi+IMT only (BP lives in `Riwayat HT & DM`)
- `Pemeriksaan PPOK (Skrining PUMA)` — only when `years >= 40`
- `Demografi Dewasa <Laki-Laki|Perempuan>` for `years < 60`, else `Demografi Lansia`
- `Skrining Telinga dan Mata (18-39 tahun)` for `years < 40`, else `Skrining Telinga dan Mata (=>40 tahun)`
- `Faktor Risiko Tuberkulosis Dewasa & Lansia`
- `Tuberkulosis - Skrining Nakes Dewasa & Lansia`
- `Pemeriksaan HIV`
- `Pemeriksaan Sifilis`
- `Perilaku Merokok - Dewasa Lansia`
- `Perilaku Merokok - Pemeriksaan Kadar CO`
- `Tingkat Aktivitas Fisik`

Always-emitted shells (no EPUS source today):

`Pemeriksaan Tuberkulosis (Dewasa & Lansia)`, `Layanan Penyakit Tropis Terabaikan`, `Pemeriksaan Hepatitis`, `Pemeriksaan Fibrosis/Sirosis Hati`, `Hati`, `Kesehatan Jiwa`, `Prediksi Risiko Jantung dan Stroke`, `Riwayat Imunisasi HPV`.

Age-gated additions:

| Threshold | Forms added |
|-----------|-------------|
| `18 <= years <= 24` | `Skrining Gigi - Dewasa 18-24 tahun` (shell) |
| `years >= 25` | `Skrining Gigi - Dewasa >=25 tahun` (shell) |
| `years >= 40` | `Skrining Laboratorium =>40 thn <Laki-laki|Perempuan> Gula Darah, Fungsi Ginjal, Hati, Profil Lipid` (shell — combines lipid + ginjal + hati + GDP cascade) |
| `years >= 45` AND gender=Laki-laki | `Skrining Kanker Paru (Laki-laki =>45 tahun)` (populated), `Skrining Kanker Paru (Laki-Laki >=45 Tahun) - Penapisan Risiko Kanker Paru` (populated) |
| `years >= 45` (any gender) | `Kanker Usus` (populated — APCS), `Skrining Kanker Usus (TL APCS)` (shell) |
| `years >= 60` | `Skrining Geriatri (Usia >=60 thn/lansia)` (shell — combined Lansia battery: Barthel, Mini-Cog, AD-8, MNA-SF, SPPB, GDS-15) |

Disease-gated additions (use **clinical** flag — see §3):

| Condition | Form added |
|-----------|------------|
| HT or DM (clinical) AND years <45 | `Skrining Jantung (Pemeriksaan EKG - hanya penyandang HIPERTENSI)` (shell) |

For `years >= 45` the EKG form is always emitted regardless of HT/DM, because live ASIK PROD shows it for the entire 45+ cluster.

Gender + age window:

| Condition | Forms added |
|-----------|-------------|
| `Perempuan AND years >= 30 AND Hasil IVA != null` | `Skrining Kanker Leher Rahim` |
| `Perempuan AND years >= 30 AND Hasil Sanadis != null` | `Skrining Kanker Payudara` |
| `Perempuan AND years >= 30` | `Hasil Pemeriksaan HPV-DNA` (shell), `Kanker Leher Rahim` (shell) |
| `Perempuan` (any age) | `Pemeriksaan Calon Pengantin Perempuan` (shell), `Riwayat Imunisasi Tetanus(Status T)` (shell) |

---

## 3. Two-tier disease detection

The converter computes **two** flag sets per patient:

### `self_report` — patient's own answer at EPUS visit

Source: `tabs.PTM.fields."Riwayat PTM pada Diri Sendiri"`. Each field normalised via `_yatidak()` (Ya/Iya/Y vs Tidak/Tdk/No/N).

| Flag | Field |
|------|-------|
| `diabetes` | `Penyakit Diabetes` |
| `hipertensi` | `Penyakit Hipertensi` |
| `jantung_kronis` | `Penyakit Jantung` |
| `paru_kronis` | `Penyakit Asma` |
| `kanker` | `Penyakit Kanker` |
| `stroke` | `Penyakit Stroke` |
| `dislipidemia` | `Kolesterol Tinggi` |

### `clinical` — OR-union of three sources

`clinical[X] = self_report[X]  OR  Tandai Kronis flag  OR  ICDX prefix scan`

Sources:

1. `self_report[X]` (above).
2. `tabs.Diagnosa.fields."Buat Baru Diagnosa"."Tandai Penyakit Kronis"."<key>"`.
3. ICDX prefix scan over `penyakit_khusus[*].ICDX`:

| Flag | ICDX prefixes |
|------|---------------|
| `diabetes` | `E10` `E11` `E12` `E13` `E14` |
| `hipertensi` | `I10` `I11` `I12` `I13` `I15` |
| `jantung_kronis` | `I20` `I21` `I22` `I23` `I24` `I25` `I50` |
| `paru_kronis` | `J40` `J41` `J42` `J43` `J44` `J45` `J47` |
| `kanker` | `C00`–`C99` (full block) |
| `stroke` | (no ICDX scan; Tandai-Kronis + Riwayat only) |
| `dislipidemia` | `E78` (any subcode) |
| `tb` | `A15`–`A19` |
| `hiv` | `B20`–`B24` |
| `syphilis` | `A50`–`A53` |

### Which flag drives what

| Use | Flag set | Why |
|-----|----------|-----|
| ASIK Q1 *Apakah Anda pernah dinyatakan…?* | **clinical** | Question = "has a doctor ever told you?" → ICDX-coded diagnosis is most authoritative. Patient denial at ASIK time is real but unpredictable. |
| Form gating (EKG / Lipid / Ginjal eligibility) | **clinical** | Form availability depends on clinical truth, not patient memory. |
| Conditional reveal trigger (e.g. *Sudah Berapa Bulan…*) | derived from parent radio = clinical | Same as above — child only emitted when parent = Ya. |

`self_report` is computed and exposed but the parent-radio mappers do **not** use it. It is kept available for future UI features (e.g. "EPUS doctor view vs patient view").

---

## 4. Per-form field rules

### Riwayat Hipertensi & Diabetes

Combined HT+DM parent radio form per CSV PROD 2026-05-05.

| ASIK field | EPUS source | Transform |
|-----------|-------------|-----------|
| `Apakah Anda pernah dinyatakan tekanan darah tinggi?` | `clinical.hipertensi` | bool → `"Ya"` / `"Tidak"` |
| `Apakah Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?` | `clinical.diabetes` | bool → `"Ya"` / `"Tidak"` |
| `Tekanan Darah Sistolik` | `tabs.Anamnesa.fields."Periksa Fisik".Sistole` | `_num()` |
| `Tekanan darah diastolik` | `tabs.Anamnesa.fields."Periksa Fisik".Diastole` | `_num()` |
| `Sudah Berapa Bulan Anda Didiagnosis Hipertensi Oleh Dokter?` | — | Emitted `null` only when HT parent = `Ya`. EPUS doesn't capture months-since-diagnosis. |
| `Sudah Berapa Bulan Anda Didiagnosis Diabetes Melitus Oleh Dokter?` | — | Emitted `null` only when DM parent = `Ya`. |

### Skrining Gizi, Tekanan Darah, dan Gula Darah `<gender>`[ ` => 40 Tahun`]

Combined per gender × age band. Variant suffix ` => 40 Tahun` for ≥40.

For **<40**, the form carries HT+DM radios + sistole/diastole on top of the gula+gizi block. For **≥40**, the BP/HT-radio block lives only in `Riwayat HT & DM`.

| ASIK field | EPUS source | Transform |
|-----------|-------------|-----------|
| `Apakah Anda pernah dinyatakan tekanan darah tinggi?` *(only <40)* | `clinical.hipertensi` | bool → `"Ya"` / `"Tidak"` |
| `Apakah Anda pernah dinyatakan diabetes ...?` | `clinical.diabetes` | bool → `"Ya"` / `"Tidak"` |
| `Tekanan Darah Sistolik` *(only <40)* | `tabs.Anamnesa.fields."Periksa Fisik".Sistole` | `_num()` |
| `Tekanan darah diastolik` *(only <40)* | `tabs.Anamnesa.fields."Periksa Fisik".Diastole` | `_num()` |
| `Gula Darah Puasa (GDP) (mg/dl)` | `tabs.PTM.fields.Pemeriksaan."Pemeriksaan Gula Darah Puasa"` | `_num()` |
| `Gula Darah 2 Jam PP (mg/dl)` | `tabs.PTM.fields.Pemeriksaan."Pemeriksaan Gula Darah 2 Jam PP"` | `_num()` |
| `Gula Darah Sewaktu (GDS) (mg/dl)` | `tabs.PTM.fields.Pemeriksaan."Pemeriksaan Gula"` | Used **only** when GDP is null. |
| `Berat Badan (Kg)` | `tabs.Anamnesa.fields."Periksa Fisik"."Berat Badan"` (fallback `tabs.PTM.fields."Tekanan Darah & IMT"."Berat Badan"`) | `_num()` |
| `Pengukuran Tinggi Badan (cm)` | `Anamnesa..."Tinggi Badan"` (fallback PTM) | `_num()` |
| `Pengukuran Lingkar Perut` | `Anamnesa..."Lingkar Perut"` (fallback `PTM > Pemeriksaan > Lingkar Perut`) | `_num()` |
| `Index Massa Tubuh` | EPUS-computed `Hasil IMT` (preferred) OR computed via `_imt_bucket(BB, TB)` | enum: `Underweight (<18.5)` / `Normal (18.5 - 22.9)` / `Overweight (23 - 24.9)` / `Obesitas I (25 - 29.9)` / `Obesitas II (>=30)` |
| `Sudah Berapa Bulan ... Hipertensi/DM` | — | `null` when parent = Ya |

GDS-2 cascade fields (`GDS Kedua`, etc.) are **never** emitted — they only fire on ASIK when `GDS-1 ≥ 140`, and EPUS doesn't carry them.

### Pemeriksaan PPOK (Skrining PUMA)

Form gated on `years >= 40`.

| ASIK field | EPUS source | Transform |
|-----------|-------------|-----------|
| `Apakah anda sedang/mempunyai riwayat merokok?` | `tabs.PTM.fields."Faktor Risiko".Merokok` | `_smoking_to_asik()`: contains `tidak` → `"Tidak"`; contains `aktif`/`merokok`/`perokok` → `"Iya"` |
| `Usia - skor PUMA` | `data_pasien.Umur` | derived: `<40 (0 poin)` / `40-59 (1 poin)` / `>=60 (2 poin)` |
| `Apakah Anda pernah merasa napas pendek…` | `tabs.PTM.fields."Faktor Risiko"."<full long question>"` | `_yatidak()` |
| `Apakah Anda biasanya mempunyai dahak…` | same → matching long question | `_yatidak()` |
| `Apakah Anda biasanya batuk saat sedang tidak menderita selesma/flu?` | same | `_yatidak()` |
| `Apakah Dokter atau tenaga medis lainnya pernah meminta…spirometri…` | same | `_yatidak()` |
| `Jika Perokok Aktif, berapa bungkus per tahun?` | `tabs.PTM.fields."Faktor Risiko"."Pack Year"` (preferred) OR `Rata-rata Jumlah Rokok × Lama Merokok dalam Tahun / 20` | Emitted **only** when smoking parent = `"Iya"`. Bucketed: `<20`, `20-30`, `>30`. Null when both EPUS Pack Year and the rokok×lama inputs are missing. |
| `Hasil Skor Kuesioner PUMA` | `tabs.PTM.fields."Faktor Risiko"."Total Skoring Puma"` | `Suspek PPOK (skor >=7)` if score >=7 else `Bukan PPOK (skor <7)` |

> EPUS rarely fills the four detail PUMA Yes/No questions in standard puskesmas flow — expect mostly `null` here even when the converter is correct.

### Demografi Dewasa Perempuan / Laki-Laki / Lansia

| Variant | ASIK field | EPUS source | Notes |
|---------|-----------|-------------|-------|
| Dewasa Perempuan | `Apakah Anda sedang hamil?` | `tabs.Anamnesa.fields."Periksa Fisik"."Status Hamil"` | `_yatidak()` |
| Dewasa Laki-Laki | (no fields filled) | — | Form is emitted as empty `{}` shell |
| Lansia (`years >= 60`) | (no fields filled) | — | Empty `{}` shell — replaces Dewasa for this age band |

> ASIK Demografi also asks `Status Perkawinan` and `Penyandang disabilitas?`. EPUS has no source. Left blank.

### Skrining Telinga dan Mata (18-39 / =>40 tahun)

Variant by age. EPUS-FLAT layout (live audit 2026-05-08): `Gangguan Penglihatan > Mata Kanan/Kiri` (no Kelainan Refraksi sub-block) and `Gangguan Pendengaran > Telinga Kanan/Kiri` (no Curiga Tuli Kongenital sub-block).

| ASIK field | EPUS source | Transform |
|-----------|-------------|-----------|
| `Apa hasil skrining tajam penglihatan?` | `tabs.PTM.fields."Gangguan Penglihatan".Mata Kanan/Kiri` | OR-union: either side `Ya` → `Curiga gangguan penglihatan (visus <6/12)`. Both `Tidak` → `Normal (visus 6/6 - 6/12)`. |
| `Hasil pemeriksaan tajam pendengaran` | `tabs.PTM.fields."Gangguan Pendengaran".Telinga Kanan/Kiri` | OR-union: `Curiga gangguan pendengaran` / `Normal` |
| `Apa Hasil Pemeriksaan Telinga Luar (serumen impaksi)?` | same | `Ada serumen impaksi` / `Tidak ada serumen impaksi` |
| `Hasil pemeriksaan pupil` *(only ≥40)* | `tabs.PTM.fields."Gangguan Penglihatan".Mata Kanan/Kiri` | OR-union: `Curiga Katarak` / `Normal` |

### Skrining Kanker Leher Rahim *(Perempuan, years ≥ 30, only if Hasil IVA non-null)*

Replaces legacy `Pemeriksaan Inspekulo dan IVA` form name.

| ASIK field | EPUS source | Transform |
|-----------|-------------|-----------|
| `Pemeriksaan Inspekulo` | `tabs.PTM.fields."Pemeriksaan IVA dan Sadanis"."Hasil IVA"` | `Negatif` → `Normal`; `Positif`/`Curiga` → `Curiga kanker` |
| `Pemeriksaan Inspeksi Visual Asam Asetat (IVA)` | same | `Negatif` / `Positif` |

### Skrining Kanker Payudara *(Perempuan, years ≥ 30, only if Hasil Sanadis non-null)*

| ASIK field | EPUS source | Transform |
|-----------|-------------|-----------|
| `Pemeriksaan yang dilakukan` | constant `SADANIS` (EPUS never does USG) | — |
| `Hasil pemeriksaan SADANIS` | `tabs.PTM.fields."Pemeriksaan IVA dan Sadanis"."Hasil Sanadis"` | `Tidak ada benjolan` → `Normal`; `Curiga kanker` → `Curiga kanker`; `Benjolan/Ditemukan` → `Ditemukan benjolan` |

### Perilaku Merokok - Dewasa Lansia

Renamed from `Perilaku Merokok`. Significantly expanded per CSV.

| ASIK field | EPUS source | Transform |
|-----------|-------------|-----------|
| `Apakah Anda merokok dalam setahun terakhir ini?` | `tabs.PTM.fields."Faktor Risiko".Merokok` | active → `Ya`; ex-smoker / non-smoker → `Tidak` |
| `Sudah berapa tahun Anda merokok?` | `tabs.PTM.fields."Faktor Risiko"."Lama Merokok dalam Tahun"` | `_num()`. Active smokers only. |
| `Biasanya, berapa batang rokok yang Anda hisap dalam sehari?` | `tabs.PTM.fields."Faktor Risiko"."Rata-rata Jumlah Rokok"` | `_num()`. Active smokers only. |
| `Apakah Anda pernah merokok sebelumnya?` | `tabs.PTM.fields."Faktor Risiko".Merokok` | ex-smoker keywords (`eks`, `mantan`, `pernah`) → `Ya`; non-smoker → `Tidak` |
| `Berapa lama (tahun) Anda merokok sebelumnya?` | `tabs.PTM.fields."Faktor Risiko"."Lama Merokok dalam Tahun"` | Ex-smokers only. |

### Perilaku Merokok - Pemeriksaan Kadar CO

| ASIK field | EPUS source | Transform |
|-----------|-------------|-----------|
| `Kadar CO Pernapasan` | `tabs.PTM.fields."Form UBM".CAR` | `_num()` |

### Tingkat Aktivitas Fisik

| ASIK field | EPUS source | Transform |
|-----------|-------------|-----------|
| `Apakah Anda rutin melakukan olahraga ...?` | `tabs.PTM.fields."Faktor Risiko"."Kurang Aktivitas Fisik"` | inverted Y/N: EPUS `Ya` (kurang aktif) → ASIK `Tidak` (rutin olahraga) |

### Tuberkulosis - Skrining Nakes Dewasa & Lansia

| ASIK field | EPUS source | Transform |
|-----------|-------------|-----------|
| `Apakah Anda pernah atau sedang mengalami batuk yang tidak sembuh-sembuh?` | `clinical.tb` (ICDX A15-A19) | `Ya, lebih dari 2 minggu` when TB ICDX present |
| `Hasil Pemeriksaan TCM` | `tabs."TB Paru".fields."Tipe Diagnosis ..."."Sebelum pengobatan hasil tes cepat"` | substring match: `negatif` → `Mtb not detected (Neg)`; `rif res` → `Mtb detected, Rif resistance detected`; `rif sen`/`sensitif` → `Mtb detected, Rif resistance not detected` |
| `Hasil Pemeriksaan BTA` | `tabs."TB Paru".fields."Tipe Diagnosis ..."."Sebelum pengobatan hasil mikroskopis"` | `positif` → `Positif`; `negatif` → `Negatif` |

### Skrining Kanker Paru (Laki-laki =>45 tahun)

Renamed from `Skrining Kanker Paru (Usia =>45 thn)`. Gender now in form name.

| ASIK field | EPUS source | Transform |
|-----------|-------------|-----------|
| `Jenis Kelamin - skor APCS` | gender (derived) | `Laki-Laki (1 poin)` / `Perempuan (0 poin)` |
| `Usia - skor APCS` | years (derived) | `<50 tahun (0 poin)` / `50-69 tahun (2 poin)` / `>=70 tahun (3 poin)` |
| `Apakah pernah didiagnosis/menderita kanker?` | `clinical.kanker` | `Memiliki diagnosis kanker <5 tahun yang lalu` (defensive — EPUS no diagnosis date) / `Tidak pernah didiagnosis menderita kanker` |
| `Apakah ada keluarga ... kanker sebelumnya?` | `tabs.PTM.fields."Riwayat PTM pada Keluarga"."Penyakit Kanker"` | `Memiliki keluarga yang terdiagnosis kanker lain` / `Tidak ada keluarga ...` |
| `Riwayat merokok/paparan asap rokok` | `tabs.PTM.fields."Faktor Risiko".Merokok` | `Tidak pernah merokok` / `Perokok aktif (dalam 1 tahun ini masih merokok)` |
| `Pernah didiagnosis penyakit paru kronik?` | `clinical.tb` / `clinical.paru_kronis` / self_report Asma | `Pernah didiagnosis tuberkulosis (TBC)` / `Pernah didiagnosis penyakit kronis lain (PPOK, ILD, dll)` / `Tidak pernah didiagnosis penyakit paru kronik` |

### Skrining Kanker Paru (Laki-Laki >=45 Tahun) - Penapisan Risiko Kanker Paru

Renamed from `Penapisan Risiko Kanker Paru`. Same fields, longer form name.

### Kanker Usus

`years >= 45` (any gender), populated form (no longer shell).

| ASIK field | EPUS source | Transform |
|-----------|-------------|-----------|
| `Apakah ada anggota keluarga ... kanker kolorektal atau kanker usus?` | `tabs.PTM.fields."Riwayat PTM pada Keluarga"."Penyakit Kanker"` | `_yatidak()` — defensive: EPUS doesn't distinguish kolorektal from any cancer |
| `Apakah Anda merokok?` | `tabs.PTM.fields."Faktor Risiko".Merokok` | `Ya` / `Tidak` |
| `Jenis Kelamin - skor APCS` | gender (derived) | same as kanker paru |
| `Usia - skor APCS` | years (derived) | same as kanker paru |
| `Skor APCS` | sum of weights from above 4 fields | `Risiko Rendah (0-1 poin)` / `Risiko Sedang (2-3 poin)` / `Risiko Tinggi (4-7 poin)` |

### Empty-shell forms (always emitted, fields never filled)

These forms appear in the output dict so the frontend can render them as "eligible but no EPUS source", but every field is `null` / form value is `{}`:

- `Pemeriksaan Tuberkulosis (Dewasa & Lansia)`
- `Layanan Penyakit Tropis Terabaikan` *(was: Pemeriksaan Penyakit Frambusia / Kusta / Skabies)*
- `Pemeriksaan Hepatitis`
- `Pemeriksaan Fibrosis/Sirosis Hati`
- `Hati`
- `Kesehatan Jiwa`
- `Prediksi Risiko Jantung dan Stroke`
- `Riwayat Imunisasi HPV`
- `Skrining Gigi - Dewasa 18-24 tahun` *(18 ≤ years ≤ 24)*
- `Skrining Gigi - Dewasa >=25 tahun` *(years ≥ 25)*
- `Skrining Laboratorium =>40 thn <Laki-laki|Perempuan> Gula Darah, Fungsi Ginjal, Hati, Profil Lipid` *(years ≥ 40)*
- `Skrining Kanker Usus (TL APCS)` *(years ≥ 45)*
- `Skrining Jantung (Pemeriksaan EKG - hanya penyandang HIPERTENSI)` *(years ≥ 45 OR clinical HT/DM)*
- `Skrining Geriatri (Usia >=60 thn/lansia)` *(years ≥ 60 — combined Lansia battery)*
- `Hasil Pemeriksaan HPV-DNA`, `Kanker Leher Rahim` *(Perempuan, years ≥ 30)*
- `Pemeriksaan Calon Pengantin Perempuan`, `Riwayat Imunisasi Tetanus(Status T)` *(Perempuan, all ages)*
---

## 5. Conditional-reveal handling

ASIK SurveyJS uses inline `visibleIf` to hide follow-up fields until a parent answer matches the trigger. The converter mirrors this:

| Form | Parent → Trigger | Child(ren) emitted only when trigger matches |
|------|------------------|---------------------------------------------|
| Riwayat Hipertensi & Diabetes | `Apakah Anda pernah dinyatakan tekanan darah tinggi?` = `Ya` | `Sudah Berapa Bulan Anda Didiagnosis Hipertensi Oleh Dokter?` |
| Riwayat Hipertensi & Diabetes | `Apakah Anda pernah dinyatakan diabetes…` = `Ya` | `Sudah Berapa Bulan Anda Didiagnosis Diabetes Melitus Oleh Dokter?` |
| Skrining Gizi, ... `<gender>` (<40) | same HT/DM radios → bulan-since-diagnosis fields | (duplicated) |
| Skrining Gizi, ... `<gender> => 40 Tahun` | DM radio = `Ya` → `Sudah Berapa Bulan ... Diabetes` | (no HT radio in this band) |
| Pemeriksaan PPOK (Skrining PUMA) | `Apakah anda sedang/mempunyai riwayat merokok?` = `Iya` | `Jika Perokok Aktif, berapa bungkus per tahun?` |

Other ASIK conditional reveals exist in the live form (e.g. GDS-2 / GDP / 2-jam PP cascade fires on `GDS-1 >= 140`; Skrining Telinga & Mata reveals refraction follow-ups on non-Normal visus). The converter does **not** emit them because EPUS has no reliable source — they are left for manual entry on the ASIK side.

---

## 6. Value-coercion helpers

| Helper | Behaviour |
|--------|-----------|
| `_yatidak(v, ya="Ya", tidak="Tidak")` | Lowercase + strip. `ya/iya/y` → `ya`; `tidak/tdk/no/n` → `tidak`; anything else → `None`. Custom pair via args (e.g. PPOK uses `Iya` not `Ya`). |
| `_num(v)` | Strip, replace `,` with `.`, return `int` if no decimal, `float` otherwise, `None` on parse failure. |
| `_smoking_to_asik(v)` | Substring scan: contains `tidak` → `Tidak`; contains `aktif`/`merokok`/`perokok` → `Iya`; else `None`. |
| `_years_from_umur(v)` | Regex `^\s*(\d+)\s*(Tahun|Thn|T|Y)` (case-insensitive). |
| `_gender_norm(v)` | Lowercase + strip. `p`/`pr`/`pere*`/`wani*` → `Perempuan`. `l`/`lk`/`laki*`/`pria*` → `Laki-laki`. |
| `_imt_bucket(bb, tb)` | `(imt_value, bucket_label)`. Asia-Pacific BMI cutoffs: <18.5 / 18.5-22.9 / 23-24.9 / 25-29.9 / >=30. |
| `_bp_bucket(s, d)` | JNC-7 enum: `Hipotensi` (<90/<60), `Normal` (<120/<80), `Pre-Hipertensi` (<140/<90), `Hipertensi grade 1/2/3 (Krisis)`, etc. |
| `_gds_bucket(v)` | `Hipoglikemi` (<70), `Normal` (70-139), `Prediabetes` (140-199), `Hiperglikemi` (>=200). |
| `_apcs_jk(g)` / `_apcs_usia(y)` | APCS demographics enum strings (3-way age, 2-way gender). |

---

## 7. Determinism guarantees

- **No randomness.** No `random`, no `time`, no `uuid`, no shuffling.
- **No I/O.** No DB, no HTTP, no filesystem reads inside the converter.
- **Stable iteration order.** Output dict insertion order mirrors source-code order; Python ≥ 3.7 preserves dict insertion order.
- **Idempotent.** `epus_to_asik(blob) == epus_to_asik(blob)` byte-for-byte. Locked in by the `--replay` test in `testing-epus-asik/compare_converter.py`.

---

## 8. Known unmapped surfaces (intentional)

EPUS data the converter ignores, with reasons:

| EPUS path | Why ignored |
|-----------|------------|
| `tabs.Anamnesa.fields.Anamnesa."Keluhan Utama"` (free text) | ASIK has no narrative destination; LLM merge prompt can use it. |
| `tabs.Anamnesa.fields."Riwayat Penyakit".RPS / RPD / RPK` (free text) | Same as above — narrative, no ASIK home. |
| `tabs.Laboratorium` | Lab values (HDL/LDL/SGOT/kreatinin/etc.) are present but row layout varies — needs a separate parser. Currently emitted as empty form shells (see §4). |
| `tabs.Odontogram` | Tooth-by-tooth state; ASIK Skrining Karies/Periodontal is binary counts. Needs a separate parser. |
| `tabs.Konseling HIV` / `tabs.Periksa IMS` | ASIK has rapid-test enums; EPUS layout pending audit. |
| `tabs.Caten` (catin / pre-marriage) | Different program. ASIK Catin forms emitted as shells. |

ASIK forms with no EPUS source at all (kept as empty shells in output for the frontend's information):

- Demografi `Penyandang disabilitas?`, `Apabila belum menikah/cerai, ada rencana menikah?` (CSV ADJ — no EPUS source)
- `Hati` (entire form — 12 Q all MISS in CSV)
- `Layanan Penyakit Tropis Terabaikan`
- `Prediksi Risiko Jantung dan Stroke`
- `Riwayat Imunisasi HPV`
- `Skrining Geriatri (Usia >=60 thn/lansia)` — combined Lansia battery (Barthel, AD-8, Mini Cog, MNA-SF, SPPB, GDS-15) — geriatric instruments not run in standard puskesmas flow.
- `Skrining Laboratorium ...` combined lab form — most numeric fields (HDL/LDL/SGOT/Kreatinin/Ureum/eLFG/Albumin urin/UACR) are in `tabs.Laboratorium` but row layout varies; needs a separate parser before un-shelling.

---

## 9. Validation status

Last validated 2026-04-29 against 32 matched patients: 94 % categorical accuracy (144/153).

> **Form-name restructure 2026-05-08 invalidates this number.** Comparison harness `testing-epus-asik/compare_converter.py` matches converter output against a live ASIK record by form name; the rename and combined-form restructure means the matcher must be re-keyed before re-running. Re-validation is pending.

Pre-restructure baseline (kept here for reference):

| Metric | Count | Note |
|--------|-------|------|
| correct (predicted == actual) | 144 | exact match after numeric tolerance |
| both_null | 191 | converter null, ASIK null — agreement |
| predicted_null | 40 | converter blank, ASIK filled — under-fill, EPUS gap |
| actual_null | 3 | converter filled, ASIK blank — overshoot |
| **mismatch_numeric** | **71** | BP/BB/lingkar drift = different visit timestamps. Not a bug. |
| **mismatch_categorical** | **9** | Patient self-report flips between EPUS & ASIK visits. Irreducible. |
| form_missing_in_actual | 42 | converter emitted form, real ASIK record had no entry for it |
| form_unexpected_in_actual | 531 | real ASIK has forms with NO EPUS source (see §8) — out of scope |

---

## 10. How to extend

1. **New ASIK form to emit**: add a `_map_<thing>(epus, ...)` helper, call it from `epus_to_asik(...)` under the appropriate gating (age / gender / disease / always).
2. **New EPUS source path**: pull via `(epus.get("tabs") or {}).get("<TabName>") or {}` chain. Always defensive — never assume keys exist.
3. **New conditional reveal**: add a parent-key check around the child key insertion (see Tekanan Darah / PPOK PUMA patterns).
4. **New value coercer**: drop next to `_yatidak` / `_num` / `_smoking_to_asik` and write a docstring describing accepted variants.
5. **Update validation**: re-run `python3 testing-epus-asik/compare_converter.py` and `--replay`; commit `asik_form_fields.json` only if the live ASIK schema changed.

---

## 11. Where to find the rest

- Converter source: `backend/app/services/epus_to_asik.py`
- HTTP endpoint that exposes the converter: `POST /patients/{id}/asik-preview` → `backend/app/api/routes/patients.py`
- Frontend tab that consumes the endpoint: `frontend-internal/components/patients/epus-to-asik-detail.tsx` (and `scraped-data-toggle.tsx` for tab gating)
- LLM merge prompt that uses converter output as a hint for `matched` patients: `backend/app/prompts/merge_patient.md`
- Validation harness: `testing-epus-asik/compare_converter.py`
- Live ASIK form schema dump: `testing-epus-asik/asik_form_fields.json` (52 forms × 168 fields, audited via agent-browser)
