# Halaman Registri Dislipidemia CKG (Kertas Kerja Dislipidemia)

Kertas kerja dislipidemia per **satu puskesmas + satu tahun pelaporan**,
mengikuti format registri dirjen (dokumen *"Register Sheet Pasien HT, DM,
Dislipidemia dan Obesitas"*, sheet **"Dislipidemia"**). Isinya: identitas
pasien, hasil pemeriksaan **profil lipid** (lemak darah) pada tanggal
berkunjung CKG, dan follow-up profil lipid pada **bulan kontrol (per 3
bulan)**. Bisa diexport ke **Excel** — di file export, rumus tertanam langsung
di sel (klik sel Interpretasi untuk melihatnya), dan ada sheet **"Formula &
Logika"** berisi penjelasan yang sama dengan kartu **"Cara Membaca Kertas Kerja
Ini"** di halaman.

Halaman ini bersaudara dengan Registri Hipertensi dan Registri Diabetes
Melitus: sumber datanya sama (kunjungan CKG yang sama), tapi yang ditampilkan
panel lemak darah (Kolesterol Total / LDL / HDL / Trigliserida).

**Cara pakai halaman:** pilih Puskesmas + Tahun Pelaporan (pilihan tahun =
tahun ini sampai 5 tahun ke belakang), lalu cari nama/NIK bila perlu. Klik
baris pasien untuk membuka detail (no. telepon, alamat, obat, sumber data, dan
tabel Follow Up per bulan). Daftarnya dibagi **20 pasien per halaman**.

Keterangan di atas tabel berbunyi: **"N pasien (CKG) · Kolesterol Total tinggi
… · LDL tinggi … · HDL rendah … · Trigliserida tinggi …"**. **Keempat angka itu
saling tumpang tindih dan TIDAK dijumlahkan menjadi total** — syaratnya "salah
satu dari empat", jadi satu pasien yang Kolesterol Total-nya tinggi DAN HDL-nya
rendah terhitung di dua kategori sekaligus. Di layar hal ini ditulis apa adanya:
*(satu pasien bisa terhitung di lebih dari satu kategori)*. Ini berbeda dari
Registri Hipertensi dan Diabetes Melitus, yang rinciannya memang menjumlah jadi
total — sheet Dislipidemia tidak punya kategori tengah seperti "Pre-Hipertensi"
atau "Prediabetes", jadi tidak ada yang bisa dibelah dua.

Kolom **"Follow-up"** di tabel utama berisi **angka** = jumlah baris Follow Up
pasien itu — gabungan kunjungan yang ada hasil lipidnya **dan** bulan kontrol
berstatus **Missed Visit**. Rinciannya muncul saat baris pasien diklik.

Saat perhitungan pertama berjalan muncul tulisan **"Loading registri
dislipidemia…"** beserta bilah kemajuan; hasilnya lalu disimpan (cache ±30 jam)
dan dihitung ulang otomatis tiap pagi. Keterangan **"Computed &lt;waktu&gt; ·
cached/fresh"** menunjukkan kapan angka itu dihitung.

## Inti — satu daftar, dua pertanyaan

Kolom hasil pemeriksaan menjawab: **bagaimana profil lemak darah pasien SAAT
skrining CKG?** Kolom Follow Up menjawab: **pada kontrol berikutnya, apakah
sudah mencapai target?** Karena pertanyaannya berbeda, labelnya bisa berbeda —
dan itu memang benar, bukan error.

## 1 · Arti singkatan

- **Kolesterol Total** — jumlah seluruh kolesterol dalam darah.
- **LDL** — kolesterol "jahat"; makin tinggi makin berisiko menyumbat pembuluh
  darah.
- **HDL** — kolesterol "baik"; makin **tinggi** makin bagus. Karena itu batasnya
  terbalik dari yang lain: yang bermasalah justru kalau nilainya **rendah**.
- **Trigliserida** — jenis lemak lain dalam darah, ikut naik kalau pola makan
  tinggi gula dan lemak.

Semua dalam satuan mg/dL.

## 2 · Siapa yang masuk daftar ini (Syarat)

Pasien (per NIK) masuk daftar jika punya **minimal satu kunjungan CKG**
(kunjungan yang tercatat di ePus DAN ASIK) pada tahun itu, **DAN** hasil
pemeriksaan lemak darahnya memenuhi **salah satu** ambang berikut:

- **Kolesterol Total 200 mg/dL ke atas**; ATAU
- **LDL 130 mg/dL ke atas**; ATAU
- **HDL di bawah 40 mg/dL**; ATAU
- **Trigliserida di ATAS 150 mg/dL**.

Cukup satu saja yang memenuhi. Perhatikan Trigliserida: tepat **150 mg/dL masih
dihitung normal**, 151 mg/dL baru dihitung tinggi. Tiga ambang lainnya bersifat
"sama dengan atau lebih" (tepat 200 sudah dihitung tinggi, tepat 130 sudah
dihitung tinggi, tepat 40 masih dihitung normal).

**Kolom "Riwayat diagnosis HT" dan "Riwayat diagnosis DM" hanya informasi,
bukan syarat masuk.** Kedua kolom itu ditampilkan supaya terlihat pasien mana
yang punya penyakit penyerta, tapi **tidak** menentukan siapa yang masuk
daftar. Yang menentukan hanya **pengukuran** lemak darahnya. Pasien dengan LDL
tinggi tetap masuk daftar walaupun belum pernah didiagnosis hipertensi maupun
diabetes.

**Yang tidak ditampilkan:** pasien yang keempat nilainya masih dalam batas
normal, dan pasien yang memang belum diperiksa lemak darahnya.

Kalau seorang pasien "hilang" dari daftar, urutan pemeriksaannya: (a) apakah
kunjungannya sudah cocok di kedua sumber (pasien CKG)? (b) apakah lemak
darahnya memang sudah diperiksa? (c) kalau sudah, apakah keempat nilainya
memang normal?

## 3 · Arti label Interpretasi (saat kunjungan CKG)

- **Dislipidemia** — ada minimal **satu** nilai yang melewati ambang di bagian
  2.
- **Normal** — lemak darah sudah diperiksa dan keempat nilainya masih dalam
  batas.
- **Kosong** — belum ada satu pun hasil pemeriksaan lemak darah pada kunjungan
  itu. Kosong **bukan** berarti normal.

Karena syaratnya di bagian 2, praktis semua baris yang tampil di halaman ini
berlabel **Dislipidemia**. Label **Normal** dan kosong baru terlihat di file
Excel kalau isi selnya diubah sendiri (rumusnya hidup di sana).

**Beda penting dari Registri Hipertensi dan Diabetes Melitus:** di dua kertas
kerja itu, pasien yang sudah punya diagnosis SELALU diberi label penyakitnya
walaupun hasil ukur hari itu bagus. **Di sini tidak.** Label di sini mengikuti
hasil **pengukuran**, karena daftar ini memang disusun dari pengukuran, bukan
dari riwayat diagnosis.

## 4 · Cara baca Follow Up

Follow Up mulai **bulan SETELAH** bulan skrining CKG. Bulan skrining sendiri
tidak diulang karena sudah ada di bagian hasil pemeriksaan.

**Kontrolnya dijadwalkan tiap 3 bulan.** Format dirjen menilai target "pada
kunjungan **3 bulan** berikutnya", jadi bulan kontrol pasien adalah **3, 6, 9,
dan 12 bulan** setelah bulan skrining CKG-nya. Contoh: pasien yang skrining CKG
pada Januari punya bulan kontrol April, Juli, Oktober, dan (kalau tahunnya
sudah lewat) Januari tahun berikutnya — yang di luar tahun pelaporan tidak
ditampilkan.

Ini **berbeda** dari Registri Hipertensi dan Registri Diabetes Melitus yang
kontrolnya **bulanan**. Jangan samakan.

Status tiap kunjungan:

- **"Pasien Dislipidemia terkendali (target tercapai)"** — Kolesterol Total di
  bawah 200, DAN LDL di bawah 130, DAN HDL 40 ke atas, DAN Trigliserida 150 ke
  bawah. Semua nilai yang terisi harus dalam batas.
- **"Pasien Dislipidemia tidak terkendali (target tidak tercapai)"** — ada
  minimal **satu** nilai yang masih melewati ambang. Satu nilai yang masih di
  luar batas sudah cukup, walaupun nilai lain sudah bagus.
- **"Pasien Missed Visit"** — **hanya muncul di bulan kontrol** (3/6/9/12 bulan
  setelah skrining) yang tidak punya satu pun hasil pemeriksaan lemak darah.

**Bulan di ANTARA jadwal kontrol sengaja dibiarkan kosong**, bukan ditandai
Missed Visit — memang tidak ada kontrol yang dijadwalkan di bulan itu, jadi
tidak adil kalau dihitung terlewat. Bulan yang belum terjadi juga dibiarkan
kosong.

Kalau pasien diperiksa beberapa kali dalam sebulan, **semua** kunjungannya
ditampilkan berurutan, masing-masing dengan tanggal, hasil, dan statusnya
sendiri. Pemeriksaan di luar bulan kontrol tetap dicatat dan tetap dinilai.

Kunjungan yang datang tapi **tidak memeriksa lemak darah sama sekali** tidak
muncul sebagai baris Follow Up: yang dinilai di sini adalah kontrol *lipid*,
bukan kunjungan pada umumnya. Konsekuensinya, kalau kunjungan itu jatuh di bulan
kontrol dan tidak ada satu pun nilai lipid, bulan itu tetap ditandai **"Pasien
Missed Visit"** walaupun pasiennya datang — yang terlewat adalah *pemeriksaan
lipidnya*, bukan kunjungannya. Di bulan non-kontrol, kunjungan seperti itu
sekadar tidak ditampilkan.

Kategori **"Loss to Follow Up (LTFU)"** yang ada di legenda format dirjen belum
dipakai di kertas kerja ini: definisinya butuh 12 bulan berturut-turut tanpa
kunjungan, sedangkan kertas kerja ini dihitung per satu tahun pelaporan.

## 5 · Kenapa banyak kolom Follow Up yang kosong

Karena pemeriksaan lemak darah **jarang dilakukan**. Di CKG, paket pemeriksaan
profil lipid hanya disediakan untuk **usia 40 tahun ke atas DAN penyandang
hipertensi dan/atau diabetes**. Di luar itu, ePuskesmas jarang mencatat
pemeriksaan lemak darah pada kunjungan biasa.

Kolom kosong berarti pemeriksaannya **tidak tercatat** — bukan kesalahan
sistem. Justru inilah yang perlu diperbaiki: makin lengkap pencatatannya, makin
berguna kertas kerja ini.

## 6 · Dari mana tiap angka diambil (sumber data)

Untuk bagian **hasil pemeriksaan saat CKG**: **ASIK** (data skrining CKG)
adalah sumber utama, **ePuskesmas** mengisi yang kosong — per kolom, jadi satu
pasien bisa punya Kolesterol Total dari ASIK dan Trigliserida dari ePuskesmas.
Di panel detail pasien ada label kecil **ASIK** / **ePus** yang menunjukkan
sumbernya.

Untuk bagian **Follow Up**: selalu dari **ePuskesmas** (kunjungan bulan-bulan
berikutnya memang tercatat di sana).

Identitas (nama, jenis kelamin, tanggal lahir, no. telepon, alamat) juga ASIK
dulu, ePuskesmas mengisi yang kosong.

Tanggal Berkunjung = tanggal kunjungan CKG **paling awal** pada tahun itu.

Kolom Riwayat HT dan Riwayat DM memakai catatan diagnosis yang sama persis
dengan yang dipakai Registri Hipertensi dan Registri Diabetes Melitus, jadi
artinya konsisten antar halaman: jawaban skrining CKG di ASIK, diagnosis pada
tatalaksana di ASIK, atau diagnosis di ePuskesmas. Cukup salah satu; sekali
tercatat, tetap **Ya**.

## 7 · Kolom Jenis Obat — hanya obat penurun lemak darah

Hanya obat penurun lemak darah yang ditampilkan, sesuai kolom dirjen "List Obat
Dislipidemia". Vitamin, antibiotik, obat darah tinggi, obat diabetes, dan obat
lain sengaja tidak ditampilkan. Obat pada bagian hasil pemeriksaan = obat pada
kunjungan CKG; obat pada Follow Up = obat pada kunjungan bulan itu.

Golongan yang dikenali (Formularium Nasional untuk puskesmas):

- **Statin** — Simvastatin, Atorvastatin, Rosuvastatin, Pravastatin,
  Lovastatin, Fluvastatin
- **Fibrat** — Gemfibrozil, Fenofibrat
- **Penghambat penyerapan kolesterol** — Ezetimib
- **Pengikat asam empedu** — Kolestiramin (Cholestyramine)

Kalau obat pasien tidak muncul: pastikan resepnya tercatat di ePuskesmas (atau
peresepan tercatat pada tatalaksana lipid di ASIK), dan obatnya memang obat
penurun lemak darah.

## 8 · Dasar aturan

- Ambang Dislipidemia (Kolesterol Total 200 / LDL 130 / HDL 40 / Trigliserida
  150) dan kategori evaluasi — dokumen dirjen "Register Sheet Pasien HT, DM,
  Dislipidemia dan Obesitas", sheet "Dislipidemia".
- Jadwal kontrol 3 bulan — legenda pada sheet yang sama.
- Paket pemeriksaan profil lipid di CKG ("POCT Lipid Panel", usia ≥40 tahun dan
  penyandang HT dan/atau DM) — Juknis CKG (KMK 84/2026).
- Daftar obat penurun lemak darah di puskesmas — Formularium Nasional
  (KMK 1199/2025).
