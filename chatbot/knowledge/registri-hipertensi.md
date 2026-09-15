# Halaman Registri Hipertensi CKG (Kertas Kerja Hipertensi)

Kertas kerja hipertensi per **satu puskesmas + satu tahun pelaporan**,
mengikuti format registri dirjen **V8juni2026**. Isinya: identitas pasien,
hasil pemeriksaan tekanan darah pada tanggal berkunjung CKG, dan follow-up
tekanan darah per bulan. Bisa diexport ke **Excel** — di file export, rumus
tertanam langsung di sel (klik sel Rerata/Interpretasi untuk melihatnya), dan
ada sheet **"Formula & Logika"** berisi penjelasan yang sama dengan kartu
**"Cara Membaca Kertas Kerja Ini"** di halaman.

**Cara pakai halaman:** pilih Puskesmas + Tahun Pelaporan (pilihan tahun =
tahun ini sampai 5 tahun ke belakang), lalu cari nama/NIK bila perlu. Klik
baris pasien untuk membuka detail (no. telepon, alamat, obat, dan tabel
Follow Up per bulan). Keterangan "N pasien (CKG) · X hipertensi · Y
pre-hipertensi" = total pasien dalam registri itu beserta rinciannya per
interpretasi (Hipertensi + Pre-Hipertensi = total); daftarnya dibagi **20
pasien per halaman**.

Kolom **"Follow-up"** di tabel utama berisi **angka** = jumlah baris Follow Up
pasien itu — gabungan kunjungan yang ada hasil tensinya **dan** bulan
**Missed Visit**. Jadi angka besar belum tentu sering kontrol; bisa jadi
banyak bulan Missed Visit. Rinciannya muncul saat baris pasien diklik.

## Inti — satu daftar, dua pertanyaan

Kolom hasil pemeriksaan menjawab: **berapa tensi pasien SAAT skrining CKG?**
Kolom Follow Up menjawab: **pada bulan-bulan setelahnya, apakah tensinya sudah
di bawah 140/90?** Karena pertanyaannya berbeda, labelnya bisa berbeda — dan
itu memang benar, bukan error.

Tiga angka yang perlu diingat: **140/90** (batas hipertensi DAN target
terkendali), **130/85** (mulai Pre-Hipertensi), dan **rata-rata 2x ukur**.

## 1 · Siapa yang masuk daftar ini (Syarat)

Pasien (per NIK) masuk daftar jika punya **minimal satu kunjungan CKG**
(kunjungan yang tercatat di ePus DAN ASIK) pada tahun itu, **DAN** memenuhi
salah satu:

1. **Sudah tercatat sebagai pasien hipertensi** — punya catatan **diagnosis**
   (kolom Riwayat HT = Ya), ATAU
2. **Tensinya di atas normal saat skrining CKG** — **rerata** pengukuran
   **130/85 ke atas**: kolom Interpretasi = **Hipertensi** (140/90 ke atas)
   atau **Pre-Hipertensi** (130–139/85–89). Pasien Pre-Hipertensi ikut dipantau
   lebih awal walau belum didiagnosis.
   Sesuai Juknis CKG KMK 84/2026: pengukuran pertama yang tinggi diulang, dan
   **rata-rata keduanya** yang menentukan — itulah fungsi kolom TD 1, TD 2, dan
   Rerata.

Pasien yang tensinya **Normal** (di bawah 130/85) **dan** tidak pernah
didiagnosis **tidak ditampilkan** — belum perlu dipantau di sini. Pasien yang
tensi tingginya hanya terjadi di kunjungan biasa (bukan CKG) dan tidak punya
diagnosis juga tidak masuk kertas kerja ini.

## 2 · Sumber setiap kolom

Sumber utama untuk kolom-kolom atas adalah **data skrining CKG di ASIK**;
**ePuskesmas** pada kunjungan yang sama dipakai sebagai **cadangan** bila ASIK
kosong. Pengecualian: kolom **Follow Up** memakai data **ePuskesmas** (kunjungan
bulan-bulan berikutnya).

Di dashboard, buka (klik) baris pasien untuk melihat **tag sumber** pada tiap
nilai: **ASIK** (biru) bila nilai itu berasal dari skrining CKG, **ePus** (hijau)
bila dari ePuskesmas. Tag menunjukkan sumber asli untuk pasien tersebut — mis.
TD biasanya ASIK, obat bisa dari ePuskesmas. Follow Up selalu ePuskesmas.

- **Identitas** (NIK, Nama, Jenis Kelamin, Tanggal Lahir, No. Telepon,
  Alamat): sumber utama **skrining ASIK**; bila sebuah kolom kosong di ASIK,
  dipakai **pendaftaran ePuskesmas** pada kunjungan yang sama. Kalau salah,
  perbaiki di sumbernya (ASIK / ePuskesmas).
- **Tanggal Berkunjung**: kunjungan CKG (ePus+ASIK) **paling awal** tahun itu.
  Kalau pasien ikut CKG dua kali setahun, yang dipakai yang **pertama**;
  kunjungan berikutnya tampil di Follow Up **bulan setelah** bulan skrining
  (kunjungan lain di bulan skrining yang sama tidak ditampilkan terpisah —
  sudah terwakili kolom hasil pemeriksaan).
- **Riwayat HT (Ya/Tidak)**: "Ya" HANYA dari **catatan diagnosis** — bukan
  dari angka tensi. Sumber utama **ASIK**, ePuskesmas sebagai cadangan; satu
  saja kena → Ya:
  1. Jawaban skrining CKG (ASIK): *"Apakah Anda pernah dinyatakan tekanan darah
     tinggi?"* = **Ya**;
  2. Diagnosis pada **tatalaksana ASIK** (tindak lanjut yang dicatat nakes)
     berkode ICD hipertensi **I10–I15** atau bernama "hipertensi/hypertension";
  3. (cadangan ePuskesmas) Diagnosis ePus penyakit khusus / PTM Diagnosa berkode
     ICD **I10–I13, I15** atau bernama hipertensi; ePus PTM → Riwayat PTM pada
     Diri Sendiri → Penyakit Hipertensi = Ya; atau ePus Diagnosa → Tandai
     Penyakit Kronis → Hipertensi.

  Jawaban "Ya" **melekat** (sticky): sekali tercatat Ya di salah satu sumber,
  tetap Ya — kolom kosong atau "Tidak" di sumber lain tidak menghapusnya.
- **TD Sistolik/Diastolik 1**: pengukuran **pertama** dari **skrining CKG
  (ASIK)**. Bila ASIK tidak punya angka pengukuran pertama, dipakai pengukuran
  **ePuskesmas** pada hari kunjungan CKG (pemeriksaan fisik; cadangan: form PTM
  Tekanan Darah & IMT).
- **TD Sistolik/Diastolik 2**: pengukuran **ke-2**, hanya ada di **skrining
  CKG (ASIK)** — ePuskesmas tidak punya kolom ini. **Sering kosong** (terisi
  hanya ±3% pasien) karena petugas biasanya mengukur sekali saja. Kosong itu
  normal, bukan data hilang.
- **Rerata**: rata-rata angka yang ada = (TD1 + TD2) ÷ 2; kalau TD2 kosong,
  rerata = TD1 saja. Dibulatkan 1 desimal.
- **Interpretasi (pada tanggal berkunjung)** — pasien yang **sudah punya
  diagnosis hipertensi** (kolom Riwayat HT = Ya) selalu berlabel **"Hipertensi"**,
  berapa pun tensinya. Bila **Riwayat HT = Tidak**, label dihitung dari **Rerata**
  dengan batas resmi Kemenkes (Juknis CKG KMK 84/2026, PNPK 4634/2021):

  | Rerata (saat Riwayat HT = Tidak) | Label |
  |---|---|
  | Sistolik ≥ 140 **dan/atau** Diastolik ≥ 90 | **Hipertensi** |
  | Sistolik 130–139 **dan/atau** Diastolik 85–89 | **Pre-Hipertensi** |
  | Sistolik ≤ 129 **dan** Diastolik ≤ 84 | **Normal** |

  Cukup **satu angka** yang lewat batas: contoh **137/100** = Hipertensi,
  karena angka bawahnya (100) sudah ≥ 90 walau angka atasnya belum 140.
  Semua aturan Kemenkes memakai "dan/atau".

  Yang dinilai adalah **rerata** (kolom Rerata). Kalau pasien hanya diukur satu
  kali (TD 2 kosong), rerata = TD 1 — jadi **satu kali ukur** yang 140/90 ke atas
  sudah cukup untuk label **"Hipertensi"** walau pasien belum pernah didiagnosis.
  Pasien ini masuk daftar lewat Syarat nomor 2.
- **Jenis Obat** (baseline): sumber utama **peresepan pada tatalaksana ASIK**
  (obat yang diresepkan nakes saat tindak lanjut hipertensi); bila tidak ada,
  dipakai **resep ePuskesmas** pada kunjungan CKG. Di tiap baris Follow Up, obat
  tetap dari **resep ePuskesmas** kunjungan itu. **Hanya obat darah tinggi**
  yang ditampilkan (sesuai kolom dirjen "List Obat Hipertensi"); vitamin,
  antibiotik, obat gula, dll. sengaja tidak ikut:
  - **Antagonis kalsium (CCB)**: Amlodipin, Nifedipin, Felodipin, Nikardipin,
    Lerkanidipin, Diltiazem, Verapamil
  - **ACE inhibitor**: Kaptopril (Captopril), Lisinopril, Ramipril, Enalapril,
    Perindopril, Imidapril
  - **ARB (sartan)**: Kandesartan, Losartan, Valsartan, Irbesartan,
    Telmisartan, Olmesartan
  - **Diuretik**: Hidroklorotiazid (HCT) & tiazid lain, Furosemid,
    Spironolakton, Indapamid, Klortalidon
  - **Beta-blocker**: Bisoprolol, Atenolol, Propranolol, Metoprolol,
    Carvedilol, Nebivolol
  - **Lainnya**: Metildopa, Klonidin, Doksazosin, Terazosin, Prazosin,
    Hidralazin, Minoxidil

## 3 · Follow Up (per bulan)

- **Mulai bulan SETELAH bulan skrining CKG** (bulan skrining tidak diulang —
  sudah terwakili kolom hasil pemeriksaan), sampai Desember; untuk tahun
  berjalan, sampai bulan ini. Bulan yang belum terjadi dibiarkan **kosong**.
- **Semua kunjungan ditampilkan**: kalau pasien datang beberapa kali dalam
  sebulan, semua kunjungan yang ada hasil tensinya ditampilkan berurutan —
  masing-masing dengan tanggal, hasil, dan statusnya sendiri (header bulan
  menunjukkan "N kunjungan").
- **Label status tiap kunjungan** (teks persis seperti di legend dirjen):
  - TD di bawah 140/90 →
    **"Pasien hipertensi terkendali (target tercapai)"**
  - Sistolik ≥ 140 dan/atau Diastolik ≥ 90 →
    **"Pasien hipertensi tidak terkendali (target tidak tercapai)"**
  - Bulan lewat tanpa pemeriksaan tensi → **"Pasien Missed Visit"**
- Kunjungan yang **tensinya tidak dicatat** tidak bisa dinilai dan tidak
  menyelamatkan bulan itu dari Missed Visit — pastikan tiap kontrol hipertensi
  tensinya dicatat di ePuskesmas.
- Duplikat hasil pengambilan data (kunjungan yang sama terekam dua kali)
  otomatis digabung menjadi satu kunjungan — tidak ada kunjungan dobel.

## 4 · Warna di tabel

Pada sel **Interpretasi** dan **Follow Up**: Merah = Hipertensi / tidak
terkendali · Kuning = Pre-Hipertensi ·
Hijau = Normal / terkendali · Abu-abu = Missed Visit.

Khusus kolom **Riwayat HT**, badge **"Ya"** juga berwarna **merah** — tapi di
sini artinya **"sudah punya diagnosis hipertensi"**, BUKAN "tidak terkendali".
Jangan menafsirkan merah pada Riwayat HT sebagai tensi tinggi/bahaya.

## 5 · Kombinasi label yang terlihat "bertentangan" (padahal benar)

- **Interpretasi "Hipertensi" lalu follow-up "terkendali"**: saat skrining
  tensinya tinggi (itulah alasan dia masuk daftar), lalu bulan-bulan
  berikutnya sudah di bawah 140/90. Justru kabar baik — skrining berhasil
  menemukan, kontrolnya berhasil. Label awal tidak berubah karena ia mencatat
  kondisi saat skrining.
- **Interpretasi "Hipertensi" padahal tensinya hari itu bagus**: pasien ini
  sudah punya diagnosis hipertensi (Riwayat = Ya), jadi tetap berlabel
  "Hipertensi" walau tensinya hari itu di bawah 140/90 — diagnosis tidak hilang
  karena satu hasil ukur yang bagus (pengobatan hipertensi pada dasarnya seumur
  hidup; tidak ada kriteria "sembuh dari hipertensi" di dokumen Kemenkes). Kalau
  tensinya sudah terkontrol, Follow Up bulan berikutnya menyebutnya "terkendali".
- **Riwayat "Tidak" tapi Interpretasi "Hipertensi"**: Riwayat = pernah
  didiagnosis **sebelumnya**. Pasien yang baru ketahuan saat skrining memang
  riwayatnya "Tidak" — dia pasien hipertensi yang **baru ditemukan**. Masuk
  daftar lewat Syarat nomor 2.
- **Interpretasi "Pre-Hipertensi" tapi di Follow Up disebut "pasien
  hipertensi"**: pasien Pre-Hipertensi (tensinya 130–139/85–89, belum
  didiagnosis) ikut dipantau lebih awal. Tulisan **"Pasien hipertensi
  terkendali/tidak terkendali"** di Follow Up adalah **istilah baku format
  dirjen**, bukan berarti dia sudah pasti didiagnosis — bacalah sebagai:
  target di bawah 140/90 tercapai atau tidak. Jadi tidak semua baris di sini
  pasien hipertensi; ada juga Pre-Hipertensi yang dipantau lebih awal.

## 6 · Tanya-jawab yang sering muncul

**"Kenapa pasien ini ada di daftar padahal tensinya normal?"**
Karena dia sudah tercatat sebagai pasien hipertensi (Riwayat = Ya). Daftar ini
memantau semua pasien hipertensi — termasuk yang tensinya sedang bagus. Tensi
bagus artinya terkendali, bukan berarti dia keluar dari daftar.

**"Kenapa pasien itu TIDAK ada di daftar? Kemarin tensinya 150."**
Daftar ini berpatokan pada kunjungan skrining CKG. Kalau tensi tingginya
terjadi di kunjungan biasa (bukan CKG) dan dia tidak punya diagnosis
hipertensi, dia tidak masuk kertas kerja ini. Bisa juga karena data CKG-nya
(ePus+ASIK) untuk tahun itu belum cocok/lengkap di sistem.

**"Interpretasi-nya Hipertensi, tapi follow-up-nya 'terkendali'. Mana yang benar?"**
Dua-duanya benar. Saat skrining tensinya tinggi — itu alasan dia masuk daftar.
Bulan-bulan setelahnya tensinya sudah di bawah 140/90 — itu artinya
terkendali. Justru ini cerita sukses: ketahuan saat skrining, sekarang
terkontrol.

**"137/100 kok Hipertensi? Kan belum 140?"**
Cukup satu angka yang lewat batas. Angka atas batasnya 140, angka bawah
batasnya 90. Di sini angka bawahnya 100 — sudah lewat 90, jadi Hipertensi.

**"Kenapa TD 2 kosong hampir di semua pasien? Datanya hilang?"**
Tidak hilang. TD 2 hanya terisi kalau petugas skrining mengukur dua kali.
Kebanyakan hanya diukur sekali, jadi kosong itu normal.

**"Kenapa bulan skrining tidak ada di Follow Up?"**
Bulan skrining sudah terwakili kolom hasil pemeriksaan. Follow Up menilai
bulan-bulan SETELAHNYA — sesuai aturan dirjen: dinilai "pada kunjungan bulan
berikutnya".

**"Pasien ini datang 3 kali sebulan, statusnya kok beda-beda?"**
Semua kunjungan memang ditampilkan dan dinilai sendiri-sendiri: di bawah
140/90 → terkendali; 140/90 ke atas → tidak terkendali. Tensi memang
naik-turun, jadi wajar sebulan ada hijau dan merah. Kalau butuh satu
kesimpulan untuk bulan itu, pakai kunjungan paling bawah (kunjungan terakhir
bulan itu).

**"Dia bulan itu DATANG ke puskesmas, kok ditulis Missed Visit?"**
Datang, tapi tensinya tidak diukur atau tidak tercatat. Tanpa angka tensi
sistem tidak bisa menilai terkendali atau tidak, jadi bulan itu terhitung
belum kontrol. Pastikan tiap kontrol hipertensi tensinya dicatat di
ePuskesmas.

**"Kenapa bulan depan kosong, bukan Missed Visit?"**
Bulan yang belum terjadi dibiarkan kosong. Missed Visit hanya untuk bulan yang
sudah lewat tanpa pemeriksaan.

**"Obat yang saya resepkan kok tidak muncul di Jenis Obat?"**
Kolom itu khusus obat darah tinggi (sesuai kolom dirjen "List Obat
Hipertensi"). Paracetamol, vitamin, antibiotik, obat gula — sengaja tidak
ditampilkan.

**"Pasien ini rutin minum amlodipine, kok kolom obatnya kosong?"**
Sistem hanya bisa menampilkan obat yang tercatat di Resep ePuskesmas pada
kunjungan itu. Kalau obatnya dibeli sendiri atau diresepkan di tempat lain,
tidak ada datanya di sistem.

**"Kok jumlah pasiennya berubah dari kemarin / beda dengan laporan lama?"**
Tampilan menyesuaikan syarat resmi format dirjen: yang ditampilkan adalah
pasien yang punya riwayat diagnosis hipertensi ATAU tensinya di atas normal
saat CKG — Hipertensi (140/90 ke atas) maupun Pre-Hipertensi (130–139/85–89).
Hanya pasien yang tensinya Normal (di bawah 130/85) dan tidak pernah
didiagnosis yang tidak ditampilkan.

**"Kenapa Pre-Hipertensi mulai 130? Setahu saya 120."**
120 itu aturan lama. Aturan resmi CKG sekarang (Juknis CKG KMK 84/2026):
Normal sampai 129/84, Pre-Hipertensi 130–139/85–89, Hipertensi mulai 140/90.
Sistem mengikuti yang terbaru — karena ini, sebagian pasien yang dulu
berlabel Pre-Hipertensi kini berlabel Normal.

**"Pasien ini sudah pindah/meninggal, kok masih Missed Visit?"**
Sistem hanya tahu dari catatan ePuskesmas. Kalau kepindahan atau kematian
belum dicatat, sistem menganggap dia masih pasien yang harus kontrol.
Dicatatkan dulu di ePuskesmas, nanti laporannya mengikuti.

**"Angka di sini beda dengan yang saya lihat di ePuskesmas/ASIK."**
Kolom Rerata adalah rata-rata dua pengukuran (umumnya keduanya dari skrining
ASIK; ePuskesmas dipakai bila ASIK kosong), jadi bisa beda dengan satu angka
yang Anda lihat di salah satu aplikasi. Di file Excel, klik selnya — rumusnya
kelihatan.

**"Kenapa tidak dibedakan hipertensi ringan/berat (derajat 1-2-3)?"**
Format dirjen untuk kertas kerja ini hanya meminta tiga kategori: Normal,
Pre-Hipertensi, Hipertensi. Pembagian derajat 1–3 ada di pedoman klinis, tapi
tidak diminta di format laporan ini.

## 7 · Dasar aturan (untuk yang ingin memeriksa)

- **Juknis CKG — KMK 84/2026**: batas Normal/Pre-Hipertensi/Hipertensi +
  aturan rata-rata 2x ukur.
- **PNPK Hipertensi Dewasa — KMK 4634/2021**: klasifikasi hipertensi
  (≥140/90).
- **Pedoman Pengendalian Hipertensi di FKTP 2024**: "terkendali" = di bawah
  140/90 pada kunjungan terakhir; obat hipertensi pada dasarnya seumur hidup.
- **Permenkes 4/2019 (SPM)**: pasien hipertensi dikontrol tensinya minimal
  1x/bulan — dasar penilaian per bulan & Missed Visit.
- **Formularium Nasional — KMK 1199/2025**: daftar obat darah tinggi di
  puskesmas (daftar obat di atas adalah perluasannya: obat antihipertensi yang
  benar-benar diresepkan tetap ditampilkan walau di luar Fornas FKTP).
- Format registri dirjen ("Registri HT, DM, IMT, dan Dislipidemia" V8juni2026)
  adalah berkas kerja internal Dirjen — legend di dalamnya (O15/O16, T15, T16,
  B23) yang dikutip sebagai teks label di atas.
