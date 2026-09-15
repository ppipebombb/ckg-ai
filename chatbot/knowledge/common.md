# Tentang Aplikasi Ini & Asal Data

## Apa aplikasi ini

Dashboard pemantauan hasil skrining **CKG (Cek Kesehatan Gratis)**. Aplikasi
ini menampilkan laporan agregat dan kertas kerja (registri) per puskesmas —
dihitung otomatis dari data kunjungan pasien yang sudah tercatat di sistem
puskesmas. Aplikasi ini **hanya membaca dan merangkum** data; tidak ada input
data di sini.

## Dua sumber data

1. **ePuskesmas (ePus)** — rekam medis elektronik puskesmas. Dari sini diambil:
   data kunjungan, identitas pendaftaran (NIK, nama, tanggal lahir, alamat,
   no. HP), tanda vital (termasuk tekanan darah dari pemeriksaan fisik),
   diagnosis (kode ICD-10 dan penyakit khusus), resep obat, dan formulir PTM.
2. **ASIK** — aplikasi Sehat IndonesiaKu (Kemenkes), tempat hasil skrining CKG
   dicatat. Dari sini diambil: jawaban kuesioner skrining (misalnya *"Apakah
   Anda pernah dinyatakan tekanan darah tinggi?"*) dan pengukuran tambahan
   (misalnya tekanan darah pengukuran ke-2). Termasuk dua bagian: **Pelayanan
   oleh Nakes** (diisi tenaga kesehatan) dan **Pemeriksaan Mandiri** (kuesioner
   yang diisi sendiri oleh pasien).

Keduanya kemudian **digabung (merge)** dengan aturan tetap: untuk nilai
pemeriksaan/kuesioner, bila nilainya berbeda **nilai ePuskesmas yang dipakai**
dan ASIK mengisi bagian yang kosong. **Khusus identitas pasien** (NIK, nama,
tanggal lahir, tempat lahir, jenis kelamin, alamat) justru sebaliknya: **nilai
ASIK yang dipakai**, ePuskesmas hanya mengisi bila ASIK kosong. Hasil gabungan
inilah yang menjadi dasar laporan.

## Apa arti pasien "CKG" di laporan

Seorang pasien dihitung sebagai **pasien CKG** ketika kunjungan yang sama
ditemukan di **kedua** sumber (ePuskesmas DAN ASIK) — artinya dia benar-benar
menjalani skrining CKG dan hasilnya tercatat lengkap. Registri (kertas kerja)
hanya dibangun dari pasien CKG. **Pengecualian:** registri **Bayi Kuning
(ikterus)** murni dari ePuskesmas dan **tidak** mensyaratkan pasien CKG — bayi
masuk berdasarkan adanya penilaian ikterus MTBM, bukan keanggotaan CKG.

Akibatnya, pasien yang datanya **hanya ada di salah satu sumber** (ePus saja
atau ASIK saja, belum cocok) **tidak muncul** di registri/laporan CKG — ini
sebab paling umum kalau "pasien saya kok tidak ada di daftar".

## Bagaimana data masuk ke sini

- Sistem mengambil data dari portal ePuskesmas dan ASIK untuk tiap puskesmas
  secara berkala (otomatis/terjadwal), memakai akun resmi puskesmas yang
  tersimpan **terenkripsi**.
- Laporan **tidak** membaca portal secara langsung saat halaman dibuka —
  laporan dihitung dari data hasil pengambilan terakhir.

## Kesegaran data — kenapa angkanya "kemarin"?

- Hasil perhitungan laporan disimpan sementara (**cache sekitar 30 jam**) agar
  halaman cepat dibuka, dan **dihitung ulang otomatis setiap pagi sekitar
  pukul 05.00 WIB** dari data terbaru.
- Akibatnya: perbaikan data di ePuskesmas/ASIK baru terlihat di laporan
  setelah pengambilan data dan perhitungan berikutnya — **paling lambat besok
  pagi**.
- Di halaman registri ada keterangan **"Computed <waktu> · cached/fresh"** =
  kapan angka itu dihitung. Tulisan **"Loading registri hipertensi…"**,
  **"Loading registri diabetes melitus…"**, **"Loading registri
  dislipidemia…"**, atau **"Loading registri obesitas…"** berarti
  perhitungan sedang berjalan di latar belakang — halaman akan terisi sendiri
  dalam beberapa saat (perhitungan pertama bisa agak lama karena sistem
  membuka data terenkripsi satu per satu). Saat berjalan muncul **bilah
  kemajuan** dengan perkiraan persentase pasien yang sudah diproses (angka
  perkiraan).

## Memperbaiki data yang salah

- **Identitas salah** (nama, tanggal lahir, alamat, no. HP): identitas mengikuti
  data **ASIK** (ePuskesmas hanya mengisi bila ASIK kosong) → perbaiki di ASIK;
  bila fieldnya memang hanya ada di ePuskesmas, perbaiki di ePuskesmas. Laporan
  akan ikut benar setelah data diperbarui (paling lambat besok pagi).
- **Tensi / gula darah / obat tidak muncul**: laporan hanya bisa menampilkan
  yang tercatat di ePuskesmas pada kunjungan itu. Pastikan hasil ukur dan resep
  dicatat di ePuskesmas.

## Halaman yang tersedia

Di menu samping ada **sebelas** halaman (menu **Dashboard**, menu **Patients**,
menu **Registri Hipertensi CKG**, dan menu **Registri PJB-K** masing-masing
punya beberapa sub-halaman):

- **Dashboard › Hipertensi** — 8 grafik analisis Registri Hipertensi CKG untuk
  satu puskesmas yang dipilih (Hipertensi 2 Tahun Berturut-turut, Hipertensi
  CKG 2026, cascade, tren tertatalaksana, target tercapai/tidak tercapai, tidak
  berkunjung, dan proporsi terkendali CKG 2025 → 2026).
- **Dashboard › Diabetes Melitus** — 2 grafik kohort untuk satu puskesmas yang
  dipilih (Diabetes Melitus 2 Tahun Berturut-turut dan Diabetes Melitus CKG
  2026).
- **Patients › CKG Umum** — daftar dan detail data pasien per orang (gabungan
  ePuskesmas + ASIK), hanya untuk dilihat. Bisa dicari dan disaring (nama/NIK,
  tanggal, status pencocokan, umur, puskesmas).
- **Patients › CKG Sekolah** — daftar dan detail siswa hasil pemeriksaan kesehatan
  anak sekolah (dari modul anak sekolah ASIK), ditata per sekolah × kelas, hanya
  untuk dilihat. Bisa disaring (nama/NIK, sekolah, kelas, status pemeriksaan,
  umur, tahun ajaran, puskesmas).
- **Registri Hipertensi CKG › Registri Hipertensi CKG** — kertas kerja
  hipertensi per puskesmas + tahun (format dirjen V8juni2026), bisa diexport ke
  Excel.
- **Registri Hipertensi CKG › Gap Tatalaksana** — daftar pasien hipertensi yang
  belum pernah tercatat diberi obat antihipertensi, lengkap dengan no telp dan
  alamat untuk ditindaklanjuti. Bisa disaring per puskesmas, tahun masuk
  registri, dan pencarian nama/NIK, serta diexport ke Excel.
- **Registri Diabetes Melitus CKG** — kertas kerja diabetes melitus per
  puskesmas + tahun (format dirjen, sheet "Diabetes Melitus"): hasil
  pemeriksaan gula darah saat kunjungan CKG dan follow-up gula darah per
  bulan, bisa diexport ke Excel.
- **Registri Dislipidemia CKG** — kertas kerja dislipidemia per puskesmas +
  tahun (format dirjen, sheet "Dislipidemia"): hasil pemeriksaan profil lipid
  (Kolesterol Total, LDL, HDL, Trigliserida) saat kunjungan CKG dan follow-up
  pada bulan kontrol **per 3 bulan** (bukan per bulan seperti dua registri
  lainnya), bisa diexport ke Excel.
- **Registri Obesitas CKG** — kertas kerja obesitas per puskesmas + tahun
  (format dirjen, sheet "Obesitas"): hasil pemeriksaan antropometri (berat
  badan, tinggi badan, dan IMT yang dihitung dari keduanya) saat kunjungan CKG
  dan follow-up berat badan pada bulan kontrol **3–6 bulan setelah CKG**, bisa
  diexport ke Excel.
- **Registri PJB-K › Bayi Kuning - Ikterus** — daftar bayi baru lahir dengan
  klasifikasi ikterus MTBM "Ikterus" atau "Ikterus berat" (hanya dari
  ePuskesmas, bukan syarat CKG), lengkap dengan pemantauan kunjungan berikutnya;
  bisa diexport ke Excel.
- **Registri PJB-K › Bayi Kuning - Ikterus Berat** — sama, tetapi hanya bayi
  dengan klasifikasi "Ikterus berat" (kuning < 24 jam, atau > 14 hari, atau
  sampai telapak tangan/kaki). Sheet PJBK belum tersedia.

## Yang TIDAK bisa dijawab asisten ini

- **Data atau angka nyata** — baik data pasien perorangan (nama, NIK, hasil
  ukur) maupun rekap/angka milik puskesmas tertentu (jumlah pasien, total per
  puskesmas, daftar pasien). Asisten ini sengaja tidak diberi akses data apa pun
  (demi privasi & sesuai perannya); angka konkret ada di dashboard/registri di
  layar. Yang bisa dijawab hanya aturan, rumus, dan cara membacanya.
- **Mengubah / memperbaiki data** — lakukan di ePuskesmas/ASIK.
- **Saran medis atau diagnosis** — tanyakan ke tenaga kesehatan.
