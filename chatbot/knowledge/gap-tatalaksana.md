# Halaman Gap Tatalaksana

Daftar **pasien hipertensi CKG yang belum pernah tercatat mendapat obat
antihipertensi**, lengkap dengan no telp dan alamat, supaya puskesmas bisa
menghubungi dan menindaklanjuti mereka satu per satu.

Halaman ini adalah sub-halaman dari menu **Registri Hipertensi CKG**. Bisa juga
dibuka lewat tombol **"Lihat Detail"** di pojok kanan atas kartu grafik **Pasien
Hipertensi Tertatalaksana** pada halaman Dashboard.

## 1 · Dari mana angkanya

Daftar ini persis **jarak antara kedua garis** pada grafik Pasien Hipertensi
Tertatalaksana di bulan terakhir:

> Pasien Hipertensi Kumulatif − Pasien Tertatalaksana = jumlah baris di halaman ini

Contoh: kalau di bulan terakhir grafik menunjukkan 2.427 pasien hipertensi
kumulatif dan 462 pasien tertatalaksana, halaman ini berisi 1.965 pasien.

Jadi kalau angka di halaman ini terasa besar, itu bukan halaman yang salah —
itu isi dari jarak yang memang terlihat di grafik.

## 2 · Siapa yang masuk daftar

Seorang pasien muncul di sini kalau **dua-duanya** benar:

1. **Dia ada di Registri Hipertensi CKG.** Artinya punya kunjungan CKG yang
   terpadan (data ePuskesmas + ASIK cocok) dan memenuhi syarat hipertensi —
   punya riwayat hipertensi, atau rerata tensinya masuk band **Hipertensi**
   (≥ 140 atau ≥ 90) atau **Pre-Hipertensi** (≥ 130 atau ≥ 85). Pasien dengan
   tensi Normal tanpa riwayat tidak masuk registri, jadi juga tidak masuk sini.
2. **Belum pernah tercatat diberi obat antihipertensi**, sejak Februari 2025
   sampai bulan berjalan.

## 3 · Arti "belum tertatalaksana"

Sistem menganggap pasien **sudah** tertatalaksana kalau obat antihipertensi
tercatat di salah satu dari dua tempat ini:

- **Resep ePuskesmas** pada kunjungan mana pun (bukan hanya kunjungan CKG), atau
- **Peresepan pada tatalaksana Tekanan Darah di ASIK** pada kunjungan CKG-nya.

Yang dihitung adalah nama obat golongan antihipertensi (amlodipin, kaptopril,
kandesartan, bisoprolol, furosemid, dan sejenisnya).

Sifatnya **sekali seumur periode**: begitu seorang pasien pernah tercatat diberi
obat — kapan pun, di bulan mana pun — dia keluar dari daftar ini dan tidak
kembali lagi, walaupun bulan-bulan berikutnya tidak ada resep baru.

**Penting:** "belum tertatalaksana" berarti **belum tercatat**, bukan pasti
belum diobati. Kalau obat diberikan tetapi tidak dicatat di resep ePuskesmas
atau di tatalaksana ASIK, pasiennya tetap muncul di sini. Perbaikannya ada di
pencatatan.

## 4 · Cara pakai halaman

Tiga penyaring di atas tabel:

- **Puskesmas** — wajib dipilih dulu; daftar dihitung per puskesmas.
- **Tahun Masuk Registri** — tahun saat pasien **pertama kali** memenuhi syarat
  hipertensi lewat kunjungan CKG. Default **"Semua tahun"**. Ini **bukan** tahun
  pelaporan: pasien yang masuk registri 2025 dan sampai sekarang belum diobati
  tetap berada di bawah 2025, bukan pindah ke tahun berjalan. Gunanya untuk
  memprioritaskan yang paling lama menunggu.
- **Search Nama / NIK** — pencarian bebas, cocok sebagian nama atau sebagian NIK.

Daftarnya dibagi **20 pasien per halaman**, diurutkan dari **bulan masuk
registri paling lama** lebih dulu.

## 5 · Kolom tabel

| Kolom | Isi |
|---|---|
| NIK | Nomor induk kependudukan pasien |
| Nama | Nama pasien |
| Jenis Kelamin | Laki-Laki / Perempuan |
| Tanggal Lahir | Tanggal lahir |
| No Telp / HP | Nomor telepon untuk dihubungi |
| Alamat | Alamat pasien |
| Tanggal Berkunjung | Tanggal kunjungan CKG saat pasien masuk registri |
| Rerata (S/D) | Rerata tensi sistol/diastol pada kunjungan CKG itu |
| Interpretasi | Hipertensi atau Pre-Hipertensi |
| Masuk Registri | Bulan dan tahun pasien masuk registri |

Identitas diambil dari sumber yang sama dengan Registri Hipertensi CKG: data
ASIK dipakai lebih dulu per kolom, data ePuskesmas mengisi yang kosong. Karena
itu nama, no telp, dan alamat di dua halaman ini tidak akan berbeda.

## 6 · Kalau no telp atau alamat kosong

Kolom yang kosong ditandai tanda strip (**—**). Itu berarti datanya memang tidak
ada di ePuskesmas maupun di ASIK, bukan gagal dimuat.

Pasien tanpa no telp **tetap ditampilkan** dan tetap dihitung dalam total —
justru pasien itulah yang paling sulit ditindaklanjuti, jadi sengaja tidak
disembunyikan. Untuk melengkapinya, perbaiki identitas pasien di ePuskesmas;
laporan ikut benar setelah data diperbarui (paling lambat besok pagi).

## 7 · Export Excel

Tombol **Export Gap Tatalaksana** mengunduh daftar ini sebagai file Excel.
Isinya **mengikuti penyaring yang sedang aktif** (puskesmas, tahun, pencarian),
tetapi memuat **semua baris** yang cocok, bukan hanya halaman yang sedang
tampil. Kolomnya sama dengan tabel, ditambah nomor urut.

## 8 · Kapan angkanya diperbarui

Hasil perhitungan disimpan sementara (**cache ~30 jam**) dan dihitung ulang
otomatis tiap pagi sekitar **05.00 WIB**, sama seperti grafik Dashboard —
keduanya berasal dari satu perhitungan yang sama. Saat perhitungan pertama
berjalan, halaman menampilkan bilah kemajuan dan hasilnya muncul sendiri setelah
selesai. Jadi tindak lanjut yang dicatat hari ini baru terlihat besok.
