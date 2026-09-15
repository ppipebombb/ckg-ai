# Halaman Registri Obesitas CKG (Kertas Kerja Obesitas)

Kertas kerja obesitas per **satu puskesmas + satu tahun pelaporan**, mengikuti
format registri dirjen (dokumen *"Register Sheet Pasien HT, DM, Dislipidemia dan
Obesitas"*, sheet **"Obesitas"**). Isinya: identitas pasien, hasil **pemeriksaan
antropometri** (berat badan, tinggi badan, dan IMT) pada tanggal berkunjung CKG,
dan follow-up **berat badan** pada **bulan kontrol (3–6 bulan setelah CKG)**.
Bisa diexport ke **Excel** — di file export, rumus tertanam langsung di sel
(klik sel IMT atau Interpretasi untuk melihatnya), dan ada sheet **"Formula &
Logika"** berisi penjelasan yang sama dengan kartu **"Cara Membaca Kertas Kerja
Ini"** di halaman.

Halaman ini bersaudara dengan Registri Hipertensi, Registri Diabetes Melitus,
dan Registri Dislipidemia: sumber datanya sama (kunjungan CKG yang sama), tapi
yang ditampilkan hasil timbang dan ukur tinggi badan.

**Cara pakai halaman:** pilih Puskesmas + Tahun Pelaporan (pilihan tahun = tahun
ini sampai 5 tahun ke belakang), lalu cari nama/NIK bila perlu. Klik baris pasien
untuk membuka detail (no. telepon, alamat, sumber data, dan tabel Follow Up per
bulan). Daftarnya dibagi **20 pasien per halaman**.

Keterangan di atas tabel berbunyi: **"N pasien (CKG) · Obesitas I … · Obesitas II
…"**. **Kedua angka itu saling terpisah dan HABIS dijumlahkan menjadi total** —
satu skala IMT yang dibelah dua, jadi setiap pasien masuk tepat satu kategori.
Ini berbeda dari Registri Dislipidemia, yang keempat rinciannya justru saling
tumpang tindih dan tidak boleh dijumlahkan.

Kolom **"Follow-up"** di tabel utama berisi **angka** = jumlah baris Follow Up
pasien itu — gabungan kunjungan yang ada hasil timbangnya **dan** bulan kontrol
berstatus **Missed Visit**. Rinciannya muncul saat baris pasien diklik.

Saat perhitungan pertama berjalan muncul tulisan **"Loading registri obesitas…"**
beserta bilah kemajuan; hasilnya lalu disimpan (cache ±30 jam) dan dihitung ulang
otomatis tiap pagi. Keterangan **"Computed &lt;waktu&gt; · cached/fresh"**
menunjukkan kapan angka itu dihitung.

Format dirjen untuk registri Obesitas ini **berlaku mulai 1 Januari 2026** (catatan
"cut off mulai 1 jan 2026" pada sheet aslinya). Tahun sebelumnya tetap bisa dipilih
di halaman, tetapi pencatatan berat dan tinggi badannya biasanya jauh lebih sedikit.

## Inti — satu daftar, dua pertanyaan

Kolom hasil pemeriksaan menjawab: **seberapa berat pasien SAAT skrining CKG?**
Kolom Follow Up menjawab: **pada kontrol 3–6 bulan setelahnya, apakah berat
badannya sudah turun cukup banyak?** Karena pertanyaannya berbeda, labelnya juga
berbeda — dan itu memang benar, bukan error.

## 1 · Arti singkatan dan cara IMT dihitung

- **BB** — berat badan, dalam kilogram (kg).
- **TB** — tinggi badan, dalam sentimeter (cm).
- **IMT** — Indeks Massa Tubuh, satuannya kg/m². Inilah angka yang menentukan
  siapa yang masuk daftar.

**Rumusnya: IMT = berat badan (kg) dibagi kuadrat tinggi badan (meter).**
Contoh: BB 78 kg, TB 165 cm = 1,65 m → 78 ÷ (1,65 × 1,65) = **28,7**. Dibulatkan
1 angka di belakang koma.

Angka IMT ini **dihitung sendiri oleh sistem**, bukan diambil apa adanya dari
ASIK maupun ePuskesmas: untuk pasien dewasa, ASIK hanya menyimpan berat dan
tinggi badan (IMT-nya tidak dikirim balik), dan ePuskesmas hanya menyimpan
kategori teksnya. Di file Excel, kolom IMT juga berupa rumus hidup — kalau BB
atau TB dikoreksi, IMT dan labelnya ikut berubah otomatis.

Pembulatan dilakukan **sebelum** label ditentukan, supaya label selalu cocok
dengan angka yang tertulis di sebelahnya. Jadi IMT yang ditulis 25,0 pasti
berlabel Obesitas I, tidak pernah "25,0 tapi Normal".

## 2 · Siapa yang masuk daftar ini (Syarat)

Pasien (per NIK) masuk daftar jika punya **minimal satu kunjungan CKG**
(kunjungan yang tercatat di ePus DAN ASIK) pada tahun itu, **DAN** IMT-nya
mencapai ambang berikut:

- **Obesitas I** — IMT **25 sampai di bawah 30** (tepat 25,0 sudah masuk);
- **Obesitas II** — IMT **30 ke atas** (tepat 30,0 sudah masuk).

Sheet aslinya menulis batas Obesitas I sebagai "IMT 25-29.9". Angka di
antara 29,9 dan 30 dihitung sebagai **Obesitas I**, supaya tidak ada pasien yang
jatuh di celah antara kedua kategori.

**Kolom "Riwayat diagnosis HT" dan "Riwayat diagnosis DM" hanya informasi, bukan
syarat masuk.** Kedua kolom itu ditampilkan supaya terlihat pasien mana yang
punya penyakit penyerta, tapi **tidak** menentukan siapa yang masuk daftar. Yang
menentukan hanya **pengukuran** BB dan TB-nya. Pasien dengan IMT 32 tetap masuk
daftar walaupun belum pernah didiagnosis hipertensi maupun diabetes.

**Yang tidak ditampilkan:** pasien dengan IMT di bawah 25, dan pasien yang berat
**atau** tinggi badannya tidak tercatat — tanpa keduanya IMT tidak bisa dihitung.

Kalau seorang pasien "hilang" dari daftar, urutan pemeriksaannya: (a) apakah
kunjungannya sudah cocok di kedua sumber (pasien CKG)? (b) apakah berat **dan**
tinggi badannya sudah dicatat? (c) kalau sudah, apakah IMT-nya memang di bawah 25?

## 3 · Arti label Interpretasi (saat kunjungan CKG)

- **Obesitas I** — IMT 25 sampai di bawah 30 kg/m².
- **Obesitas II** — IMT 30 kg/m² ke atas.
- **Normal** — sudah diukur, tapi IMT-nya masih di bawah 25. Pasien seperti ini
  **tidak** muncul di daftar. Label ini hanya berarti "di bawah ambang obesitas"
  — format dirjen tidak membagi lagi wilayah di bawah 25, jadi kurus dan berat
  badan lebih tidak dibedakan di sini.
- **Kosong** — berat atau tinggi badan tidak tercatat pada kunjungan itu, jadi
  IMT tidak bisa dihitung. Kosong **bukan** berarti normal.

Karena syaratnya di bagian 2, semua baris yang tampil di halaman ini berlabel
**Obesitas I** atau **Obesitas II**. Label **Normal** dan kosong baru terlihat di
file Excel kalau isi selnya diubah sendiri (rumusnya hidup di sana).

**Beda penting dari Registri Hipertensi dan Diabetes Melitus:** di dua kertas
kerja itu, pasien yang sudah punya diagnosis SELALU diberi label penyakitnya
walaupun hasil ukur hari itu bagus. **Di sini tidak.** Label di sini mengikuti
hasil **pengukuran** — sama seperti Registri Dislipidemia.

## 4 · Cara baca Follow Up

Follow Up mulai **bulan SETELAH** bulan skrining CKG. Bulan skrining sendiri
tidak diulang karena sudah ada di bagian hasil pemeriksaan.

**Kontrolnya dijadwalkan 3–6 bulan setelah skrining.** Format dirjen menilai
target "penurunan BB pada **3-6 bulan** berikutnya", jadi bulan kontrol pasien
adalah bulan ke-**3, 4, 5, dan 6** setelah bulan skrining CKG-nya. Contoh: pasien
yang skrining CKG pada Januari punya bulan kontrol April, Mei, Juni, dan Juli.

Ini **berbeda** dari Registri Hipertensi dan Registri Diabetes Melitus (kontrol
**bulanan**) maupun Registri Dislipidemia (kontrol **tiap 3 bulan**: bulan ke-3,
6, 9, 12). Jangan samakan ketiganya.

Status tiap kunjungan:

- **"Pasien Obesitas dengan target tercapai"** — berat badan turun **lebih dari
  5%** dibanding berat saat skrining CKG.
- **"Pasien Obesitas dengan target tidak tercapai"** — penurunan **5% atau
  kurang**, termasuk kalau beratnya tetap atau justru naik.
- **"Pasien Missed Visit"** — **hanya muncul di bulan kontrol** (bulan ke-3 s/d
  ke-6 setelah skrining) yang tidak punya satu pun hasil pengukuran.

Perhatikan batasnya: penurunan **tepat 5,0% belum** dihitung tercapai; harus
lebih dari itu. Ini mengikuti legenda format dirjen yang menulis ">5%" untuk
target tercapai dan "<=5%" untuk target tidak tercapai.

**Pembandingnya selalu berat badan saat skrining CKG**, bukan berat kunjungan
sebelumnya. Jadi persentase penurunannya selalu dihitung dari titik awal yang
sama dan bisa dibandingkan antar bulan. Angka itu ditampilkan langsung di kolom
**"Δ BB vs CKG"** pada panel detail pasien (tanda minus = turun, plus = naik).

**Bulan ke-1, ke-2, dan bulan ke-7 ke atas sengaja dibiarkan kosong**, bukan
ditandai Missed Visit — memang tidak ada kontrol yang dijadwalkan di bulan itu,
jadi tidak adil kalau dihitung terlewat. Bulan kontrol yang belum terjadi juga
dibiarkan kosong.

Kalau pasien ditimbang beberapa kali dalam sebulan, **semua** kunjungannya
ditampilkan berurutan, masing-masing dengan tanggal, hasil, dan statusnya
sendiri. Penimbangan di luar bulan kontrol tetap dicatat dan tetap dinilai.

Kunjungan yang **hanya mencatat tinggi badan** tetap ditampilkan (kolom TB
terisi), tetapi kolom Interpretasinya dibiarkan kosong — tanpa berat badan tidak
ada penurunan yang bisa dihitung. Kunjungan yang **tidak mencatat BB maupun TB**
tidak muncul sebagai baris Follow Up sama sekali; kalau kunjungan seperti itu
jatuh di bulan kontrol, bulan itu tetap ditandai **"Pasien Missed Visit"**
walaupun pasiennya datang — yang terlewat adalah *penimbangannya*, bukan
kunjungannya.

Kategori **"Loss to Follow Up (LTFU)"** yang ada di legenda format dirjen belum
dipakai di kertas kerja ini: definisinya butuh 12 bulan berturut-turut tanpa
kunjungan, sedangkan kertas kerja ini dihitung per satu tahun pelaporan.

## 5 · Kenapa banyak kolom Follow Up yang kosong

Karena berat badan **jarang ditimbang ulang di kunjungan biasa**. Saat skrining
CKG hampir semua peserta diukur BB dan TB-nya, tapi pada kunjungan berobat
berikutnya sering tidak dicatat lagi di ePuskesmas.

Kolom kosong berarti pengukurannya **tidak tercatat** — bukan kesalahan sistem.
Justru inilah yang perlu diperbaiki: makin rutin berat badan ditimbang dan
dicatat, makin berguna kertas kerja ini.

## 6 · Dari mana tiap angka diambil (sumber data)

Untuk bagian **hasil pemeriksaan saat CKG**: **ASIK** (data skrining CKG) adalah
sumber utama, **ePuskesmas** mengisi yang kosong — per kolom, jadi satu pasien
bisa punya berat badan dari ASIK dan tinggi badan dari ePuskesmas. Di panel
detail pasien ada label kecil **ASIK** / **ePus** yang menunjukkan sumbernya.
**IMT tidak punya label sumber** karena memang dihitung sendiri dari BB dan TB.

Untuk bagian **Follow Up**: selalu dari **ePuskesmas** (kunjungan bulan-bulan
berikutnya memang tercatat di sana).

Identitas (nama, jenis kelamin, tanggal lahir, no. telepon, alamat) juga ASIK
dulu, ePuskesmas mengisi yang kosong.

Tanggal Berkunjung = tanggal kunjungan CKG **paling awal** pada tahun itu.

Kolom Riwayat HT dan Riwayat DM memakai catatan diagnosis yang sama persis dengan
yang dipakai Registri Hipertensi dan Registri Diabetes Melitus, jadi artinya
konsisten antar halaman: jawaban skrining CKG di ASIK, diagnosis pada tatalaksana
di ASIK, atau diagnosis di ePuskesmas. Cukup salah satu; sekali tercatat, tetap
**Ya**.

**Angka yang tidak masuk akal diabaikan:** berat badan di luar 20–400 kg atau
tinggi badan di luar 80–250 cm dianggap salah ketik dan diperlakukan sebagai
"tidak terukur" — bukan dipaksa masuk ke perhitungan. Kalau seorang pasien
IMT-nya kosong padahal terasa sudah diukur, salah satu sebabnya bisa ini
(misalnya tinggi badan tercatat "1,65" dalam meter, bukan "165" dalam cm).

## 7 · Tidak ada kolom Jenis Obat

Berbeda dengan Registri Hipertensi, Diabetes Melitus, dan Dislipidemia, sheet
Obesitas pada format dirjen **tidak punya kolom Jenis Obat**, jadi halaman ini
juga tidak menampilkan daftar obat dan tidak punya hitungan "pasien dalam
pengobatan".

## 8 · Dasar aturan

- Ambang Obesitas I (IMT 25) dan Obesitas II (IMT 30), target penurunan berat
  badan >5%, jadwal kontrol 3–6 bulan, dan catatan "cut off mulai 1 Jan 2026" —
  dokumen dirjen "Register Sheet Pasien HT, DM, Dislipidemia dan Obesitas",
  sheet "Obesitas".
- Pengukuran berat dan tinggi badan di CKG (paket "Gizi (BB - TB - Lingkar
  Perut)") — Juknis CKG (KMK 84/2026).
