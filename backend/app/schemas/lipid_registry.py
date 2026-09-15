from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.report_progress import WarmProgress


# ── Follow-up reading (one EPUS visit) ───────────────────────────────────
class LipidFollowUpReading(BaseModel):
    """One kunjungan with a lipid reading — every visit in the month is listed
    (date order), each evaluated independently against the N17 target.
    ``tanggal`` is null for a Missed Visit.

    Missed Visit rows appear only in CONTROL months (baseline month +3/+6/+9/
    +12): the sheet evaluates the target "pada kunjungan 3 bulan berikutnya", so
    an empty non-control month is simply blank, not a missed one.

    Expect these to be sparse. ASIK's lipid form is gated to ≥40 yrs AND
    HT/DM patients, and ePuskesmas records a lipid panel far less often than a
    blood pressure. That emptiness is the intended signal.
    """

    tanggal: date | None = None  # the visit (scrape) date — Tanggal Pemeriksaan
    kol_total: float | None = None  # Kolesterol Total (mg/dL)
    ldl: float | None = None  # LDL (mg/dL)
    hdl: float | None = None  # HDL (mg/dL)
    trigliserida: float | None = None  # Trigliserida (mg/dL)
    # Legend (N17) wording: "Pasien Dislipidemia terkendali (target tercapai)" |
    # "... tidak terkendali (target tidak tercapai)" | "Pasien Missed Visit" | ""
    interpretasi: str = ""
    obat: list[str] = Field(default_factory=list)  # lipid drugs for the visit


# ── Per-field source provenance ──────────────────────────────────────────
class LipidRegistrySources(BaseModel):
    """Which source each baseline value came from — "ASIK" | "EPUS" | None
    (field absent). ASIK is the source of truth; ePuskesmas (EPUS) is the
    per-field fallback. Follow Up is always ePuskesmas (not surfaced here).
    Shown as small tags in the dashboard detail panel.

    ``lipid`` is one tag for the whole panel: the four analytes are merged per
    field, so a single per-slot tag would be misleading.
    """

    lipid: str | None = None
    riwayat_ht: str | None = None
    riwayat_dm: str | None = None
    obat: str | None = None


# ── Registry row (one patient / NIK) ─────────────────────────────────────
class LipidRegistryRow(BaseModel):
    """One patient (NIK) in the Dislipidemia registry."""

    puskesmas_name: str
    tahun_pelaporan: int

    # Identitas
    nik: str
    nama: str
    jenis_kelamin: str = ""
    tanggal_lahir: date | None = None
    no_tlp: str = ""
    alamat: str = ""

    # Baseline "Hasil pemeriksaan Lipid" (on Tanggal Berkunjung)
    tanggal_berkunjung: date | None = None  # earliest MATCHED/CKG visit date
    # Reported, NOT filtered on — the registry admits on measurement alone.
    riwayat_ht: str = "Tidak"  # "Ya" | "Tidak"
    riwayat_dm: str = "Tidak"  # "Ya" | "Tidak"
    kol_total: float | None = None
    ldl: float | None = None
    hdl: float | None = None
    trigliserida: float | None = None
    # "Dislipidemia" | "Normal" | "" — every row in the registry is
    # "Dislipidemia" by construction (the syarat filter); the other values exist
    # because the same model is used before filtering.
    interpretasi: str = ""
    obat: list[str] = Field(default_factory=list)  # baseline visit drug list

    # Per-field source provenance (ASIK / ePuskesmas) for the dashboard.
    sources: LipidRegistrySources = Field(default_factory=LipidRegistrySources)

    # Follow Up: month number (1..12) → readings in that month
    followup: dict[int, list[LipidFollowUpReading]] = Field(default_factory=dict)


class LipidRegistryDashboardOut(BaseModel):
    """Paginated registry response with cache metadata (mirrors the Hipertensi
    and DM registries: cache_hit + computed_at + computing so the UI can show
    fresh/cached status and a cold cache returns immediately)."""

    items: list[LipidRegistryRow]
    total: int
    # Per-analyte abnormal counts over the (search-filtered) rows. These OVERLAP
    # and do NOT sum to ``total`` — the syarat is an OR of four thresholds and
    # one patient routinely breaches several. Unlike the HT/DM registries there
    # is no middle band to split the total into; this sheet defines none.
    kol_total_tinggi: int = 0
    ldl_tinggi: int = 0
    hdl_rendah: int = 0
    trigliserida_tinggi: int = 0
    page: int
    size: int
    pages: int
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
    progress: WarmProgress | None = None  # approx warm progress while computing


class LipidRegistrySummaryOut(BaseModel):
    """Per-puskesmas aggregate counts over the Dislipidemia registry: total
    pasien (CKG), the four per-analyte counts (overlapping — see above), pasien
    dengan riwayat HT / DM (Ya), dan pasien dalam pengobatan (≥1 obat diresepkan
    pada baseline). Same cache metadata so a cold cache returns immediately and
    the caller polls back."""

    total: int
    kol_total_tinggi: int = 0
    ldl_tinggi: int = 0
    hdl_rendah: int = 0
    trigliserida_tinggi: int = 0
    riwayat_ht_ya: int
    riwayat_dm_ya: int
    dalam_pengobatan: int
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
