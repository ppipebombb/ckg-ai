# Dashboard Diabetes Melitus

Halaman **Dashboard › Diabetes Melitus** menampilkan **2 grafik kohort** untuk
satu puskesmas yang dipilih (pilih puskesmas dulu di atas). Angkanya dihitung
dari Registri Diabetes Melitus CKG (pasien terpadan ASIK + ePuskesmas), lintas
tahun 2025 → bulan berjalan. Sama seperti dashboard lain: hasil di-cache ~30 jam
dan dihitung ulang otomatis tiap pagi ~05.00 WIB.

## Populasi "DM murni" (dipakai Batang 1 kedua grafik)

**Batang 1 di kedua grafik BUKAN "anggota Registri Diabetes Melitus"** — lebih
sempit: **DM murni oleh hasil ukur**, yaitu glukosa saat skrining CKG mencapai
**ambang diagnosis DM**:

- **GDP ≥126** mg/dL, **atau**
- **GD2PP ≥200** mg/dL, **atau**
- **GDS-2 ≥200** mg/dL.

Jadi pasien yang di registri berlabel "Diabetes Melitus" **hanya karena riwayat**
(sudah pernah didiagnosis) tapi gula darahnya saat itu sebenarnya normal, **tidak
dihitung** di grafik ini. Pasien **Prediabetes** (GDP 100–125 dsb.) juga tidak
termasuk. Ini analog persis dengan grafik Hipertensi yang memakai "HT murni"
(TD ≥140/90).

Ambang **Ya/Tidak di CKG 2026** memakai **ambang diagnosis yang sama** (bukan
target "terkendali" follow-up) — supaya simetris dengan grafik Hipertensi.

## Grafik 1 — Diabetes Melitus 2 Tahun Berturut-turut (batang bertumpuk)

Empat batang:
1. **DM CKG 2025** — pasien dengan glukosa mencapai ambang diagnosis DM saat
   skrining CKG 2025 (acuan 100%).
2. **Diperiksa CKG 2026** — dari nomor 1, yang juga punya kunjungan skrining CKG
   di 2026 (dipadankan per NIK), berapa pun hasil gula darahnya di 2026.
3. **DM 2026 — Ya/Tidak** — dari nomor 2, dipecah dua warna dalam satu batang:
   **Ya** (merah) = glukosa CKG 2026 masih ≥ ambang diagnosis DM; **Tidak**
   (hijau) = sudah di bawah ambang.
4. **Diobati** — dipecah **empat** warna, masing-masing dari salah satu warna
   nomor 3 (bukan dari total nomor 2): **Ya-Diobati** (merah tua) dan
   **Ya-Tidak Diobati** (merah muda) dari pasien yang glukosa 2026-nya masih
   tinggi; **Tidak-Diobati** (hijau tua) dan **Tidak-Tidak Diobati** (hijau
   muda) dari pasien yang sudah di bawah ambang. "Diobati" = pernah diberi obat
   antidiabetik (mis. Metformin, insulin) kapan saja sejak 2025.

Angka di atas batang hanya muncul di batang hitungan populasi — DM CKG 2025,
Diperiksa CKG 2026, dan DM CKG 2026 — = jumlah pasien batang itu. Batang yang
dipecah dua/empat warna (Ya/Tidak, Kategori Pasien, Diobati) TIDAK diberi angka
di atasnya, karena totalnya cuma mengulang batang sebelumnya; rincian jumlah per
warnanya muncul di kotak info melayang saat batang diarahkan kursor/disentuh,
dengan teks berwarna sesuai warna segmennya.

## Grafik 2 — Diabetes Melitus CKG 2026 (batang bertumpuk)

Batang 1 memakai populasi "DM murni oleh hasil ukur" (glukosa mencapai ambang
diagnosis saat skrining CKG 2026), bukan registri DM penuh.

Tiga batang:
1. **DM CKG 2026** — pasien dengan glukosa mencapai ambang diagnosis DM saat
   skrining CKG 2026 (acuan 100%).
2. **Kategori Pasien — Pasien Baru/Sudah DM** — dari nomor 1, dipecah dua warna:
   **Pasien Baru** (ungu) = tidak punya riwayat diagnosis DM sebelumnya (baru
   ketahuan lewat gula darah tinggi di skrining ini); **Sudah DM** (biru muda) =
   punya riwayat diagnosis DM (termasuk pasien yang riwayatnya baru dilaporkan
   sendiri di skrining 2026 ini — tetap dihitung "Sudah DM", bukan "Pasien
   Baru", karena secara medis bukan kasus baru).
3. **Diobati** — dipecah **empat** warna, masing-masing dari salah satu warna
   nomor 2 (bukan dari total nomor 1): **Pasien Baru-Diobati** (ungu tua) dan
   **Pasien Baru-Tidak Diobati** (ungu muda); **Sudah DM-Diobati** (biru tua)
   dan **Sudah DM-Tidak Diobati** (biru muda). "Diobati" = obat antidiabetik
   kapan saja sejak 2025, sama seperti Grafik 1 batang 4.

## Arti tulisan status di layar

- **"Computed <tanggal jam> · cached/fresh"** = kapan angka grafik terakhir
  dihitung. Hasil disimpan sementara (**cache ~30 jam**) dan dihitung ulang
  otomatis tiap pagi ~05.00 WIB, jadi perubahan data ePuskesmas/ASIK baru
  terlihat paling lambat besok pagi.
