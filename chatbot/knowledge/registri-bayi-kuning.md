# Registri Bayi Kuning (Ikterus & Ikterus Berat)

Dua halaman di bawah menu **Registri PJB-K**: **Bayi Kuning - Ikterus** dan
**Bayi Kuning - Ikterus Berat**. Keduanya mendaftar bayi baru lahir (umur 0)
yang dinilai kuning (ikterus) pada pemeriksaan MTBM (Manajemen Terpadu Bayi
Muda), mengikuti format dirjen "Register Sheet Pasien PJB, Ikterus" (sheet
"Bayi Kuning_Ikterus" dan "Bayi Kuning_Ikterus Berat"). Bisa disaring per
puskesmas + tahun + pencarian nama/NIK, dan diexport ke Excel.

## Beda dua sheet

- **Bayi Kuning - Ikterus** memuat bayi dengan klasifikasi **Ikterus** ATAU
  **Ikterus berat**. Punya kolom **Pemantauan** (kunjungan ikterus berikutnya).
- **Bayi Kuning - Ikterus Berat** hanya memuat bayi dengan klasifikasi
  **Ikterus berat**. Tanpa kolom pemantauan (baseline saja).

## Siapa yang masuk daftar

Bayi baru lahir (umur 0) yang klasifikasi ikterus-nya positif. Bayi yang tidak
kuning ("Tidak ada ikterus") tidak ditampilkan.

## Aturan klasifikasi (MTBM)

Diambil dari kuesioner "Memeriksa Ikterus" pada pemeriksaan MTBM:

- **Tidak ada ikterus** — "Apakah bayi kuning" = Tidak.
- **Ikterus** — kuning, tanpa kriteria berat.
- **Ikterus berat** — kuning DAN salah satu: kuning timbul **< 24 jam**, ATAU
  **> 14 hari**, ATAU kuning sampai **telapak tangan/kaki**.

## Tanda sumber: EPUS vs Hitung

Setiap nilai klasifikasi diberi tanda kecil, mirip tanda (ePus)/(ASIK) di
registri lain — tapi di sini artinya berbeda:

- **EPUS** — klasifikasi diambil langsung dari isian field klasifikasi di EPUS.
- **Hitung** — klasifikasi **dihitung sistem** dari kuesioner "Memeriksa
  Ikterus" (aturan di atas), karena field klasifikasi EPUS-nya kosong.

Saat ini hampir semua bertanda **Hitung**, karena field klasifikasi EPUS
umumnya belum terisi. Diagnosis dan Rujuk Eksternal selalu dari EPUS.

## Kolom

- **Tanggal Berkunjung** — kunjungan pertama (skrining) tempat ikterus dinilai.
- **Ikterus** — klasifikasi pada kunjungan itu (dengan tanda EPUS/Hitung).
- **Diagnosis** — diagnosis yang tercatat di EPUS pada kunjungan itu.
- **Rujuk Eksternal** — faskes tujuan rujukan pada kunjungan itu (dari tabel
  "Data Rujukan External" EPUS); kosong bila tidak dirujuk.
- **Pemantauan** (hanya sheet Ikterus) — kunjungan ikterus berikutnya, masing-
  masing dengan tanggal, klasifikasi, diagnosis, dan rujukannya sendiri.

## Beda dengan registri lain (penting)

- Registri ini **hanya dari ePuskesmas (EPUS)**, tidak digabung dengan ASIK, dan
  **tidak** disyaratkan "pasien CKG" (kunjungan cocok di kedua sumber). Sebabnya:
  di lapangan, penilaian ikterus MTBM dicatat pada kunjungan yang tidak ditandai
  CKG, sehingga syarat CKG akan mengosongkan daftar. Jadi bayi masuk daftar
  berdasarkan adanya penilaian ikterus, bukan keanggotaan program CKG.
- Bayi membawa **NIK orang tua** (belum punya KTP), jadi bayi dibedakan dari
  orang tua lewat umur 0 / nama berawalan "BAYI", bukan lewat NIK.

## Yang belum tersedia

- Sheet **PJBK** (skrining jantung bawaan / pulse-oksimetri) belum tersedia di
  aplikasi — datanya belum terekam di EPUS.
- Kolom "Rujuk Eksternal" hanya berisi bila rujukan tercatat di EPUS pada
  kunjungan itu; sering kosong.
