# Halaman Registri Diabetes Melitus CKG (Kertas Kerja DM)

Kertas kerja diabetes melitus per **satu puskesmas + satu tahun pelaporan**,
mengikuti format registri dirjen (dokumen *"Register Sheet Pasien HT, DM,
Dislipidemia dan Obesitas"*, sheet **"Diabetes Melitus"**). Isinya: identitas
pasien, hasil pemeriksaan **gula darah** pada tanggal berkunjung CKG, dan
follow-up gula darah per bulan. Bisa diexport ke **Excel** — di file export,
rumus tertanam langsung di sel (klik sel Interpretasi untuk melihatnya), dan
ada sheet **"Formula & Logika"** berisi penjelasan yang sama dengan kartu
**"Cara Membaca Kertas Kerja Ini"** di halaman.

Halaman ini **berbeda** dari halaman Registri Hipertensi: sumber datanya sama
(kunjungan CKG yang sama), tapi yang ditampilkan panel gula darah
(GDS/GDS 2/GDP/GD2PP/HbA1C), bukan tekanan darah.

**Cara pakai halaman:** pilih Puskesmas + Tahun Pelaporan (pilihan tahun =
tahun ini sampai 5 tahun ke belakang), lalu cari nama/NIK bila perlu. Klik
baris pasien untuk membuka detail (no. telepon, alamat, obat, sumber data, dan
tabel Follow Up per bulan). Keterangan "N pasien (CKG) · X diabetes melitus ·
Y prediabetes" = total pasien dalam registri itu beserta rinciannya per
interpretasi (Diabetes Melitus + Prediabetes = total); daftarnya dibagi **20
pasien per halaman**.

Kolom **"Follow-up"** di tabel utama berisi **angka** = jumlah baris Follow Up
pasien itu — gabungan kunjungan yang ada hasil gula darahnya **dan** bulan
**Missed Visit**. Jadi angka besar belum tentu sering kontrol; bisa jadi
banyak bulan Missed Visit. Rinciannya muncul saat baris pasien diklik.

Saat perhitungan pertama berjalan muncul tulisan **"Loading registri diabetes
melitus…"** beserta bilah kemajuan; hasilnya lalu disimpan (cache ±30 jam) dan
dihitung ulang otomatis tiap pagi. Keterangan **"Computed <waktu> ·
cached/fresh"** menunjukkan kapan angka itu dihitung.

## Inti — satu daftar, dua pertanyaan

Kolom hasil pemeriksaan menjawab: **berapa gula darah pasien SAAT skrining
CKG?** Kolom Follow Up menjawab: **pada bulan-bulan setelahnya, apakah gula
darahnya sudah mencapai target?** Karena pertanyaannya berbeda, labelnya bisa
berbeda — dan itu memang benar, bukan error.

Contoh yang paling sering ditanyakan: pasien dengan Interpretasi **"Diabetes
Melitus"** di bagian hasil pemeriksaan bisa berstatus **"Pasien DM terkendali
(target tercapai)"** di Follow Up. Itu bukan kontradiksi: yang pertama
menjawab *"apakah dia pasien diabetes?"*, yang kedua *"apakah gula darahnya
bulan ini sudah on target?"*.

## 1 · Arti singkatan

- **GDS** — Gula Darah Sewaktu, diperiksa kapan saja tanpa perlu puasa.
- **GDS 2** — pemeriksaan GDS **kedua**, untuk memastikan hasil GDS 1 yang
  tinggi. Hanya diisi kalau GDS 1 sudah ≥140 dan pasien belum pernah
  didiagnosis diabetes.
- **GDP** — Gula Darah Puasa (biasanya setelah puasa 8 jam).
- **GD2PP** — Gula Darah 2 jam setelah makan (Post Prandial).
- **HbA1C** — rata-rata gula darah ±3 bulan terakhir, dalam persen (%).

## 2 · Siapa yang masuk daftar ini (Syarat)

Pasien (per NIK) masuk daftar jika punya **minimal satu kunjungan CKG**
(kunjungan yang tercatat di ePus DAN ASIK) pada tahun itu, **DAN** memenuhi
salah satu:

1. **Sudah tercatat sebagai pasien DM** — ada catatan **diagnosis** diabetes,
   ATAU pasien menjawab "Ya" pada pertanyaan skrining CKG *"Apakah Anda pernah
   dinyatakan diabetes atau kencing manis oleh Dokter?"* → kolom Riwayat DM =
   **Ya**; ATAU
2. **Hasil gula darahnya di atas normal saat skrining CKG** — kolom
   Interpretasi = **Diabetes Melitus** atau **Prediabetes**. Pasien
   Prediabetes ikut ditampilkan supaya bisa dipantau lebih awal walau belum
   didiagnosis.

**Yang tidak ditampilkan:** pasien yang gula darahnya **Normal** DAN tidak
pernah didiagnosis diabetes — belum perlu dipantau di kertas kerja ini. Begitu
juga pasien yang hasilnya tidak bisa disimpulkan (lihat bagian 4) dan tidak
punya catatan diagnosis.

Kalau seorang pasien "hilang" dari daftar, urutan pemeriksaannya: (a) apakah
kunjungannya sudah cocok di kedua sumber (pasien CKG)? (b) apakah gula
darahnya memang Normal dan tidak ada diagnosis?

Sumber catatan diagnosis DM yang dipakai: jawaban skrining CKG di ASIK,
diagnosis pada tatalaksana Gula Darah di ASIK, atau diagnosis di ePuskesmas
(kode ICD-10 **E10–E14**, "Riwayat PTM pada Diri Sendiri" → Penyakit Diabetes,
dan "Tandai Penyakit Kronis" → Diabetes Mellitus). Cukup salah satu; sekali
tercatat, Riwayat DM tetap **Ya**.

## 3 · Arti label Interpretasi (saat kunjungan CKG)

Kalau **Riwayat DM = Ya** → selalu **"Diabetes Melitus"**, berapa pun hasil
gula darahnya hari itu. Diagnosis tidak hilang karena satu hasil ukur yang
bagus.

Kalau Riwayat DM = Tidak, labelnya dari hasil ukur:

- **Diabetes Melitus** — GDP **126 mg/dL ke atas**, ATAU GD2PP **200 mg/dL ke
  atas**, ATAU GDS 2 **200 mg/dL ke atas**. Cukup salah satu.
- **Prediabetes** — GDP **100–125 mg/dL**, ATAU GD2PP **140–199 mg/dL**, ATAU
  GDS 1 **140–199 mg/dL**. Belum diabetes, tapi sudah di atas normal.
- **Normal** — di bawah ambang Prediabetes di atas.

Diabetes Melitus menang atas Prediabetes: kalau satu hasil sudah memenuhi
ambang diabetes, labelnya Diabetes Melitus walau hasil lain hanya Prediabetes.

**HbA1C tidak dipakai untuk label ini.** Format dirjen tidak mencantumkan
kolom HbA1C di bagian hasil pemeriksaan — HbA1C hanya ada di Follow Up. Di
layar, nilai HbA1C saat CKG tetap ditampilkan di panel detail pasien sebagai
informasi, tapi tidak mengubah Interpretasi.

## 4 · Kapan hasil dianggap tidak valid

Dua kombinasi yang tidak bisa dibaca (catatan format dirjen):

- **GD2PP tanpa GDP** — GD2PP hanya bisa dibaca kalau ada GDP-nya. Kalau GD2PP
  terisi tapi GDP kosong, angka GD2PP itu **tidak dipakai** menyimpulkan.
- **GDS 2 tanpa GDS 1** — GDS 2 adalah pemeriksaan konfirmasi. Tanpa GDS 1,
  angkanya **tidak dipakai** menyimpulkan.

Yang diabaikan hanya angka yang bermasalah, bukan seluruh barisnya. Contoh:
GDS 1 = 150 dan ada GD2PP tanpa GDP → GD2PP diabaikan, GDS 1 tetap dibaca →
**Prediabetes**.

Label **"Tidak dapat diinterpretasikan"** dipakai kalau **tidak ada satu pun**
hasil yang sah tersisa. Pasien seperti itu — tanpa catatan diagnosis — tidak
memenuhi syarat, jadi **tidak muncul di daftar**; labelnya baru terlihat di
file Excel kalau isi selnya diubah sendiri (rumusnya hidup di sana).

## 5 · Cara baca Follow Up

Follow Up mulai **bulan SETELAH** bulan skrining CKG ("kunjungan bulan
berikutnya"). Bulan skrining sendiri tidak diulang karena sudah ada di bagian
hasil pemeriksaan. Kalau pasien datang beberapa kali dalam sebulan, **semua**
kunjungannya ditampilkan berurutan, masing-masing dengan tanggal, hasil, dan
statusnya sendiri.

Status tiap kunjungan:

- **"Pasien DM terkendali (target tercapai)"** — HbA1C **di bawah 7%**, ATAU
  GDP **80–130 mg/dL**, ATAU GD2PP **di bawah 180 mg/dL**.
- **"Pasien DM tidak terkendali (target tidak tercapai)"** — HbA1C **7% ke
  atas**, ATAU GDP **di atas 130 mg/dL**, ATAU GD2PP **180 mg/dL ke atas**.
  GDP **di bawah 80 mg/dL** juga dihitung tidak tercapai, karena gula darah
  terlalu rendah (hipoglikemia) juga bukan kondisi terkendali.
- **"Pasien Missed Visit"** — bulan yang sudah lewat tanpa pemeriksaan gula
  darah sama sekali. Bulan yang belum terjadi dibiarkan kosong.

Kalau ada hasil yang gagal target, statusnya **tidak tercapai** — satu sinyal
gagal cukup, walau hasil lain sudah bagus.

**Kolom GDS di Follow Up tidak menentukan status.** Format dirjen tidak
menetapkan batas target untuk GDS. Jadi kunjungan yang **hanya** punya GDS
(tanpa GDP / GD2PP / HbA1C) dibiarkan **kosong** — bukan berarti gagal.

Kategori **"Loss to Follow Up (LTFU)"** yang ada di legenda format dirjen
belum dipakai di kertas kerja ini: definisinya butuh 12 bulan berturut-turut
tanpa kunjungan, sedangkan kertas kerja ini dihitung per satu tahun pelaporan.

## 6 · Kenapa banyak kolom Follow Up yang kosong

Karena pemeriksaan gula darah **jarang dicatat di ePuskesmas**. Berbeda dengan
tekanan darah yang hampir selalu diukur tiap kunjungan, gula darah hanya
tercatat pada sebagian kecil kunjungan (sekitar 4% kunjungan).

Kolom kosong berarti pemeriksaannya **tidak tercatat** — bukan kesalahan
sistem. Justru inilah yang perlu diperbaiki: makin lengkap pencatatan gula
darah di ePuskesmas, makin berguna kertas kerja ini.

**HbA1C paling sering kosong** — pemeriksaannya jarang tersedia di puskesmas.
Kolomnya tetap disediakan sesuai format dirjen dan akan terisi otomatis begitu
datanya masuk.

## 7 · Dari mana tiap angka diambil (sumber data)

Untuk bagian **hasil pemeriksaan saat CKG**: **ASIK** (data skrining CKG)
adalah sumber utama, **ePuskesmas** mengisi yang kosong — per kolom, jadi satu
pasien bisa punya GDS dari ASIK dan GDP dari ePuskesmas. Di panel detail
pasien ada label kecil **ASIK** / **ePus** yang menunjukkan sumbernya.

Untuk bagian **Follow Up**: selalu dari **ePuskesmas** (kunjungan bulan-bulan
berikutnya memang tercatat di sana).

Identitas (nama, jenis kelamin, tanggal lahir, no. telepon, alamat) juga
ASIK dulu, ePuskesmas mengisi yang kosong.

Tanggal Berkunjung = tanggal kunjungan CKG **paling awal** pada tahun itu.

## 8 · Kolom Jenis Obat — hanya obat diabetes

Hanya obat diabetes yang ditampilkan, sesuai kolom dirjen "List_obat_dm".
Vitamin, antibiotik, obat darah tinggi, dan obat lain sengaja tidak
ditampilkan. Obat pada bagian hasil pemeriksaan = obat pada kunjungan CKG;
obat pada Follow Up = obat pada kunjungan bulan itu.

Golongan yang dikenali (Formularium Nasional untuk puskesmas):

- **Biguanid** — Metformin
- **Sulfonilurea** — Glibenklamid, Glimepirid, Gliklazid, Glipizid, Glikuidon
- **Penghambat alfa-glukosidase** — Akarbose
- **Tiazolidindion** — Pioglitazon, Rosiglitazon
- **Penghambat DPP-4** — Sitagliptin, Vildagliptin, Linagliptin, Saxagliptin,
  Alogliptin
- **Penghambat SGLT-2** — Dapagliflozin, Empagliflozin, Kanagliflozin
- **Agonis GLP-1** — Liraglutid, Semaglutid, Exenatid
- **Insulin** — semua sediaan insulin (Glargine, Aspart, Detemir, dan merek
  seperti Novorapid, Lantus, Levemir, Humalog, Humulin, Actrapid, Apidra)

Kalau obat pasien tidak muncul: pastikan resepnya tercatat di ePuskesmas (atau
peresepan tercatat pada tatalaksana Gula Darah di ASIK), dan obatnya memang
obat diabetes.

## 9 · Dasar aturan

- Ambang diagnosis DM (GDP 126 / GD2PP 200 / GDS 200) dan Prediabetes —
  pedoman skrining dan tata laksana Diabetes Melitus Tipe 2 dewasa, Kemenkes;
  Juknis CKG (KMK 84/2026).
- Target pengendalian (HbA1C <7%, GDP 80–130, GD2PP <180) dan format registri
  — dokumen dirjen "Register Sheet Pasien HT, DM, Dislipidemia dan Obesitas",
  sheet "Diabetes Melitus".
- Daftar obat diabetes di puskesmas — Formularium Nasional (KMK 1199/2025).
