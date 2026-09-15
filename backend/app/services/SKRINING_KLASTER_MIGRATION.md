# Migrasi Sumber Jawaban ASIK → Halaman Skrining Klaster

> Spec revisi **converter** (`backend/app/services/epus_to_asik.py`) + verifikasi scraper.
> Keputusan PKM: **default ambil jawaban dari halaman Skrining Klaster**; fallback ke modul (Anamnesa/PTM/Kartu Bayi) hanya bila tak ada; sisanya memang tak ada di EPUS.
> Berlaku untuk **semua puskesmas** (converter & scraper shared; getlist `key` region-stable). Referensi field: PKM Tebet (config terlengkap).
> Sumber: sandingan `Lengkap from PDF` vs `Hasil PKM Tebet` (Excel) + struktur form live ePus (getlist + form kosong, read-only).

## Status implementasi (update 2026-08-12)

**SUDAH — converter `epus_to_asik.py` klaster-primary + scraper Vue-extract, verified:**

*Batch 1 (nilai bersih, sumber sudah di-scrape):*
| Repoint | ASIK field | Sumber klaster (`detail`/`record`) |
|---|---|---|
| Hipertensi riwayat | `Apakah Anda pernah dinyatakan tekanan darah tinggi?` | `hipertensi.riwayat_pribadi` (Ya/Tidak) |
| DM riwayat | `Apakah Anda pernah dinyatakan diabetes…?` | `diabetes_melitus.anamnesis[Riwayat Pribadi Diabetes Melitus]` |
| GDS/GDP/GD2PP | `Gula Darah Sewaktu/Puasa/2 Jam PP (mg/dl)` | `diabetes_melitus.hasil_gds/hasil_gdp/hasil_gd2pp` |
| PPOK PUMA (5 Q) | (5 pertanyaan PPOK) | `puma.*` — **inversi prioritas** (dulu PTM primary) |
| EKG Jantung | `Hasil Pemeriksaan EKG` | `resiko_penyakit_jantung.SkriningJantung[ekg_v2]` — **inversi** |

*Batch 2 (butuh re-scrape; faktor_risiko/fungsi_ginjal via Vue-extract baru):*
| Repoint | ASIK field | Sumber klaster |
|---|---|---|
| Merokok setahun | `Perilaku Merokok > Apakah Anda merokok dalam setahun terakhir ini?` | `faktor_risiko q::…merokok dalam setahun…` (id 53) |
| Paparan asap rokok (BARU) | `Perilaku Merokok > …terpapar asap rokok…dari orang lain…?` | `faktor_risiko q::…terpapar asap rokok…` (id 59) |
| Kreatinin / Ureum | `Skrining Fungsi Ginjal <g> > Hasil Pemeriksaan Kreatinin/Ureum` | `fungsi_ginjal q::kreatinin / q::ureum` |
| Kel. kanker usus + merokok | `Faktor Risiko Kanker Usus` (2 Q) | `kolorektal.riwayat_kanker_kolorektal / riwayat_merokok` |

*Batch 3 (Telinga & Mata — map 2-opsi):*
| Repoint | ASIK field | Sumber klaster |
|---|---|---|
| Tajam penglihatan | `Skrining Telinga dan Mata <g> > Apa hasil skrining tajam penglihatan?` | `penglihatan.tajam_kiri/tajam_kanan` (sisi abnormal → Curiga) |
| Tajam pendengaran | `… > Hasil pemeriksaan tajam pendengaran` | `skrining_indra_pendengaran.bisikan_telinga_kiri/kanan` |

**Scraper** (`scrapers/epus/patient_scraper.py`): `_extract_js_answers` kini mengekstrak
Vue `viewData.formulir/skriningDetail` → `q::<pertanyaan>` (mirror PHQ-4). Diverifikasi
deterministik (`scratchpad/verify_extract_unit.py`): kedua shape jalan, PHQ-4 tetap utuh.

Test: `backend/tests/test_epus_to_asik_klaster.py` (**10 kasus, hijau**). Payudara + PHQ-4 sudah klaster-primary sejak sebelumnya.
**Validasi data nyata SUDAH** (`scratchpad/validate_rescrape.py`, jaksel 2026-08-12): login →
scraper `_fetch_skrining/_attach_skrining_detail` (jalankan `_extract_js_answers` baru) → `epus_to_asik`.
Terbukti pada pasien nyata: faktor_risiko→Perilaku Merokok, fungsi_ginjal→Kreatinin=1.01/Ureum=33,
DM→GDP=113/GD2PP=145, kolorektal→Kanker Usus. **Belum**: restart Celery + re-merge `force_remerge` di DB (§9/§12) — langkah runtime.

*Batch 4 (SUDAH — nilai berkode, recon value→label 2026-08-12):*
| Repoint | ASIK field | Sumber (kode→opsi) |
|---|---|---|
| Serviks inspekulo | `Pemeriksaan Inspekulo dan IVA > Pemeriksaan Inspekulo` | `serviks.inspekulo` 0=Normal / 1=Curiga kanker |
| Serviks IVA | `… > Pemeriksaan Inspeksi Visual Asam Asetat (IVA)` | `serviks.hasil_iva` 1=Negatif / 0,2=Positif |
| Hubungan seksual (BARU) | `Kanker Leher Rahim > Apakah pernah melakukan hubungan intim/seksual?` | `serviks.seksual` 1=Ya / 0=Tidak |

**#1 Breadcrumbs: SUDAH** — `EPUS_BREADCRUMBS` diupdate ke `skrining_klaster > … (fallback PTM > …)` untuk semua field Batch 1–5.
**#2 Recon nilai berkode: SUDAH** (`scratchpad/recon2_coded.py`). Peta value→label lengkap tertangkap:
- `skriningkankerparu` (kode 1–4): `diagnosis_kanker` 1=Tidak pernah/2=Ya<5th/3=Ya>5th; `keluarga_kanker` 1=Tidak ada/2=kanker lain/3=kanker paru; `riwayat_merokok` 1=Tidak/2=pasif/3=bekas<15th/4=aktif; `riwayat_bekerja`/`tempat_tinggal_berpolusi`/`rumah_tidak_sehat` 1=Tidak/2=ragu/3=Ya; `diagnosis_paru_kronik` 1=Tidak/2=PPOK/3=TBC.
- `imunisasi_tetanus` 0=Belum…5=T5.

*Batch 5 (SUDAH — 2026-08-12, keputusan PKM):*
| Repoint / BARU | ASIK field | Sumber (kode/label→opsi) |
|---|---|---|
| Kanker Paru (7 field) | `Skrining Kanker Paru (Usia =>45 thn)` (semua 7 Q) | `skriningkankerparu.*` kode 1–4 → opsi ASIK (klaster-primary, 4 field lingkungan **BARU**) |
| Penapisan Kanker Paru | `Penapisan Risiko Kanker Paru` (5 Q Y/N) | derive dari `riwayat_merokok`/`keluarga_kanker`/`diagnosis_paru_kronik` (pasif→terpapar **BARU**) |
| Imunisasi tetanus | `Riwayat Imunisasi Tetanus…Catin > minimal 2 kali?` | `skrining_imunisasi_dewasa.imunisasi_tetanus` **T2+→"minimal dua kali"; <T2 (Belum/T1) kosong** (opsi ASIK tak punya "Belum"; nakes isi) |
| Pupil/Katarak | `Skrining Telinga dan Mata (=>40 thn) > Hasil pemeriksaan pupil` | `penglihatan.pemeriksaan_pupil_kiri/kanan` Positif→Curiga Katarak / Negatif→Normal |
| Mini-Cog | `Penurunan Kognitif - Tindak Lanjut (Mini Cog-Clock Draw)` (clock+recall) | `mini_cog.gambar_jam`→Benar/Salah, `mini_cog.kata_yang_tepat_dua`→Benar N/semua/Tidak dapat |

Test: **8 kasus baru** di `test_epus_to_asik_klaster.py` (total **18 hijau**).

*Batch 6 (SUDAH — 2026-08-12, opsi ASIK dirakit dari `asik_form_mapping.json`):*
| BARU | ASIK form | Sumber (opsi EPUS→opsi ASIK) |
|---|---|---|
| SPPB (5 item) | `Mobilisasi - Pemeriksaan Lanjutan (SPPB)` (>=60) | `sppb` detail `SkriningSppb[<field>]` = **teks opsi terpilih** → opsi ASIK byte-exact (fold punktuasi via `_norm_opt`; en-dash/koma vs hyphen/titik). `berdampingan`/`tandem` tak punya "Tidak dilakukan" di ASIK → kosong. |
| MNA-SF (6 item) | `Skrining Malnutrisi - Pemeriksaan Lanjutan (MNA-SF)` (>=60) | `pengkajian_nutrisi` detail (nama polos) = teks opsi → opsi ASIK (wording beda utk mobilitas/neuropsik/IMT → map eksplisit). **2 param bolong**: asupan (PPM131) & penurunan BB (PPM134) tak punya opsi "normal/tidak ada penurunan" di repo → nilai "normal" EPUS **kosong** (nakes isi). Lingkar-betis tak ada di EPUS (IMT-only). |

⚠️ **Opsi ASIK Batch 6 = Padanan-Excel/JSON, BELUM diverifikasi vs DOM `<select>` ASIK live** (SurveyJS render lazy; scraper baca hanya nilai terpilih). Semua **0-data** (PKM Tebet belum isi instrumen lanjutan) → **safe-fail**: nilai tak match = tak emit (bukan korupsi), byte-mismatch = tak sync. **Langkah finishing tertunda:** byte-check vs DOM live (manual browser buka dropdown / patch scraper enumerasi `select.options[].text`) saat ada pasien lansia.

Test: **6 kasus baru** di `test_epus_to_asik_klaster.py` (total **24 hijau**).

**#3 geriatri — temuan (block sebagian):** form "Pemeriksaan Lanjutan" lansia memecah tiap item jadi
**input live utama + pseudo-Q `SKILAS Lanjutan-*` non-live** (`live_kind:null`) yang menampung opsi
overflow, dan opsi dropdown live **tak lengkap ter-capture** di `asik_form_mapping.json` (JS-rendered).
- **gds** → form depresi-lanjutan `live_kind:null` (tak fillable); 2 item depresi live SUDAH via `_map_skilas`. **Tak ada yang ditambah.**
- **mini_cog** → opsi radio lengkap ter-capture → **DIIMPLEMENTASI** (Batch 5). *(Asumsi: recall = `kata_yang_tepat_dua`; detail = label; 0-data → safe-fail ke kosong.)*
- **sppb / pengkajian_nutrisi (MNA-SF)** → **DIIMPLEMENTASI (Batch 6)**: opsi ASIK dirakit dari `asik_form_mapping.json` (opsi utama + sibling `SKILAS Lanjutan-*` yang berbagi `parameter_codes` = opsi dropdown yang sama). SPPB lengkap; MNA-SF 6/8 param — 2 param (asupan/penurunan-BB) bolong opsi "normal". **Belum byte-verified vs DOM live** (finishing tertunda).

**Sisa (butuh keputusan / recon lanjutan):**
- **sppb / pengkajian_nutrisi**: opsi ASIK Batch 6 **belum byte-verified vs `<select>` DOM live** — byte-check saat ada pasien lansia (manual browser / patch scraper). 2 opsi "normal" MNA-SF genuinely tak ada di repo.
- **imunisasi**: value 0/T1 saat ini KOSONG (tak ada opsi "Belum" di ASIK). Bila mau T1→"satu kali", tinggal bilang.

**BELUM (batch berikut) — butuh pemetaan opsi ASIK atau recon nilai-berkode:**
- **Perlu map label→opsi ASIK** (nilai sudah label, browser tak wajib): `penglihatan` (tajam+pupil), `skrining_indra_pendengaran` (tajam pendengaran/serumen), `gds` (4Q), `mini_cog`, `gejala_tbc` per-gejala.
- **Nilai berkode "1/2/3" → perlu recon value→label (browser)**: `skriningkankerparu`, `skrining_resiko_kanker_serviks`, `skrining_imunisasi_dewasa` (SUDAH Batch 5). `sppb`/`pengkajian_nutrisi` ternyata **label langsung** (bukan kode) → SUDAH Batch 6.

**Koreksi model sumber (penting):** getlist `klaster` record = **ringkasan** saja
(`skor`/`kesimpulan`/`klasifikasi_ht`/`hasil_skrining`/`total_skor`). Jawaban **per-item**
(riwayat_pribadi, sistole, hasil_gds, tajam_kiri, per-gejala, dst.) ada di **halaman `/edit`**
→ scraper simpan sebagai `detail` (keyed by input-name), digabung `_skrining_index`.
Diverifikasi live via `tools/skrining_inventory.py` (jaksel, 25 pasien done, 2026-08-12).

**Confirmed `detail` keys (siap dipetakan):** hipertensi, diabetes_melitus, penglihatan
(tajam_kiri/kanan, pemeriksaan_pupil_*, mata_luar), puma, payudara (record `kesimpulan`),
skrining_phq_4 (`q::*`), kolorektal, resiko_stroke, thalasemia, anemia, obesitas,
skriningkankerparu, skrining_resiko_kanker_serviks, gds, mini_cog, skilas, adl, pasien_kb.

**BLOCKED — hasil recon (jaksel, 400 pasien di-scan 2026-08-12):** sebab "detail kosong"
ada DUA: (1) **mekanisme JS baru** yang belum di-extract scraper, atau (2) **data langka**
(form dikonfigurasi tapi **0 pasien** mengisinya di PKM ini). Ini beda penting: yang (2)
tidak bisa dipetakan/diverifikasi sekarang tanpa mengarang.

| Form | Mekanisme edit-page | Gap scraper? | Ada data (400 pts) | Aksi |
|---|---|---|---|---|
| `faktor_risiko` (Grup B, 4Q) | Vue `const viewData={formulir[], skriningDetail[]}` | **YA** — mekanisme baru di `_extract_js_answers` | dewasa ✓ (2127671) | ubah scraper → mapper → **re-scrape** |
| `fungsi_ginjal` (Grup B, 2Q) | **sama** shape Vue | **YA** (mekanisme sama) | dewasa ✓ (2127781/2127823) | idem — Ureum/Kreatinin/e-LFG |
| `skrining_indra_pendengaran` (Grup A, 3Q) | jQuery `.prop("checked")` | **TIDAK** — sudah ditangani `_extract_js_answers` #2 | **0 dewasa** (hanya anak) | mapper converter siap; nunggu data nyata |
| `catin` (Grup B, 3Q) | (kemungkinan Vue) | ? | **0 done** | tunggu instans done |
| `skrining_kesehatan_gigi_dewasa`, `skrining_imunisasi_dewasa` | ? | ? | **0 done** | data langka — jangan dipetakan spekulatif |
| Geriatri: `sppb`,`pengkajian_nutrisi` | select (teks opsi) | tidak | **0 done** | **mapper SIAP (Batch 6)** — opsi ASIK Excel-sourced, belum byte-verified vs DOM live; nunggu data |
| Geriatri: `rapuh`,`abbreviated`,`skrining_kesehatan_gigi_lansia` | ? | ? | **0 done** | idem (PKM belum isi instrumen lanjutan) |
| `resiko_penyakit_jantung` (EKG) | ? | ? | **0 done** | inversi EKG sudah ada; jarang terpicu |
| `gejala_tbc` per-gejala | radio (server-render) | tidak | done ada, tapi semua "Bukan terduga" → gejala tak ter-`checked` | butuh pasien terduga TB |

**Mekanisme viewData `formulir/skriningDetail`** (faktor_risiko/fungsi_ginjal — beda dari
PHQ-4 yang pakai `pertanyaan[].questions[]`): jawaban tersimpan =
`skriningDetail[].skrining_jawaban.jawaban` (radio) atau `.jawaban_freetext` (teks), di-join
ke `formulir[]` via `skrining_pertanyaan_id`. Pertanyaan CKG ADA persis: id 53 "Apakah Anda
merokok dalam setahun terakhir ini?", id 59 "…terpapar asap rokok…dari orang lain dalam
sebulan terakhir?". Data mentah: `scratchpad/skrining_inventory_jaksel.json`,
`recon_blocked_found.json`.

## Ringkasan angka (278 pertanyaan ASIK)
| Bucket | Jml | Aksi |
|---|--:|---|
| 🟢 Sudah benar (green, path sama) | 69 | — |
| 🟢 ADL + SKILAS (green, relabel kosmetik) | 19 | — (converter sudah `skrining_klaster>adl/skilas`) |
| ⬜ Tidak ada di EPUS (uncolored/"x") | 91 | biarkan kosong (nakes isi) |
| 🔴🟡 **REVISI ke skrining klaster** | **83** | 48 repoint + **35 BARU** (dulu kosong) |

## Arsitektur (feasibility)
- **Scraper sudah menangkap semua**: `POST /klaster_siklushidup/{pid}/getlist` menyimpan tiap screening (`records` + `edit_html` untuk yang *done*) ke `epus['skrining_klaster'][key]`.
- Revisi **hampir seluruhnya di converter**: baca `skr[key]` (via `_skrining_index`) sebagai **primary**, modul jadi fallback.
- **Caveat scraper**: `edit_html` hanya diambil utk form *done* → data historis perlu **re-scrape** setelah PKM mulai mengisi. Beberapa form **Vue-rendered** (`faktor_risiko`,`fungsi_ginjal`,`catin`) → nilainya hanya dari `records` getlist / `_extract_js_answers`.

## GRUP A — Balik prioritas (converter sudah baca key-nya)

### `gejala_tbc` — e-Puskesmas - Formulir Skrining Gejala TBC dan Penyakit Pernapasan Lainnya - Buat Baru
- **route** `/skrining/tbc`  ·  **converter fn**: _map_faktor_risiko_tb, _cough_duration, _map_pemeriksaan_tuberkulosis  ·  _extend kids→dewasa + field gejala baru_
- **7 pertanyaan ASIK** dipindah ke sini (4 BARU / 3 repoint)
- **Field live (37)**: `nama-pasien (input/text)`, `no-rekam-medis (input/number)`, `tanggal-lahir (input/text)`, `nik (input/text)`, `jenis_kelamin (input/text)`, `pekerjaan (input/text)`, `no_hp (input/text)`, `alamat (input/text)`, `berat_badan (input/number)`, `tinggi_badan (input/number)`, `imt (input/number)`, `data_imt (input/text)`, `cara_ukur (input/text)`, `kategori_imt (input/text)`, `riwayat_kontak_tbc (Ya/Tidak)`, `batuk_2_minggu_lebih (Ya/Tidak)`, `metode_sputum (TCM (Tes Cepat Molekuler)/BTA (Basil Tahan Asam))`, `hasil_sputum (Tidak terdeteksi TB/TB tanpa resistensi rifampisin/TB dengan resistensi rifampisin (RR-TB)/Negatif (Tidak ditemukan basil tahan asam))`, `tandai_semua_faktor_risiko (Tandai "Ya"/Tandai "Tidak")`, `pernah_terdiagnosa (Ya/Tidak)`, `kapan (input/text)`, `berobat_tidak_tuntas (Ya/Tidak)`, `malnutrisi (Ya/Tidak)`, `merokok (Ya/Tidak)`, `riwayat_kencing_manis (Ya/Tidak)`, `odhiv (Ya/Tidak)`, `lansia (Ya/Tidak)`, `hamil (Ya/Tidak)`, `wbp (Ya/Tidak)`, `tinggal_wilayah_kumuh (Ya/Tidak)`, `abnormalitas_tbc (Abnormalitas TBC/Abnormalitas Bukan TBC/Normal)`, `tandai_semua_gejala (Ya/Tidak)`, `batuk (Ya/Tidak)`, `bb_turun (Ya/Tidak)`, `demam (Ya/Tidak)`, `berkeringat (Ya/Tidak)`, `gejala_penyakit_pernapasan_lainnya (input/text)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Apakah anda ada kontak dengan pasien Tuberkulosis (TBC | Balita | TB Paru > Data Register Terduga TB | ↻ |
| Apakah anda ada kontak dengan pasien Tuberkulosis (TBC)? | Dws/Lansia | TB Paru > Data Register Terduga TB > Kriteri | ↻ |
| Metode Pemeriksaan (untuk terduga TB) | Dws/Lansia | — | 🆕 |
| Apakah Anda pernah atau sedang mengalami batuk yang tidak se | Dws/Lansia | penyakit_khusus.ICDX (A15-A19) / Anamnesa >  | ↻ |
| Apakah berat badan Anda turun tanpa penyebab jelas/BB tidak  | Dws/Lansia | — | 🆕 |
| Apakah Anda mengalami demam hilang timbul tanpa sebab yang j | Dws/Lansia | — | 🆕 |
| Apakah Anda mengalami berkeringat di malam hari tanpa kegiat | Dws/Lansia | — | 🆕 |

### `puma` — e-Puskesmas - Skrining PPOK dengan Kuesioner PUMA - Buat Baru
- **route** `/skriningpuma`  ·  **converter fn**: _map_ppok_puma, _puma_screening_answers  ·  _jadikan primary (kini fallback PTM)_
- **5 pertanyaan ASIK** dipindah ke sini (0 BARU / 5 repoint)
- **Field live (27)**: `jenis_kelamin (Perempuan/Laki-laki)`, `usia (40 - 49 tahun/50 - 59 tahun/> 60 tahun)`, `pernah_merokok (Perokok aktif (dalam 1 tahun ini masih merokok)/Perokok/bekas perokok berhenti <10 tahun lalu/Tidak pernah merokok)`, `jumlah_rokok (< 20 bungkus per tahun: Skor 0/20-30 bungkus per tahun: Skor 1/> 30 bungkus per tahun: Skor 2)`, `status_merokok (Merokok/Tidak Merokok)`, `napas_pendek (Ya/Tidak)`, `dahak (Ya/Tidak)`, `batuk (Ya/Tidak)`, `pemeriksaan_fungsi_paru (Ya/Tidak)`, `keluhan [select: Batuk kering, Rasa berat di dada, Sesak nafas, Batuk berdahak]`, `wawancara_1 (Ya/Tidak)`, `wawancara_2 (Ya/Tidak)`, `pink_puffer (Ada pink puffer/Tidak ada pink puffer)`, `pursed_lips_breathing (Ada pernapasan pursed lips breathing/Tidak ada pernapasan pursed lips breathing)`, `otot_bantu_napas (Ya/Tidak)`, `sela_iga (Ada pelebaran sela iga/Tidak ada pelebaran sela iga)`, `barrel_chest (Ada barrel chest/Tidak ada barrel chest)`, `hipersonor (Ada hipersonor/Tidak ada hipersonor)`, `vesikular (Normal breathing/Suara nafas vesikular meningkat/Suara nafas vesikular melemah)`, `ronki_mengi (Ada ronki atau mengi/Tidak ada ronki atau mengi)`, `ekspirasi (Ada ekspirasi memanjang/Tidak ada ekspirasi memanjang)`, `spirometri (Selesai/Tidak Selesai)`, `hasil_spirometri [select: Normal, Restriksi ringan, Restriksi sedang, Restriksi berat]`, `kv (input/number)`, `kvp_prediksi (input/number)`, `vep1_prediksi (input/number)`, `rasio_vep1_kvp (input/number)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Apakah anda sedang/mempunyai riwayat merokok? | Dws/Lansia | PTM > Faktor Risiko > Merokok | ↻ |
| Apakah Anda pernah merasa napas pendek ketika berjalan lebih | Dws/Lansia | PTM > Faktor Risiko > napas pendek | ↻ |
| Apakah Anda biasanya mempunyai dahak dari paru atau kesulita | Dws/Lansia | PTM > Faktor Risiko > dahak | ↻ |
| Apakah Anda biasanya batuk saat sedang tidak menderita seles | Dws/Lansia | PTM > Faktor Risiko > batuk | ↻ |
| Apakah Dokter/tenaga medis pernah meminta Anda melakukan spi | Dws/Lansia | PTM > Faktor Risiko > spirometri | ↻ |

### `skrining_phq_4` — e-Puskesmas - Skrining Kesehatan Jiwa Dewasa dan Lansia (PHQ-4)
- **route** `/skriningkesehatanjiwadewasalansia`  ·  **converter fn**: _map_kesehatan_jiwa  ·  _sudah primary — verifikasi_
- **4 pertanyaan ASIK** dipindah ke sini (0 BARU / 4 repoint)
- **Field live (4)**: `tidak-sama-sekali (Tidak sama sekali)`, `kurang-dari-satu (Kurang dari 1 (satu) minggu)`, `lebih-dari-satu (Lebih dari 1 (satu) minggu)`, `hampir-setiap-hari (Hampir setiap hari)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Dalam 2 minggu terakhir, seberapa sering anda kurang/tidak b | Dws/Lansia | skrining_klaster > skrining_phq_4 > PHQ-2 it | ↻ |
| Dalam 2 minggu terakhir, seberapa sering anda merasa murung, | Dws/Lansia | skrining_klaster > skrining_phq_4 > PHQ-2 it | ↻ |
| Dalam 2 minggu terakhir, seberapa sering anda merasa gugup,  | Dws/Lansia | skrining_klaster > skrining_phq_4 > GAD-2 it | ↻ |
| Dalam 2 minggu terakhir, seberapa sering anda tidak mampu me | Dws/Lansia | skrining_klaster > skrining_phq_4 > GAD-2 it | ↻ |

### `skrining_indra_pendengaran` — e-Puskesmas - Skrining Indra Pendengaran - Buat Baru
- **route** `/skriningindrapendengaran`  ·  **converter fn**: _map_telinga_mata_fields, _telinga_mata_balita  ·  _extend balita→dewasa_
- **3 pertanyaan ASIK** dipindah ke sini (0 BARU / 3 repoint)
- **Field live (18)**: `kiri (Ya/Tidak)`, `kanan (Ya/Tidak)`, `rujuk (Rujuk/Tidak Rujuk)`, `curiga_telinga_kiri (Ya/Tidak)`, `curiga_telinga_kanan (Ya/Tidak)`, `curiga_rujuk (Rujuk/Tidak Rujuk)`, `pemeriksaan_telinga_kiri (Ya/Tidak)`, `pemeriksaan_telinga_kanan (Ya/Tidak)`, `pemeriksaan_rujuk (Rujuk/Tidak Rujuk)`, `omsk_telinga_kiri (Ya/Tidak)`, `omsk_telinga_kanan (Ya/Tidak)`, `omsk_rujuk (Rujuk/Tidak Rujuk)`, `presbikusis_telinga_kiri (Ya/Tidak)`, `presbikusis_telinga_kanan (Ya/Tidak)`, `bisikan_telinga_kiri (Normal/Gangguan pendengaran)`, `bisikan_telinga_kanan (Normal/Gangguan pendengaran)`, `otoskop_kiri (Normal/Gangguan Pendengaran)`, `otoskop_kanan (Normal/Gangguan Pendengaran)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Apa Hasil Pemeriksaan Telinga Luar (serumen impaksi)? | Dws/Lansia | PTM > Gangguan Pendengaran > Serumen Telinga | ↻ |
| Apa Hasil Pemeriksaan Telinga Luar (infeksi telinga)? | Dws/Lansia | PTM > Gangguan Pendengaran > Congek Telinga  | ↻ |
| Hasil pemeriksaan tajam pendengaran | Dws/Lansia | PTM > Gangguan Pendengaran > Congek + Tuli K | ↻ |

### `penglihatan` — e-Puskesmas - Skrining Kesehatan Penglihatan
- **route** `/skriningkesehatanpenglihatan`  ·  **converter fn**: _map_telinga_mata_fields, _telinga_mata_balita  ·  _extend balita→dewasa_
- **2 pertanyaan ASIK** dipindah ke sini (0 BARU / 2 repoint)
- **Field live (23)**: `mata_luar (Normal/Tidak Sehat)`, `jenis_pemeriksaan_mata (E tumbling/Uncorrected Snellen Chart)`, `tajam_kiri (Normal (6/6 - 6/12)/Kelainan Refraksi Sedang (< 6/12 - 6/18)/Kelainan Refraksi Berat (< 6/18 - 6/60)/low vision (6/60 - 3/60))`, `tajam_kanan (Normal (6/6 - 6/12)/Kelainan Refraksi Sedang (< 6/12 - 6/18)/Kelainan Refraksi Berat (< 6/18 - 6/60)/low vision (6/60 - 3/60))`, `pemeriksaan_visus_rabun_dekat_kiri (Ya/Tidak)`, `pemeriksaan_visus_rabun_dekat_kanan (Ya/Tidak)`, `buta_warna_kiri (Ya/Tidak)`, `buta_warna_kanan (Ya/Tidak)`, `kacamata (Ya/Tidak)`, `gangguan_refraksi_kiri (Ya/Tidak)`, `gangguan_refraksi_kanan (Ya/Tidak)`, `kelainan_organik[] (input/checkbox)`, `katarak_kiri (Ya/Tidak)`, `katarak_kanan (Ya/Tidak)`, `pinhole_kiri (Visus membaik: visus 6/6 - 6/12/Visus tidak membaik: visus < 6/12 - < 3/60)`, `pinhole_kanan (Visus membaik: visus 6/6 - 6/12/Visus tidak membaik: visus < 6/12 - < 3/60)`, `pemeriksaan_pupil_kiri (Positif/Negatif)`, `pemeriksaan_pupil_kanan (Positif/Negatif)`, `glaukoma_kiri (Ya/Tidak)`, `glaukoma_kanan (Ya/Tidak)`, `retinopati_kiri (Ya/Tidak)`, `retinopati_kanan (Ya/Tidak)`, `rujuk_rs_dua (Ya/Tidak)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Apa hasil skrining tajam penglihatan? | Dws/Lansia | PTM > Gangguan Penglihatan > Refraksi Mata K | ↻ |
| Hasil pemeriksaan pupil | Dws/Lansia | PTM > Gangguan Penglihatan > Katarak Mata Ka | ↻ |

### `resiko_penyakit_jantung` — e-Puskesmas - Skrining Risiko Penyakit Jantung - Buat Baru
- **route** `/skriningrisikojantung`  ·  **converter fn**: _skrining_ekg, _map_skrining_jantung_ekg  ·  _jadikan primary_
- **2 pertanyaan ASIK** dipindah ke sini (0 BARU / 2 repoint)
- **Field live (24)**: `Skrining[nama] (input/text)`, `Skrining[pasien_id] (input/number)`, `Skrining[tanggal] (input/text)`, `SkriningJantung[jantung_keluarga] (Jantung/Tidak Ada)`, `SkriningJantung[jantung_sendiri] (Jantung/Tidak Ada)`, `tandai_semua_risiko_jantung (Ya/Tidak)`, `SkriningJantung[merokok] (Ya/Tidak)`, `SkriningJantung[kurang_aktifitas_fisik] (Ya/Tidak)`, `SkriningJantung[gula_berlebih] (Ya/Tidak)`, `SkriningJantung[garam_berlebih] (Ya/Tidak)`, `SkriningJantung[lemak_berlebih] (Ya/Tidak)`, `SkriningJantung[kurang_makan_sayur] (Ya/Tidak)`, `SkriningJantung[alkohol] (Ya/Tidak)`, `SkriningJantung[ekg] (input/text)`, `SkriningJantung[ekg_v2] (Normal/Tidak Normal)`, `SkriningJantung[kardiovaskuler_rujuk_rs] (Rujuk/Tidak Rujuk)`, `SkriningJantung[st_depresi] (Ya/Tidak)`, `SkriningJantung[t_inversi] (Ya/Tidak)`, `SkriningJantung[hipertrofi_ventrikel_kiri] (Ya/Tidak)`, `SkriningJantung[atrial_fibrilasi] (Ya/Tidak)`, `SkriningJantung[q_patologis] (Ya/Tidak)`, `SkriningJantung[st_elevasi] (Ya/Tidak)`, `SkriningJantung[abnormal_lainnya] (textarea/textarea)`, `SkriningJantung[carta] [select: <5%, 5% - <10%, 10% - <20%, 20% - <30%]`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Hasil Pemeriksaan EKG | Dws/Lansia | PTM > Kardiovaskular > Hasil EKG | ↻ |
| Pemeriksaan EKG | Dws/Lansia | PTM > Kardiovaskular > Hasil EKG | ↻ |

### `payudara` — e-Puskesmas - Skrining Risiko Kanker Payudara - Buat Baru
- **route** `/skriningkankerpayudara`  ·  **converter fn**: _enrich_payudara, _map_iva_sadanis  ·  _jadikan primary_
- **1 pertanyaan ASIK** dipindah ke sini (0 BARU / 1 repoint)
- **Field live (13)**: `riwayat_penyakit_keluarga (Kanker/Benjolan Abnormal Pada Payudara)`, `riwayat_penyakit_sendiri (Kanker/Benjolan Abnormal Pada Payudara)`, `checkall (Ya/Tidak)`, `merokok (Ya/Tidak)`, `kurang_aktifitas_fisik (Ya/Tidak)`, `gula_berlebih (Ya/Tidak)`, `garam_berlebih (Ya/Tidak)`, `lemak_berlebih (Ya/Tidak)`, `kurang_buah_sayur (Ya/Tidak)`, `konsumsi_alkohol (Ya/Tidak)`, `hasil_sadanis (Normal/Ditemukan benjolan/Curiga kanker)`, `tindak_lanjut_sadanis (Rujuk/Tidak Rujuk)`, `hasil_usg (Normal/Simple cyst/Non simple cyst)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Pemeriksaan yang dilakukan | Dws/Lansia | skrining_klaster > payudara (SADANIS) / PTM  | ↻ |

## GRUP B — Mapper baru / repoint dewasa

### `skriningkankerparu` — e-Puskesmas - Skrining Risiko Kanker Paru - Buat Baru
- **route** `/skriningkankerparu`  ·  **converter fn**: _map_skrining_kanker_paru, _map_penapisan_kanker_paru
- **8 pertanyaan ASIK** dipindah ke sini (5 BARU / 3 repoint)
- **Field live (9)**: `jenis_kelamin (Laki-laki/Perempuan)`, `usia (> 65 tahun/45 - 65 tahun/< 45 tahun)`, `diagnosis_kanker (Ya, pernah > 5 tahun yang lalu/Ya, pernah < 5 tahun yang lalu/Tidak pernah)`, `keluarga_kanker (Ya, kanker paru/Ya, kanker jenis lain/Tidak ada)`, `riwayat_merokok (Perokok aktif, masih merokok 1 tahun ini/Bekas perokok, berhenti < 15 tahun/Perokok pasif (dari lingkungan rumah atau kantor)/Tidak merokok)`, `riwayat_bekerja (Ya/Tidak yakin / ragu-ragu/Tidak)`, `tempat_tinggal_berpolusi (Ya/Tidak yakin / ragu-ragu/Tidak)`, `rumah_tidak_sehat (Ya/Tidak yakin / ragu-ragu/Tidak)`, `diagnosis_paru_kronik (Ya, pernah Tuberkulosis (TBC)/Ya, pernah penyakit paru kronik (PPOK)/Tidak)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Apakah memiliki riwayat kanker paru pada keluarga (ayah/ibu/ | Dws/Lansia | PTM > Riwayat PTM pada Keluarga > Penyakit K | ↻ |
| Apakah sedang mengalami gejala (batuk lama/berdarah/sesak na | Dws/Lansia | penyakit_khusus.ICDX (A15-A19 TB) | ↻ |
| Apakah Anda pernah memiliki riwayat penyakit TBC atau PPOK? | Dws/Lansia | PTM > Riwayat PTM pada Diri Sendiri > Penyak | ↻ |
| Apakah pernah didiagnosis/menderita kanker? | Dws/Lansia | — | 🆕 |
| Riwayat tempat kerja mengandung zat karsinogenik (pertambang | Dws/Lansia | — | 🆕 |
| Lingkungan tempat tinggal berpotensi tinggi (dekat pabrik/pe | Dws/Lansia | — | 🆕 |
| Lingkungan dalam rumah yang tidak sehat (ventilasi buruk/ata | Dws/Lansia | — | 🆕 |
| Pernah didiagnosis penyakit paru kronik? | Dws/Lansia | — | 🆕 |

### `diabetes_melitus` — e-Puskesmas - Skrining Diabetes Melitus
- **route** `/skriningdiabetesmelitus`  ·  **converter fn**: _map_pemeriksaan_gula_darah_dewasa_lansia, pediatric gula darah
- **6 pertanyaan ASIK** dipindah ke sini (0 BARU / 6 repoint)
- **Field live (31)**: `anamnesis[Sering lapar] (Ya/Tidak)`, `anamnesis[Sering haus] (Ya/Tidak)`, `anamnesis[Sering BAK/mengompol] (Ya/Tidak)`, `anamnesis[Penurunan Berat Badan 2-6 minggu terakhir] (Ya/Tidak)`, `anamnesis[Riwayat Pribadi Diabetes Melitus] (Ya/Tidak)`, `anamnesis[Riwayat Keluarga Diabetes Melitus] (Ya/Tidak)`, `anamnesis[Riwayat Merokok] (Ya/Tidak)`, `anamnesis[Riwayat Minum alkohol/Merokok di keluarga] (Ya/Tidak)`, `anamnesis[Kebiasaan makan manis] (Ya/Tidak)`, `anamnesis[Aktifitas fisik setiap hari] (Ya/Tidak)`, `anamnesis[Istirahat cukup] (Ya/Tidak)`, `anamnesis[Kurang Makan Buah dan Sayur] (Ya/Tidak)`, `pemeriksaan_fisik[berat] (input/text)`, `pemeriksaan_fisik[tinggi] (input/text)`, `data_imt (input/text)`, `pemeriksaan_fisik[lingkar_perut] (input/text)`, `pemeriksaan_fisik[imt] (input/text)`, `pemeriksaan_fisik[hasil_imt] (input/text)`, `hasil_gds (input/text)`, `nilai_rujukan (input/text)`, `satuan (input/text)`, `hasil_gdp (input/text)`, `nilai_rujukan_gdp (input/text)`, `satuan_gdp (input/text)`, `hasil_gd2pp (input/text)`, `nilai_rujukan_gd2pp (input/text)`, `satuan_gd2pp (input/text)`, `hasil_hba1c (input/text)`, `nilai_rujukan_hba1c (input/text)`, `satuan_hba1c (input/text)`, `skor [select: Normal, Suspek]`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Apakah Anak Anda pernah dinyatakan diabetes atau kencing man | Balita | PTM > Riwayat PTM pada Diri Sendiri > Penyak | ↻ |
| Gula Darah Sewaktu (GDS) | Balita | PTM > Pemeriksaan > Pemeriksaan Gula | ↻ |
| Apakah Anda pernah dinyatakan diabetes atau kencing manis ol | Dws/Lansia | PTM > Riwayat PTM pada Diri Sendiri > Penyak | ↻ |
| Gula Darah Sewaktu (GDS) (mg/dl) | Dws/Lansia | PTM > Pemeriksaan > Pemeriksaan Gula | ↻ |
| Gula Darah Puasa (GDP) (mg/dl) | Dws/Lansia | PTM > Pemeriksaan > Pemeriksaan Gula Darah P | ↻ |
| Gula Darah 2 Jam PP (mg/dl) | Dws/Lansia | PTM > Pemeriksaan > Pemeriksaan Gula Darah 2 | ↻ |

### `kolorektal` — e-Puskesmas - Skrining Kanker Kolokteral
- **route** `/skriningkankerkolorektal`  ·  **converter fn**: _map_faktor_risiko_kanker_usus
- **5 pertanyaan ASIK** dipindah ke sini (3 BARU / 2 repoint)
- **Field live (11)**: `riwayat_bab (Ada/Tidak ada)`, `riwayat_polip (Ada/Tidak ada)`, `riwayat_reseksi (Ada/Tidak ada)`, `usia_tahun (< 50/50 - 69/≥ 70)`, `jenis_kelamin (Perempuan/Laki-laki)`, `riwayat_kanker_kolorektal (Memiliki riwayat keluarga kanker kolorektal generasi pertama/Tidak memiliki riwayat keluarga kanker kolorektal generasi pertama)`, `riwayat_merokok (Saat ini atau dulu pernah merokok/Tidak pernah)`, `kesediaan_colok_dubur (Bersedia/Menolak)`, `colok_dubur (Ditemukan benjolan/Tidak ditemukan benjolan)`, `darah_samar (Negatif/Positif)`, `skor [select: Normal, Suspek]`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Apakah ada anggota keluarga Anda yang pernah dinyatakan mend | Dws/Lansia | PTM > Riwayat PTM pada Keluarga > Penyakit K | ↻ |
| Apakah Anda merokok? | Dws/Lansia | PTM > Faktor Risiko > Merokok | ↻ |
| Kesediaan untuk diperiksa Colok Dubur | Dws/Lansia | — | 🆕 |
| Colok Dubur (hanya apabila bersedia) | Dws/Lansia | — | 🆕 |
| Hasil pemeriksaan Darah Samar (hanya apabila bersedia) | Dws/Lansia | — | 🆕 |

### `faktor_risiko` — e-Puskesmas - Skrining Faktor Risiko
- **route** `/skriningfaktorrisiko`  ·  **converter fn**:  _map_ppok_puma / _map_perilaku_merokok / new  ·  _Vue-rendered_
- **4 pertanyaan ASIK** dipindah ke sini (2 BARU / 2 repoint)
- ⚠️ **Field form Vue-rendered** — nama field dari `records` getlist pasien *done* (jalankan `skrining_inventory.py`).

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Apakah Anda merokok dalam setahun terakhir ini? | Dws/Lansia | PTM > Faktor Risiko > Merokok | ↻ |
| Apakah Anda terpapar asap rokok atau menghirup asap rokok da | Dws/Lansia | — | 🆕 |
| Apakah Anda merokok dalam setahun terakhir ini? | Dws/Lansia | PTM > Faktor Risiko > Merokok | ↻ |
| Apakah Anda terpapar/menghirup asap rokok dari orang lain di | Dws/Lansia | — | 🆕 |

### `skrining_resiko_kanker_serviks` — e-Puskesmas - Formulir Skrining Risiko Kanker Serviks - Buat Baru
- **route** `/risikokankerserviks`  ·  **converter fn**: _map_iva_sadanis
- **4 pertanyaan ASIK** dipindah ke sini (1 BARU / 3 repoint)
- **Field live (14)**: `riwayat_penyakit_keluarga (Kanker/Benjolan Abnormal Pada Payudara)`, `riwayat_penyakit_sendiri (Kanker/Benjolan Abnormal Pada Payudara)`, `merokok (Ya/Tidak)`, `kurang_aktivitas (Ya/Tidak)`, `gula_berlebihan (Ya/Tidak)`, `garam_berlebihan (Ya/Tidak)`, `lemak_berlebihan (Ya/Tidak)`, `kurang_makan_buah (Ya/Tidak)`, `konsumsi_alkohol (Ya/Tidak)`, `seksual (Ya/Tidak)`, `inspekulo (Normal/Curiga Kanker)`, `hasil_iva (Positif/Negatif/Curiga Kanker)`, `tindak_lanjut_iva (Krioterapi/Rujuk)`, `hpv_dna (HPV Negatif/Positif HPV tipe onkogenik lain/Positif HPV tipe 52/Positif HPV tipe 18)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Apakah pernah melakukan hubungan intim/seksual? | Dws/Lansia | — | 🆕 |
| Pemeriksaan Inspekulo | Dws/Lansia | PTM > Pemeriksaan IVA dan Sadanis > Hasil IV | ↻ |
| Pemeriksaan Inspeksi Visual Asam Asetat (IVA) | Dws/Lansia | PTM > Pemeriksaan IVA dan Sadanis > Hasil IV | ↻ |
| Hasil pemeriksaan DNA HPV | Dws/Lansia | Klaster & Siklus Hidup > Skrining Risiko Kan | ↻ |

### `skrining_kesehatan_gigi_dewasa` — e-Puskesmas - Skrining Gigi Dewasa - Buat Baru
- **route** `/skriningkesehatangigidewasa`  ·  **converter fn**: _map_dental
- **4 pertanyaan ASIK** dipindah ke sini (1 BARU / 3 repoint)
- **Field live (17)**: `Skrining[nama] (input/text)`, `Skrining[pasien_id] (input/number)`, `Skrining[tanggal] (input/text)`, `SkriningGigi[rutin_kontrol] (Ya/Tidak)`, `SkriningGigi[gigi_bungsu] (Ya/Tidak)`, `SkriningGigi[gigi_hilang] (Ya/Tidak)`, `SkriningGigi[gigi_berlubang] (Ya/Tidak)`, `SkriningPkg[is_karies_gigi] (Ya/Tidak)`, `SkriningPkg[tindak_lanjut_karies_gigi] (textarea/textarea)`, `SkriningPkg[is_pemeriksaan_saluran_akar_gigi] (Normal/Ditemukan Kelainan)`, `SkriningPkg[tindak_lanjut_pemeriksaan_saluran_akar_gigi] (textarea/textarea)`, `SkriningGigi[pocket_periodontal] (Ya/Tidak)`, `SkriningGigi[hasil_pocket_periodontal] (input/text)`, `SkriningGigi[rekomendasi_pocket_periodontal] (input/text)`, `SkriningGigi[mobility_gigi] (Ya/Tidak)`, `SkriningGigi[hasil_mobility_gigi] [select: 0, 1, 2, 3]`, `SkriningGigi[rekomendasi_mobility_gigi] (input/text)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Gigi karies | Dws/Lansia | Anamnesa > Pemeriksaan Dasar Gigi > Status K | ↻ |
| Gigi hilang/dicabut | Dws/Lansia | — | 🆕 |
| Penyakit Periodontal | Dws/Lansia | Anamnesa > Pemeriksaan Dasar Gigi > Warna Gu | ↻ |
| Gigi Goyang | Dws/Lansia | Anamnesa > Pemeriksaan Dasar Gigi > Goyang | ↻ |

### `catin` — e-Puskesmas - Skrining Calon Pengantin (Catin) - Buat Baru
- **route** `/skriningcatin`  ·  **converter fn**: _map catin (Hb)  ·  _Vue-rendered_
- **3 pertanyaan ASIK** dipindah ke sini (0 BARU / 3 repoint)
- ⚠️ **Field form Vue-rendered** — nama field dari `records` getlist pasien *done* (jalankan `skrining_inventory.py`).

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Hasil Pemeriksaan Rapid Test Sifilis | Dws/Lansia | penyakit_khusus.ICDX (A50-A53) -> Reaktif | ↻ |
| Hasil Pemeriksaan Rapid Test HIV | Dws/Lansia | penyakit_khusus.ICDX (B20-B24) -> Reaktif; e | ↻ |
| Kadar Hemoglobin | Dws/Lansia | Laboratorium > Hb (Hemoglobin) > Hasil | ↻ |

### `fungsi_ginjal` — e-Puskesmas - Skrining Fungsi Ginjal
- **route** `/skriningfungsiginjal`  ·  **converter fn**: blok ginjal >=40  ·  _Vue-rendered_
- **2 pertanyaan ASIK** dipindah ke sini (0 BARU / 2 repoint)
- ⚠️ **Field form Vue-rendered** — nama field dari `records` getlist pasien *done* (jalankan `skrining_inventory.py`).

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Hasil Pemeriksaan Kreatinin | Dws/Lansia | PTM > Ginjal > Kreatinin | ↻ |
| Hasil Pemeriksaan Ureum | Dws/Lansia | PTM > Ginjal > Ureum | ↻ |

### `hipertensi` — e-Puskesmas - Skrining Hipertensi - Buat Baru
- **route** `/skrininghipertensi`  ·  **converter fn**: _map_tekanan_darah_dewasa_lansia
- **1 pertanyaan ASIK** dipindah ke sini (0 BARU / 1 repoint)
- **Field live (11)**: `riwayat_pribadi (Ya/Tidak)`, `riwayat_keluarga (Ya/Tidak)`, `riwayat_merokok (Ya/Tidak)`, `riwayat_alkohol (Ya/Tidak)`, `makan_asin (Ya/Tidak)`, `aktifitas_fisik (Ya/Tidak)`, `istirahat_cukup (Ya/Tidak)`, `kurang_buah_sayur (Ya/Tidak)`, `sistole (input/number)`, `diastole (input/number)`, `klasifikasi_ht (input/text)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Apakah Anda pernah dinyatakan tekanan darah tinggi? | Dws/Lansia | PTM > Riwayat PTM pada Diri Sendiri > Penyak | ↻ |

### `skrining_kesehatan_gigi_balita` — /skriningkesehatangigibalita
- **route** `/skriningkesehatangigibalita`  ·  **converter fn**: _map_dental / pediatric gigi  ·  _key balita — konfirmasi_
- **1 pertanyaan ASIK** dipindah ke sini (0 BARU / 1 repoint)

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Berapa jumlah gigi karies? | Balita | Anamnesa > Pemeriksaan Dasar Gigi > Status K | ↻ |

### `skrining_imunisasi_dewasa` — e-Puskesmas - Formulir Skrining Imunisasi Dewasa - Buat Baru
- **route** `/skriningimunisasidewasa`  ·  **converter fn**: (baru)
- **1 pertanyaan ASIK** dipindah ke sini (1 BARU / 0 repoint)
- **Field live (1)**: `imunisasi_tetanus (Belum/Sudah mendapat T1/Sudah mendapat T2/Sudah mendapat T3)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| Apakah anda pernah mendapatkan imunisasi tetanus minimal 2 k | Dws/Lansia | — | 🆕 |

## GRUP C — Mapper geriatri baru (kini shell)

### `pengkajian_nutrisi` — e-Puskesmas - Formulir Skrining Pengkajian Nutrisi (Short-Form MNA) - Buat Baru
- **route** `/skriningpengkajiannutrisi`  ·  **converter fn**: (baru — shell MNA)
- **6 pertanyaan ASIK** dipindah ke sini (6 BARU / 0 repoint)
- **Field live (10)**: `bb (input/number)`, `tb (input/number)`, `usia (input/text)`, `imt_view (input/number)`, `penurunan_asupan_makanan (Nafsu makan yang sangat berkurang/Nafsu makan sedikit berkurang (sedang)/Nafsu makan biasa saja)`, `penurunan_berat_badan (Penurunan berat badan lebih dari 3 kg/Tidak tahu/Penurunan berat badan 1-3 kg/Tidak ada penurunan berat badan)`, `mobilitas (Harus berbaring di tempat tidur atau menggunakan kursi roda/Bisa keluar dari tempat tidur atau kursi roda, tetapi tidak bisa keluar rumah/Bisa keluar rumah)`, `stres_psikologis_penyakit (Ya/Tidak)`, `masalah_neuropsikologi (Demensia berat atau depresi berat/Demensia ringan/Tidak ada masalah psikologis)`, `imt (IMT < 19/IMT 19 - < 21/IMT 21 - < 23/IMT 23 atau lebih)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| [MNA-SF] Penurunan asupan makanan dalam 3 bulan terakhir (na | Dws/Lansia | — | 🆕 |
| [MNA-SF] Penurunan berat badan dalam tiga bulan terakhir? | Dws/Lansia | — | 🆕 |
| [MNA-SF] Kemampuan melakukan mobilitas? | Dws/Lansia | — | 🆕 |
| [MNA-SF] Menderita stress psikologis atau penyakit akut dala | Dws/Lansia | — | 🆕 |
| [MNA-SF] Mengalami masalah neuropsikologis? | Dws/Lansia | — | 🆕 |
| [MNA-SF] Berapa Nilai IMT (Indeks Massa Tubuh)? | Dws/Lansia | — | 🆕 |

### `sppb` — e-Puskesmas - Formulir Skrining Short Physical Performance Battery (SPPB) - Buat Baru
- **route** `/skriningsppb`  ·  **converter fn**: (baru — shell SPPB)
- **5 pertanyaan ASIK** dipindah ke sini (5 BARU / 0 repoint)
- **Field live (8)**: `Skrining[nama] (input/text)`, `Skrining[pasien_id] (input/number)`, `Skrining[tanggal] (input/text)`, `SkriningSppb[berdampingan] (Bertahan 10 detik/Tidak bertahan 10 detik/Tidak dilakukan)`, `SkriningSppb[semitandem] (Bertahan 10 detik/Tidak bertahan 10 detik/Tidak dilakukan)`, `SkriningSppb[tandem] (Bertahan 10 detik/Bertahan 3 – 9,99 detik/Bertahan <3 detik/Tidak dilakukan)`, `SkriningSppb[kecepatan] (<4,82 detik/4,82 detik – 6,20 detik/6,21 detik – 8,70 detik/>8,70 detik)`, `SkriningSppb[berdiri] (<11,19 detik/11,2 – 13,69 detik/13,7 – 16,69 detik/16,7 – 59,9 detik)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| [SPPB] Tes keseimbangan berdiri 10 detik: Berdiri berdamping | Dws/Lansia | — | 🆕 |
| [SPPB] Tes keseimbangan berdiri 10 detik: Berdiri semi tande | Dws/Lansia | — | 🆕 |
| [SPPB] Tes keseimbangan berdiri 10 detik: Berdiri Tandem | Dws/Lansia | — | 🆕 |
| [SPPB] Tes kecepatan berjalan: Waktu untuk berjalan sejauh e | Dws/Lansia | — | 🆕 |
| [SPPB] Tes berdiri dari kursi: Waktu untuk bangkit dari kurs | Dws/Lansia | — | 🆕 |

### `gds` — Skrining Geriatric Depression Scale (GDS-4)
- **route** `/skrining/gds`  ·  **converter fn**: (baru — sebagian via _map_skilas depresi)
- **4 pertanyaan ASIK** dipindah ke sini (4 BARU / 0 repoint)
- **Field live (4)**: `kepuasan_hidup (Ya/Tidak)`, `merasa_bosan (Ya/Tidak)`, `tidak_berdaya (Ya/Tidak)`, `merasa_tidak_berharga (Ya/Tidak)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| [Lanjutan] Apakah anda pada dasarnya puas dengan kehidupan a | Dws/Lansia | — | 🆕 |
| [Lanjutan] Apakah anda sering merasa bosan? | Dws/Lansia | — | 🆕 |
| [Lanjutan] Apakah anda sering merasa tidak berdaya? | Dws/Lansia | — | 🆕 |
| [Lanjutan] Apakah anda merasa tidak berharga seperti perasaa | Dws/Lansia | — | 🆕 |

### `mini_cog` — Skrining Instrumen Mini-COG
- **route** `/skrining/cog`  ·  **converter fn**: (baru — shell Mini-COG)
- **3 pertanyaan ASIK** dipindah ke sini (3 BARU / 0 repoint)
- **Field live (3)**: `kata_yang_tepat (Tidak Tepat/Tepat 1 Kata/Tepat 2 Kata/Tepat 3 Kata)`, `gambar_jam (Gambar Jam Normal/Gambar Jam Abnormal)`, `kata_yang_tepat_dua (Tidak Tepat/Tepat 1 Kata/Tepat 2 Kata/Tepat 3 Kata)`

| Pertanyaan ASIK | Klaster | Path lama (PDF) | Baru? |
|---|---|---|:--:|
| [Mini-Cog] Mintalah pasien mendengarkan dengan cermat dan me | Dws/Lansia | — | 🆕 |
| [Mini-Cog] Katakan seluruh frase: 'Tolong gambar sebuah jam. | Dws/Lansia | — | 🆕 |
| [Mini-Cog] Mintalah pasien mengulang 3 kata yang disebutkan  | Dws/Lansia | — | 🆕 |

## ⚠️ Target belum ter-resolve ke key (perlu cek manual)
- [yellow] Apakah Anda melakukan olahraga intensitas sedang ( → target: `x PTM > Faktor Risiko > Kurang Aktivitas Fisik`
- [yellow] Apakah Anda melakukan olahraga intensitas berat (b → target: `x PTM > Faktor Risiko > Kurang Aktivitas Fisik`

## Grup D — tetap modul (fallback), tidak ada di skrining klaster
- **Tingkat Aktivitas Fisik** → tetap `PTM > Faktor Risiko > Kurang Aktivitas Fisik` (sheet Tebet menandai `x`).

## Langkah implementasi
1. `skrining_inventory.py` (Tebet) → nama field `records` per screening (khususnya 3 form Vue: faktor_risiko, fungsi_ginjal, catin).
2. Helper prioritas **klaster-primary → modul-fallback** (di `_skrining_index`/per-mapper).
3. Grup A (invert) → Grup B (repoint dewasa) → Grup C (geriatri).
4. Validasi key di 1–2 region lain (Pekayon/Cipondoh).
5. Restart Celery + re-merge `force_remerge` sampel per klaster (CLAUDE.md §9/§12).

## Lampiran — inventory field per screening (form live ePus)
- **`faktor_risiko`** — Vue-rendered (field via getlist record).
- **`gejala_tbc`** (37): `nama-pasien (input/text)`, `no-rekam-medis (input/number)`, `tanggal-lahir (input/text)`, `nik (input/text)`, `jenis_kelamin (input/text)`, `pekerjaan (input/text)`, `no_hp (input/text)`, `alamat (input/text)`, `berat_badan (input/number)`, `tinggi_badan (input/number)`, `imt (input/number)`, `data_imt (input/text)`, `cara_ukur (input/text)`, `kategori_imt (input/text)`, `riwayat_kontak_tbc (Ya/Tidak)`, `batuk_2_minggu_lebih (Ya/Tidak)`, `metode_sputum (TCM (Tes Cepat Molekuler)/BTA (Basil Tahan Asam))`, `hasil_sputum (Tidak terdeteksi TB/TB tanpa resistensi rifampisin/TB dengan resistensi rifampisin (RR-TB)/Negatif (Tidak ditemukan basil tahan asam))`, `tandai_semua_faktor_risiko (Tandai "Ya"/Tandai "Tidak")`, `pernah_terdiagnosa (Ya/Tidak)`, `kapan (input/text)`, `berobat_tidak_tuntas (Ya/Tidak)`, `malnutrisi (Ya/Tidak)`, `merokok (Ya/Tidak)`, `riwayat_kencing_manis (Ya/Tidak)`, `odhiv (Ya/Tidak)`, `lansia (Ya/Tidak)`, `hamil (Ya/Tidak)`, `wbp (Ya/Tidak)`, `tinggal_wilayah_kumuh (Ya/Tidak)`, `abnormalitas_tbc (Abnormalitas TBC/Abnormalitas Bukan TBC/Normal)`, `tandai_semua_gejala (Ya/Tidak)`, `batuk (Ya/Tidak)`, `bb_turun (Ya/Tidak)`, `demam (Ya/Tidak)`, `berkeringat (Ya/Tidak)`, `gejala_penyakit_pernapasan_lainnya (input/text)`
- **`puma`** (27): `jenis_kelamin (Perempuan/Laki-laki)`, `usia (40 - 49 tahun/50 - 59 tahun/> 60 tahun)`, `pernah_merokok (Perokok aktif (dalam 1 tahun ini masih merokok)/Perokok/bekas perokok berhenti <10 tahun lalu/Tidak pernah merokok)`, `jumlah_rokok (< 20 bungkus per tahun: Skor 0/20-30 bungkus per tahun: Skor 1/> 30 bungkus per tahun: Skor 2)`, `status_merokok (Merokok/Tidak Merokok)`, `napas_pendek (Ya/Tidak)`, `dahak (Ya/Tidak)`, `batuk (Ya/Tidak)`, `pemeriksaan_fungsi_paru (Ya/Tidak)`, `keluhan [select: Batuk kering, Rasa berat di dada, Sesak nafas, Batuk berdahak]`, `wawancara_1 (Ya/Tidak)`, `wawancara_2 (Ya/Tidak)`, `pink_puffer (Ada pink puffer/Tidak ada pink puffer)`, `pursed_lips_breathing (Ada pernapasan pursed lips breathing/Tidak ada pernapasan pursed lips breathing)`, `otot_bantu_napas (Ya/Tidak)`, `sela_iga (Ada pelebaran sela iga/Tidak ada pelebaran sela iga)`, `barrel_chest (Ada barrel chest/Tidak ada barrel chest)`, `hipersonor (Ada hipersonor/Tidak ada hipersonor)`, `vesikular (Normal breathing/Suara nafas vesikular meningkat/Suara nafas vesikular melemah)`, `ronki_mengi (Ada ronki atau mengi/Tidak ada ronki atau mengi)`, `ekspirasi (Ada ekspirasi memanjang/Tidak ada ekspirasi memanjang)`, `spirometri (Selesai/Tidak Selesai)`, `hasil_spirometri [select: Normal, Restriksi ringan, Restriksi sedang, Restriksi berat]`, `kv (input/number)`, `kvp_prediksi (input/number)`, `vep1_prediksi (input/number)`, `rasio_vep1_kvp (input/number)`
- **`obesitas`** (13): `tandai_semua_obesitas (Ya/Tidak)`, `makan_manis (Ya/Tidak)`, `aktifitas_fisik (Ya/Tidak)`, `istirahat_cukup (Ya/Tidak)`, `risiko_merokok (Ya/Tidak)`, `keluarga_alkohol_merokok (Ya/Tidak)`, `obat_steroid (Ya/Tidak)`, `berat (input/number)`, `tinggi (input/number)`, `lingkar_perut (input/number)`, `imt (input/number)`, `status_obesitas_sentral (input/text)`, `kategori_status_gizi [select: Gizi Kurang, Gizi Baik, Gizi Lebih, Obesitas]`
- **`diabetes_melitus`** (31): `anamnesis[Sering lapar] (Ya/Tidak)`, `anamnesis[Sering haus] (Ya/Tidak)`, `anamnesis[Sering BAK/mengompol] (Ya/Tidak)`, `anamnesis[Penurunan Berat Badan 2-6 minggu terakhir] (Ya/Tidak)`, `anamnesis[Riwayat Pribadi Diabetes Melitus] (Ya/Tidak)`, `anamnesis[Riwayat Keluarga Diabetes Melitus] (Ya/Tidak)`, `anamnesis[Riwayat Merokok] (Ya/Tidak)`, `anamnesis[Riwayat Minum alkohol/Merokok di keluarga] (Ya/Tidak)`, `anamnesis[Kebiasaan makan manis] (Ya/Tidak)`, `anamnesis[Aktifitas fisik setiap hari] (Ya/Tidak)`, `anamnesis[Istirahat cukup] (Ya/Tidak)`, `anamnesis[Kurang Makan Buah dan Sayur] (Ya/Tidak)`, `pemeriksaan_fisik[berat] (input/text)`, `pemeriksaan_fisik[tinggi] (input/text)`, `data_imt (input/text)`, `pemeriksaan_fisik[lingkar_perut] (input/text)`, `pemeriksaan_fisik[imt] (input/text)`, `pemeriksaan_fisik[hasil_imt] (input/text)`, `hasil_gds (input/text)`, `nilai_rujukan (input/text)`, `satuan (input/text)`, `hasil_gdp (input/text)`, `nilai_rujukan_gdp (input/text)`, `satuan_gdp (input/text)`, `hasil_gd2pp (input/text)`, `nilai_rujukan_gd2pp (input/text)`, `satuan_gd2pp (input/text)`, `hasil_hba1c (input/text)`, `nilai_rujukan_hba1c (input/text)`, `satuan_hba1c (input/text)`, `skor [select: Normal, Suspek]`
- **`hipertensi`** (11): `riwayat_pribadi (Ya/Tidak)`, `riwayat_keluarga (Ya/Tidak)`, `riwayat_merokok (Ya/Tidak)`, `riwayat_alkohol (Ya/Tidak)`, `makan_asin (Ya/Tidak)`, `aktifitas_fisik (Ya/Tidak)`, `istirahat_cukup (Ya/Tidak)`, `kurang_buah_sayur (Ya/Tidak)`, `sistole (input/number)`, `diastole (input/number)`, `klasifikasi_ht (input/text)`
- **`penglihatan`** (23): `mata_luar (Normal/Tidak Sehat)`, `jenis_pemeriksaan_mata (E tumbling/Uncorrected Snellen Chart)`, `tajam_kiri (Normal (6/6 - 6/12)/Kelainan Refraksi Sedang (< 6/12 - 6/18)/Kelainan Refraksi Berat (< 6/18 - 6/60)/low vision (6/60 - 3/60))`, `tajam_kanan (Normal (6/6 - 6/12)/Kelainan Refraksi Sedang (< 6/12 - 6/18)/Kelainan Refraksi Berat (< 6/18 - 6/60)/low vision (6/60 - 3/60))`, `pemeriksaan_visus_rabun_dekat_kiri (Ya/Tidak)`, `pemeriksaan_visus_rabun_dekat_kanan (Ya/Tidak)`, `buta_warna_kiri (Ya/Tidak)`, `buta_warna_kanan (Ya/Tidak)`, `kacamata (Ya/Tidak)`, `gangguan_refraksi_kiri (Ya/Tidak)`, `gangguan_refraksi_kanan (Ya/Tidak)`, `kelainan_organik[] (input/checkbox)`, `katarak_kiri (Ya/Tidak)`, `katarak_kanan (Ya/Tidak)`, `pinhole_kiri (Visus membaik: visus 6/6 - 6/12/Visus tidak membaik: visus < 6/12 - < 3/60)`, `pinhole_kanan (Visus membaik: visus 6/6 - 6/12/Visus tidak membaik: visus < 6/12 - < 3/60)`, `pemeriksaan_pupil_kiri (Positif/Negatif)`, `pemeriksaan_pupil_kanan (Positif/Negatif)`, `glaukoma_kiri (Ya/Tidak)`, `glaukoma_kanan (Ya/Tidak)`, `retinopati_kiri (Ya/Tidak)`, `retinopati_kanan (Ya/Tidak)`, `rujuk_rs_dua (Ya/Tidak)`
- **`kolorektal`** (11): `riwayat_bab (Ada/Tidak ada)`, `riwayat_polip (Ada/Tidak ada)`, `riwayat_reseksi (Ada/Tidak ada)`, `usia_tahun (< 50/50 - 69/≥ 70)`, `jenis_kelamin (Perempuan/Laki-laki)`, `riwayat_kanker_kolorektal (Memiliki riwayat keluarga kanker kolorektal generasi pertama/Tidak memiliki riwayat keluarga kanker kolorektal generasi pertama)`, `riwayat_merokok (Saat ini atau dulu pernah merokok/Tidak pernah)`, `kesediaan_colok_dubur (Bersedia/Menolak)`, `colok_dubur (Ditemukan benjolan/Tidak ditemukan benjolan)`, `darah_samar (Negatif/Positif)`, `skor [select: Normal, Suspek]`
- **`payudara`** (13): `riwayat_penyakit_keluarga (Kanker/Benjolan Abnormal Pada Payudara)`, `riwayat_penyakit_sendiri (Kanker/Benjolan Abnormal Pada Payudara)`, `checkall (Ya/Tidak)`, `merokok (Ya/Tidak)`, `kurang_aktifitas_fisik (Ya/Tidak)`, `gula_berlebih (Ya/Tidak)`, `garam_berlebih (Ya/Tidak)`, `lemak_berlebih (Ya/Tidak)`, `kurang_buah_sayur (Ya/Tidak)`, `konsumsi_alkohol (Ya/Tidak)`, `hasil_sadanis (Normal/Ditemukan benjolan/Curiga kanker)`, `tindak_lanjut_sadanis (Rujuk/Tidak Rujuk)`, `hasil_usg (Normal/Simple cyst/Non simple cyst)`
- **`anemia`** (19): `check_all_1_7 (Ya/Tidak)`, `q1 (Ya/Tidak)`, `q2 (Ya/Tidak)`, `q3 (Ya/Tidak)`, `q4 (Ya/Tidak)`, `q5 (Ya/Tidak)`, `q6 (Ya/Tidak)`, `q7 (Ya/Tidak)`, `q8 (Ya/Tidak)`, `q9 (Ya/Tidak)`, `q10 (Ya/Tidak)`, `q11 (Ya/Tidak)`, `q12 (Sehat/Tidak Sehat)`, `q13 (Sehat/Tidak Sehat)`, `q14 (Ya/Tidak)`, `q15 (Sehat/Tidak Sehat)`, `tanda_klinis_anemia (Ya/Tidak)`, `pemeriksaan_hb (input/text)`, `skor [select: ≥ 12 g/dl, 11,9-11 g/dl, 10.9-8 g/dl, < 8 g/dl]`
- **`skriningkankerparu`** (9): `jenis_kelamin (Laki-laki/Perempuan)`, `usia (> 65 tahun/45 - 65 tahun/< 45 tahun)`, `diagnosis_kanker (Ya, pernah > 5 tahun yang lalu/Ya, pernah < 5 tahun yang lalu/Tidak pernah)`, `keluarga_kanker (Ya, kanker paru/Ya, kanker jenis lain/Tidak ada)`, `riwayat_merokok (Perokok aktif, masih merokok 1 tahun ini/Bekas perokok, berhenti < 15 tahun/Perokok pasif (dari lingkungan rumah atau kantor)/Tidak merokok)`, `riwayat_bekerja (Ya/Tidak yakin / ragu-ragu/Tidak)`, `tempat_tinggal_berpolusi (Ya/Tidak yakin / ragu-ragu/Tidak)`, `rumah_tidak_sehat (Ya/Tidak yakin / ragu-ragu/Tidak)`, `diagnosis_paru_kronik (Ya, pernah Tuberkulosis (TBC)/Ya, pernah penyakit paru kronik (PPOK)/Tidak)`
- **`resiko_penyakit_jantung`** (24): `Skrining[nama] (input/text)`, `Skrining[pasien_id] (input/number)`, `Skrining[tanggal] (input/text)`, `SkriningJantung[jantung_keluarga] (Jantung/Tidak Ada)`, `SkriningJantung[jantung_sendiri] (Jantung/Tidak Ada)`, `tandai_semua_risiko_jantung (Ya/Tidak)`, `SkriningJantung[merokok] (Ya/Tidak)`, `SkriningJantung[kurang_aktifitas_fisik] (Ya/Tidak)`, `SkriningJantung[gula_berlebih] (Ya/Tidak)`, `SkriningJantung[garam_berlebih] (Ya/Tidak)`, `SkriningJantung[lemak_berlebih] (Ya/Tidak)`, `SkriningJantung[kurang_makan_sayur] (Ya/Tidak)`, `SkriningJantung[alkohol] (Ya/Tidak)`, `SkriningJantung[ekg] (input/text)`, `SkriningJantung[ekg_v2] (Normal/Tidak Normal)`, `SkriningJantung[kardiovaskuler_rujuk_rs] (Rujuk/Tidak Rujuk)`, `SkriningJantung[st_depresi] (Ya/Tidak)`, `SkriningJantung[t_inversi] (Ya/Tidak)`, `SkriningJantung[hipertrofi_ventrikel_kiri] (Ya/Tidak)`, `SkriningJantung[atrial_fibrilasi] (Ya/Tidak)`, `SkriningJantung[q_patologis] (Ya/Tidak)`, `SkriningJantung[st_elevasi] (Ya/Tidak)`, `SkriningJantung[abnormal_lainnya] (textarea/textarea)`, `SkriningJantung[carta] [select: <5%, 5% - <10%, 10% - <20%, 20% - <30%]`
- **`skrining_resiko_kanker_serviks`** (14): `riwayat_penyakit_keluarga (Kanker/Benjolan Abnormal Pada Payudara)`, `riwayat_penyakit_sendiri (Kanker/Benjolan Abnormal Pada Payudara)`, `merokok (Ya/Tidak)`, `kurang_aktivitas (Ya/Tidak)`, `gula_berlebihan (Ya/Tidak)`, `garam_berlebihan (Ya/Tidak)`, `lemak_berlebihan (Ya/Tidak)`, `kurang_makan_buah (Ya/Tidak)`, `konsumsi_alkohol (Ya/Tidak)`, `seksual (Ya/Tidak)`, `inspekulo (Normal/Curiga Kanker)`, `hasil_iva (Positif/Negatif/Curiga Kanker)`, `tindak_lanjut_iva (Krioterapi/Rujuk)`, `hpv_dna (HPV Negatif/Positif HPV tipe onkogenik lain/Positif HPV tipe 52/Positif HPV tipe 18)`
- **`skrining_kesehatan_gigi_dewasa`** (17): `Skrining[nama] (input/text)`, `Skrining[pasien_id] (input/number)`, `Skrining[tanggal] (input/text)`, `SkriningGigi[rutin_kontrol] (Ya/Tidak)`, `SkriningGigi[gigi_bungsu] (Ya/Tidak)`, `SkriningGigi[gigi_hilang] (Ya/Tidak)`, `SkriningGigi[gigi_berlubang] (Ya/Tidak)`, `SkriningPkg[is_karies_gigi] (Ya/Tidak)`, `SkriningPkg[tindak_lanjut_karies_gigi] (textarea/textarea)`, `SkriningPkg[is_pemeriksaan_saluran_akar_gigi] (Normal/Ditemukan Kelainan)`, `SkriningPkg[tindak_lanjut_pemeriksaan_saluran_akar_gigi] (textarea/textarea)`, `SkriningGigi[pocket_periodontal] (Ya/Tidak)`, `SkriningGigi[hasil_pocket_periodontal] (input/text)`, `SkriningGigi[rekomendasi_pocket_periodontal] (input/text)`, `SkriningGigi[mobility_gigi] (Ya/Tidak)`, `SkriningGigi[hasil_mobility_gigi] [select: 0, 1, 2, 3]`, `SkriningGigi[rekomendasi_mobility_gigi] (input/text)`
- **`skrining_indra_pendengaran`** (18): `kiri (Ya/Tidak)`, `kanan (Ya/Tidak)`, `rujuk (Rujuk/Tidak Rujuk)`, `curiga_telinga_kiri (Ya/Tidak)`, `curiga_telinga_kanan (Ya/Tidak)`, `curiga_rujuk (Rujuk/Tidak Rujuk)`, `pemeriksaan_telinga_kiri (Ya/Tidak)`, `pemeriksaan_telinga_kanan (Ya/Tidak)`, `pemeriksaan_rujuk (Rujuk/Tidak Rujuk)`, `omsk_telinga_kiri (Ya/Tidak)`, `omsk_telinga_kanan (Ya/Tidak)`, `omsk_rujuk (Rujuk/Tidak Rujuk)`, `presbikusis_telinga_kiri (Ya/Tidak)`, `presbikusis_telinga_kanan (Ya/Tidak)`, `bisikan_telinga_kiri (Normal/Gangguan pendengaran)`, `bisikan_telinga_kanan (Normal/Gangguan pendengaran)`, `otoskop_kiri (Normal/Gangguan Pendengaran)`, `otoskop_kanan (Normal/Gangguan Pendengaran)`
- **`skrining_phq_4`** (4): `tidak-sama-sekali (Tidak sama sekali)`, `kurang-dari-satu (Kurang dari 1 (satu) minggu)`, `lebih-dari-satu (Lebih dari 1 (satu) minggu)`, `hampir-setiap-hari (Hampir setiap hari)`
- **`skrining_imunisasi_dewasa`** (1): `imunisasi_tetanus (Belum/Sudah mendapat T1/Sudah mendapat T2/Sudah mendapat T3)`
- **`fungsi_ginjal`** — Vue-rendered (field via getlist record).
- **`catin`** — Vue-rendered (field via getlist record).
- **`pengkajian_nutrisi`** (10): `bb (input/number)`, `tb (input/number)`, `usia (input/text)`, `imt_view (input/number)`, `penurunan_asupan_makanan (Nafsu makan yang sangat berkurang/Nafsu makan sedikit berkurang (sedang)/Nafsu makan biasa saja)`, `penurunan_berat_badan (Penurunan berat badan lebih dari 3 kg/Tidak tahu/Penurunan berat badan 1-3 kg/Tidak ada penurunan berat badan)`, `mobilitas (Harus berbaring di tempat tidur atau menggunakan kursi roda/Bisa keluar dari tempat tidur atau kursi roda, tetapi tidak bisa keluar rumah/Bisa keluar rumah)`, `stres_psikologis_penyakit (Ya/Tidak)`, `masalah_neuropsikologi (Demensia berat atau depresi berat/Demensia ringan/Tidak ada masalah psikologis)`, `imt (IMT < 19/IMT 19 - < 21/IMT 21 - < 23/IMT 23 atau lebih)`
- **`sppb`** (8): `Skrining[nama] (input/text)`, `Skrining[pasien_id] (input/number)`, `Skrining[tanggal] (input/text)`, `SkriningSppb[berdampingan] (Bertahan 10 detik/Tidak bertahan 10 detik/Tidak dilakukan)`, `SkriningSppb[semitandem] (Bertahan 10 detik/Tidak bertahan 10 detik/Tidak dilakukan)`, `SkriningSppb[tandem] (Bertahan 10 detik/Bertahan 3 – 9,99 detik/Bertahan <3 detik/Tidak dilakukan)`, `SkriningSppb[kecepatan] (<4,82 detik/4,82 detik – 6,20 detik/6,21 detik – 8,70 detik/>8,70 detik)`, `SkriningSppb[berdiri] (<11,19 detik/11,2 – 13,69 detik/13,7 – 16,69 detik/16,7 – 59,9 detik)`
- **`gds`** (4): `kepuasan_hidup (Ya/Tidak)`, `merasa_bosan (Ya/Tidak)`, `tidak_berdaya (Ya/Tidak)`, `merasa_tidak_berharga (Ya/Tidak)`
- **`mini_cog`** (3): `kata_yang_tepat (Tidak Tepat/Tepat 1 Kata/Tepat 2 Kata/Tepat 3 Kata)`, `gambar_jam (Gambar Jam Normal/Gambar Jam Abnormal)`, `kata_yang_tepat_dua (Tidak Tepat/Tepat 1 Kata/Tepat 2 Kata/Tepat 3 Kata)`
- **`skrining_kesehatan_gigi_lansia`** (19): `Skrining[nama] (input/text)`, `Skrining[pasien_id] (input/number)`, `Skrining[tanggal] (input/text)`, `SkriningGigi[rutin_kontrol] (Ya/Tidak)`, `SkriningGigi[pola_makan_sehat] (Ya/Tidak)`, `SkriningGigi[sikat_gigi] (Ya/Tidak)`, `SkriningGigi[gigi_palsu] (Ya/Tidak)`, `SkriningGigi[gigi_baik] (Ya/Tidak)`, `SkriningGigi[keluhan] (Ya/Tidak)`, `SkriningPkg[is_karies_gigi] (Ya/Tidak)`, `SkriningPkg[tindak_lanjut_karies_gigi] (textarea/textarea)`, `SkriningPkg[is_pemeriksaan_saluran_akar_gigi] (Normal/Ditemukan Kelainan)`, `SkriningPkg[tindak_lanjut_pemeriksaan_saluran_akar_gigi] (textarea/textarea)`, `SkriningGigi[pocket_periodontal] (Ya/Tidak)`, `SkriningGigi[hasil_pocket_periodontal] (input/text)`, `SkriningGigi[rekomendasi_pocket_periodontal] (input/text)`, `SkriningGigi[mobility_gigi] (Ya/Tidak)`, `SkriningGigi[hasil_mobility_gigi] [select: 0, 1, 2, 3]`, `SkriningGigi[rekomendasi_mobility_gigi] (input/text)`
