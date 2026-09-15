# Halaman CKG Sekolah (School Patients)

Halaman **CKG Sekolah** menampilkan daftar dan detail **siswa hasil pemeriksaan
kesehatan anak sekolah** (CKG di sekolah), dikelompokkan **per sekolah dan per
kelas**. Halaman ini **hanya untuk dilihat** (read-only): tidak ada tombol ubah
data, scrape ulang, atau merge di sini.

Di menu samping, **Patients** punya dua sub-halaman: **CKG Umum** (pasien CKG biasa,
gabungan ePuskesmas + ASIK) dan **CKG Sekolah** (halaman ini).

## Sumber data — beda dengan CKG Umum

Data CKG Sekolah diambil dari modul **anak sekolah di ASIK** (Sehat IndonesiaKu),
yaitu hasil **Pelayanan oleh Nakes** (mis. Gizi, Tekanan Darah, Gula Darah, Gigi,
Mata & Telinga, Kebugaran, dll.) beserta **tatalaksana** (tindak lanjut).

Berbeda dengan CKG Umum, data sekolah **tidak digabung (merge) dengan
ePuskesmas** dan **tidak memakai filter tanggal** — pemeriksaan sekolah ditata
per **sekolah × kelas**, bukan per tanggal kunjungan. Karena itu di sini tidak
ada status "Hanya ASIK / Hanya EPUS / Cocok".

## Pencarian & filter

- **Cari** — cari berdasarkan **nama** atau **NIK**.
- **Sekolah** — pilih satu sekolah dari daftar sekolah yang ada datanya.
- **Kelas** — pilih kelas; pilihan kelas **mengikuti sekolah yang dipilih**
  (kalau belum memilih sekolah, daftar kelas berisi gabungan semua sekolah).
- **Status** — status pemeriksaan siswa:
  - **Belum Pemeriksaan** — siswa terdaftar tetapi pemeriksaan belum dilakukan.
  - **Sedang Pemeriksaan** — pemeriksaan sedang berjalan (sebagian hasil sudah
    terisi, belum lengkap).
  - **Selesai Pemeriksaan** — seluruh rangkaian pemeriksaan sudah selesai.
- **Umur** — saring berdasarkan **umur sekarang** (umur per hari ini); isi batas
  **minimum** dan/atau **maksimum**. Umur dihitung dari tanggal lahir siswa.
  Siswa yang tanggal lahirnya tidak terbaca **tidak muncul** selama filter umur
  aktif.
- **Tahun Ajaran** — saring berdasarkan tahun CKG sekolah.
- **Puskesmas** — pilih puskesmas tertentu.

## Detail siswa

Membuka satu siswa menampilkan **identitas** (termasuk data sekolah dan alamat),
lalu **tatalaksana** (tindak lanjut) bila ada, dan hasil tiap **Pelayanan oleh
Nakes** per jenis pemeriksaan. Tiap kartu menunjukkan berapa **field terisi** dari
total pertanyaan, sehingga terlihat pemeriksaan mana yang sudah/belum lengkap —
selaras dengan status Belum/Sedang/Selesai.

## Yang TIDAK bisa dijawab asisten ini di halaman ini

Asisten **tidak** punya akses ke data siswa — jadi tidak bisa menyebutkan nama,
NIK, umur, sekolah, atau hasil ukur siswa tertentu, maupun menghitung jumlah
siswa. Yang bisa dijelaskan hanya **cara membaca halaman, arti status, dan cara
kerja filter**. Data konkret ada di layar.
