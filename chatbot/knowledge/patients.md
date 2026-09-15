# Halaman Pasien (Patients)

Halaman **Pasien** menampilkan daftar dan detail **data pasien per orang** —
gabungan data ePuskesmas dan ASIK untuk tiap kunjungan. Halaman ini **hanya
untuk dilihat** (read-only): tidak ada tombol ubah data, scrape ulang, atau
merge di sini.

## Sumber & gabungan data

Sama seperti laporan lain: tiap baris berasal dari **ePuskesmas** dan/atau
**ASIK**, lalu **digabung (merge)** dengan aturan tetap — untuk nilai
pemeriksaan/kuesioner, bila berbeda **nilai ePuskesmas yang dipakai** dan ASIK
mengisi bagian yang kosong. **Khusus identitas pasien** (NIK, nama, tanggal
lahir, tempat lahir, jenis kelamin, alamat) justru sebaliknya: **nilai ASIK yang
dipakai**, ePuskesmas hanya mengisi bila ASIK kosong. (Lihat penjelasan dua
sumber di bagian "Tentang Aplikasi Ini & Asal Data".)

## Pencarian & filter

- **Cari** — cari berdasarkan **nama** atau **NIK**.
- **Tanggal** — tanggal kunjungan.
- **Status** — status pencocokan antar sumber:
  - **Hanya EPUS** — datanya baru ada di ePuskesmas, belum cocok dengan ASIK.
  - **Hanya ASIK** — datanya baru ada di ASIK, belum cocok dengan ePuskesmas.
  - **Cocok** — kunjungan yang sama ditemukan di **kedua** sumber (inilah
    calon **pasien CKG** yang masuk ke registri).
- **Penggabungan** — apakah hasil gabungan (merge) sudah dibuat untuk pasien itu.
- **Umur** — saring berdasarkan **umur sekarang** (umur per hari ini); isi batas
  **minimum** dan/atau **maksimum**. Umur dihitung dari tanggal lahir pasien.
  Pasien yang tanggal lahirnya tidak terbaca dari sumber **tidak muncul** selama
  filter umur aktif.
- **Puskesmas** — pilih puskesmas tertentu.

## Detail pasien

Membuka satu pasien menampilkan hasil gabungan; lewat tombol pengalih (toggle)
di kanan atas bisa berganti ke tampilan sumber **ePus**, **ASIK**, atau konversi
**ePus→ASIK** — satu tampilan setiap kali, bukan berdampingan. Pada tampilan
gabungan, tiap nilai menandai asal sumbernya sehingga bisa ditelusuri. Label di
kanan atas menunjukkan **puskesmas • tanggal kunjungan**.

Hasil dari ASIK mencakup dua bagian pemeriksaan: **Pelayanan oleh Nakes**
(diisi tenaga kesehatan) dan **Pemeriksaan Mandiri** (kuesioner skrining yang
diisi sendiri oleh pasien — misalnya Kesehatan Jiwa, Perilaku Merokok, Tingkat
Aktivitas Fisik). Kedua bagian ini tampil di bawah judulnya masing-masing pada
**tampilan sumber ASIK** (bukan pada hasil gabungan). Sebagian pasien mungkin
belum melengkapi Pemeriksaan Mandiri, jadi bagiannya bisa kosong.

## Yang TIDAK bisa dijawab asisten ini di halaman ini

Asisten **tidak** punya akses ke data pasien — jadi tidak bisa menyebutkan nama,
NIK, umur, atau hasil ukur pasien tertentu, maupun menghitung jumlah pasien.
Yang bisa dijelaskan hanya **cara membaca halaman, arti status, dan cara kerja
filter**. Data konkret ada di layar.
