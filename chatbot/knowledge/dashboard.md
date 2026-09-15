# Halaman Dashboard Hipertensi

Halaman **Dashboard** menampilkan **8 grafik analisis Registri Hipertensi CKG**
untuk **satu puskesmas** yang dipilih. Grafik 1–6 hanya menghitung **pasien
CKG** — pasien yang kunjungannya cocok di **ePuskesmas DAN ASIK** dan memenuhi
**syarat hipertensi** (punya riwayat diagnosis hipertensi **ATAU** rerata tensi
di atas normal saat skrining CKG) — persis populasi yang sama dengan halaman
**Registri Hipertensi CKG**.

**Grafik 7 dan 8 memakai populasi awal yang BEDA**, lihat masing-masing
bagiannya di bawah — bukan cacat, memang disengaja oleh klien.

Cara pakai: pilih puskesmas dulu di kolom **"Puskesmas"** di atas; grafik baru
muncul setelah puskesmas dipilih. Tidak ada tampilan gabungan semua puskesmas —
satu puskesmas per tampilan.

**Rentang waktu:** perhitungan selalu dihitung dari **Februari 2025** sampai
**bulan berjalan** (bulan kalender sekarang). Grafik garis/area **menampilkan 12
bulan terakhir**, tetapi angkanya tetap memperhitungkan data sejak Feb 2025.

**Label angka (Grafik 2–5):** tiap titik pada grafik garis/area diberi label
angka langsung di grafik, jadi tidak perlu mengarahkan kursor. Bulan yang
angkanya **0 tidak diberi label** supaya grafik tetap mudah dibaca. Arahkan
kursor ke titik untuk melihat tooltip rinciannya.

**Istilah kunci yang dipakai semua grafik:**
- **Pasien Hipertensi** = pasien di Registri Hipertensi CKG (unik per NIK).
- **Tertatalaksana** = pasien yang **pernah diberi obat antihipertensi** — kapan
  saja sejak 2025, baik pada kunjungan CKG (kolom Jenis Obat) maupun pada
  kunjungan bulanan berikutnya (sumber: resep ePuskesmas / peresepan tatalaksana
  ASIK, hanya obat darah tinggi).
- **Terkendali (bulan tertentu)** = pada bulan itu ada **minimal satu** hasil
  pemeriksaan tensi dengan **sistolik < 140 DAN diastolik < 90**. Kalau ada
  beberapa kunjungan dalam sebulan dan **salah satunya** terkendali → dihitung
  terkendali.
- **Tidak terkendali (bulan tertentu)** = ada hasil tensi bulan itu tetapi tidak
  ada yang terkendali (**sistolik ≥ 140 ATAU diastolik ≥ 90**).
- **Tidak berkunjung (bulan tertentu)** = tidak ada hasil pemeriksaan tensi sama
  sekali pada bulan itu.

## Grafik 1 — Cascade Hipertensi (bulan berjalan)

Tiga batang berurutan untuk **bulan berjalan**:
1. **Pasien Hipertensi** — total pasien di registri (jadi acuan 100%).
2. **Tertatalaksana** — dari nomor 1, yang pernah diberi obat antihipertensi.
3. **Target Tercapai** — dari yang tertatalaksana, yang tensinya **terkendali
   (< 140 dan < 90)** pada bulan berjalan.

Tiap batang menampilkan **angka absolut** dan **persentase terhadap batang 1**
(total pasien hipertensi). Batang 1 tidak diberi persentase (ia acuannya).

## Grafik 2 — Pasien Hipertensi Tertatalaksana (12 bulan)

Dua garis, keduanya menggambar **angka absolut** yang kumulatif (menumpuk).

- **Pasien Hipertensi Kumulatif** — jumlah unik pasien teregistrasi sampai bulan
  itu. Angkanya tertulis **di atas** tiap titik.
- **Pasien Tertatalaksana** — jumlah unik pasien yang sudah pernah diberi obat
  sampai bulan itu. Angkanya tertulis **di bawah** tiap titik, dengan
  **persentase terhadap garis Kumulatif** di bawah angka itu.

Angka ditulis di atas dan di bawah supaya kedua label tidak bertumpuk saat kedua
garis hampir berimpit (cakupan mendekati 100%).

**Sumbu Y grafik ini angka absolut** (jumlah pasien), bukan persentase. Kedua
garis karena itu **tidak pernah turun** — keduanya kumulatif, dan pasien yang
sudah pernah diberi obat tetap terhitung tertatalaksana di bulan-bulan
berikutnya. Garis Tertatalaksana selalu berada di bawah atau berimpit dengan
garis Kumulatif; jaraknya adalah pasien yang belum pernah diberi obat.

**Persentasenya bisa turun walaupun garisnya naik.** Rasio tertatalaksana ÷
kumulatif (yang muncul sebagai keterangan kecil di bawah tiap titik
Tertatalaksana, di tooltip, dan sebagai angka besar di kartu) membandingkan dua
angka yang sama-sama naik. Kalau bulan ini pasien baru masuk registri lebih
banyak daripada pasien yang mulai diberi obat, persentasenya turun walaupun
**jumlah** pasien tertatalaksana tetap bertambah. Contoh: Januari 10 dari 20
pasien = 50%; Februari 12 dari 40 pasien = 30%. Jadi persentase yang turun
**tidak** berarti ada pasien yang kehilangan obat.

Bulan-bulan **sebelum puskesmas punya pasien teregistrasi pertama** tidak
digambar sama sekali. Grafik mulai dari bulan registrasi pertama.

Di pojok kanan atas kartu grafik ini ada tombol **"Lihat Detail"**. Tombol itu
membuka halaman **Gap Tatalaksana**, yang menampilkan daftar pasien di jarak
antara kedua garis tadi — yaitu pasien hipertensi yang belum pernah tercatat
diberi obat antihipertensi — lengkap dengan no telp dan alamat untuk
ditindaklanjuti. Puskesmas yang sedang dipilih di Dashboard ikut terbawa ke
halaman itu.

## Grafik 3 — Pasien Hipertensi Target Tercapai (area, 12 bulan)

Dari **pasien tertatalaksana** sampai bulan itu, jumlah yang tensinya
**terkendali** pada bulan itu. Persentasenya dihitung terhadap jumlah
tertatalaksana bulan itu. Tiap titik diberi label **angka** dengan
**persentase** di bawahnya.

## Grafik 4 — Pasien Hipertensi Target Tidak Tercapai (area, 12 bulan)

Dari pasien tertatalaksana, jumlah yang tensinya **tidak terkendali** pada bulan
itu.

## Grafik 5 — Pasien Hipertensi Tidak Berkunjung (area, 12 bulan)

Dari pasien tertatalaksana, jumlah yang **tidak punya hasil pemeriksaan tensi**
pada bulan itu. **Penting:** angka ini hanya akurat kalau **semua tanggal
kunjungan sudah diambil (scrape) sistem**. Kalau ada tanggal kunjungan yang
belum terambil, pasien bisa terhitung "tidak berkunjung" padahal sebenarnya
datang — jadi anggap grafik ini sebagai batas atas.

Grafik 3, 4, dan 5 saling melengkapi: untuk tiap bulan, jumlah **Tercapai +
Tidak Tercapai + Tidak Berkunjung = jumlah pasien tertatalaksana** bulan itu.
Yang dijamin persis adalah **angkanya**, bukan persentasenya: tiap persentase
dibulatkan sendiri-sendiri, jadi kalau ketiga persentase dijumlahkan hasilnya
bisa 99% atau 101%. Itu efek pembulatan, bukan data yang salah.

Pada ketiga grafik area ini **sumbu Y adalah persentase (0%–100%, kelipatan
25%)** terhadap jumlah tertatalaksana bulan itu — jadi bentuk kurvanya mengikuti
persentase, bukan angka absolut. Angka absolutnya tetap ditampilkan di label tiap
titik dan di tooltip.

## Judul kartu keempat grafik garis (Grafik 2–5)

Di bawah judul tiap kartu grafik garis/area ada dua baris ringkasan yang memakai
angka **bulan terakhir yang tampil** (bulan paling kanan pada grafik):
- Baris pertama: **persentase** bulan terakhir, dicetak besar dan berwarna sama
  dengan garis grafiknya. Untuk Grafik 2 persentase itu terhadap Pasien
  Hipertensi Kumulatif; untuk Grafik 3–5 terhadap jumlah tertatalaksana.
- Baris kedua: **angka absolut** bulan terakhir diikuti keterangan singkat metrik
  grafik itu, misalnya "599 pasien hipertensi tertatalaksana" pada Grafik 2, atau
  "150 pasien dengan tekanan darah <140/90" pada Grafik 3.

Contoh: kartu "Pasien Hipertensi Tertatalaksana" menampilkan "25%" lalu "599
pasien hipertensi tertatalaksana" — artinya di bulan terakhir ada 599 pasien
tertatalaksana, yaitu 25% dari seluruh pasien hipertensi kumulatif.

## Grafik 6 — Proporsi Target Tercapai (batang, CKG 2025 → 2026)

Empat batang:
1. **Hipertensi CKG 2025** — pasien di registri hipertensi tahun 2025 (acuan 100%).
2. **Diperiksa CKG 2026** — dari nomor 1, yang **juga masuk registri hipertensi
   2026** (dipadankan per NIK).
3. **Terkendali CKG 2026** — dari nomor 2, yang tensinya **terkendali saat
   skrining CKG 2026** (rerata TD < 140 dan < 90 pada kunjungan CKG-nya).
4. **Terkendali (bulan berjalan)** — dari nomor 2, yang tensinya terkendali pada
   **bulan berjalan** (labelnya mengikuti bulan sekarang).

Persentase batang 2–4 dihitung terhadap batang 1 (Hipertensi CKG 2025).

## Grafik 7 — Hipertensi 2 Tahun Berturut-turut (batang bertumpuk, CKG 2025 → 2026)

**Populasi Batang 1 di sini BUKAN "Registri Hipertensi CKG 2025"** seperti
Grafik 6 — populasinya lebih sempit: **hipertensi murni oleh hasil ukur**
(rerata TD ≥140/90 saat skrining CKG 2025), tanpa memandang riwayat diagnosis.
Jadi pasien yang berlabel "Hipertensi" di Registri **hanya karena riwayat**
(sudah pernah didiagnosis) tapi tensinya saat itu sebenarnya normal/di bawah
140/90, **tidak dihitung** di grafik ini — beda dengan Grafik 6.

Empat batang:
1. **Hipertensi CKG 2025** — pasien dengan rerata TD ≥140/90 saat skrining CKG
   2025 (acuan 100%).
2. **Diperiksa CKG 2026** — dari nomor 1, yang juga punya kunjungan skrining
   CKG di 2026 (dipadankan per NIK), berapa pun hasil tensinya di 2026.
3. **Hipertensi 2026 — Ya/Tidak** — dari nomor 2, dipecah dua warna dalam satu
   batang: **Ya** (merah) = rerata TD saat skrining CKG 2026 masih ≥140/90;
   **Tidak** (hijau) = sudah terkendali (<140/90).
4. **Diobati** — dipecah **empat** warna, masing-masing dari salah satu warna
   nomor 3 (bukan dari total nomor 2): **Ya-Diobati** (merah tua) dan
   **Ya-Tidak Diobati** (merah muda) dari pasien TD 2026 masih ≥140/90;
   **Tidak-Diobati** (hijau tua) dan **Tidak-Tidak Diobati** (hijau muda) dari
   pasien yang sudah terkendali. "Diobati" = pernah diberi obat antihipertensi
   kapan saja sejak 2025.

Angka di atas batang hanya muncul di batang hitungan populasi — Hipertensi CKG
2025, Diperiksa CKG 2026, dan Hipertensi CKG 2026 — = jumlah pasien batang itu.
Batang yang dipecah dua/empat warna (Ya/Tidak, Diobati) TIDAK diberi angka di
atasnya, karena totalnya cuma mengulang batang sebelumnya; rincian jumlah per
warnanya muncul di kotak info melayang saat batang diarahkan kursor/disentuh,
dengan teks berwarna sesuai warna segmennya.

## Grafik 8 — Hipertensi CKG 2026 (batang bertumpuk)

Sama seperti Grafik 7, **Batang 1 di sini memakai populasi "hipertensi murni
oleh hasil ukur"** (rerata TD ≥140/90 saat skrining CKG 2026), BUKAN populasi
Registri Hipertensi CKG 2026 penuh — pasien Pre-Hipertensi (130–139/85–89)
tidak termasuk di grafik ini sama sekali.

Tiga batang:
1. **Hipertensi CKG 2026** — pasien dengan rerata TD ≥140/90 saat skrining CKG
   2026 (acuan 100%).
2. **Kategori Pasien — Pasien Baru/Sudah Hipertensi** — dari nomor 1, dipecah
   dua warna: **Pasien Baru** (ungu) = tidak punya riwayat diagnosis hipertensi
   sebelumnya (baru ketahuan lewat tensi tinggi di skrining ini); **Sudah
   Hipertensi** (biru muda) = punya riwayat diagnosis (termasuk pasien yang
   riwayatnya baru dilaporkan sendiri di skrining 2026 ini walau belum pernah
   tercatat di registri 2025 — tetap dihitung "Sudah Hipertensi", bukan "Pasien
   Baru", karena secara medis dia bukan kasus baru).
3. **Diobati** — dipecah **empat** warna, masing-masing dari salah satu warna
   nomor 2 (bukan dari total nomor 1): **Pasien Baru-Diobati** (ungu tua) dan
   **Pasien Baru-Tidak Diobati** (ungu muda); **Sudah Hipertensi-Diobati**
   (biru tua) dan **Sudah Hipertensi-Tidak Diobati** (biru muda). "Diobati" =
   obat antihipertensi kapan saja sejak 2025, sama seperti Grafik 7 batang 4.

## Arti tulisan status di layar

- **"Computed <tanggal jam> · cached/fresh"** = kapan angka grafik terakhir
  dihitung. Hasil disimpan sementara (**cache ~30 jam**) dan dihitung ulang
  otomatis tiap pagi ~05.00 WIB, jadi perubahan data ePuskesmas/ASIK baru
  terlihat paling lambat besok pagi.
- **"Pilih puskesmas untuk menampilkan grafik."** = belum ada puskesmas dipilih.
- **"Menghitung…"** = angka puskesmas itu sedang dihitung di latar belakang
  (perhitungan pertama bisa agak lama karena membuka data terenkripsi). Muncul
  **bilah kemajuan** dengan perkiraan jumlah pasien yang sudah diproses (mis.
  "12.345/28.900 · 43%"), supaya jelas perhitungan memang berjalan — angkanya
  perkiraan. Halaman terisi sendiri saat selesai.
- **"Gagal memuat data."** = gangguan sesaat; coba muat ulang halaman.

## Catatan penting

- Grafik hanya menghitung **pasien CKG** (terpadan ePuskesmas + ASIK). Pasien
  yang datanya hanya di salah satu sumber tidak ikut terhitung — sama seperti
  Registri Hipertensi CKG.
- Angka **obat** hanya sebesar yang tercatat di ePuskesmas/ASIK. Kalau resep
  tidak dicatat, pasien tidak terhitung "tertatalaksana".
