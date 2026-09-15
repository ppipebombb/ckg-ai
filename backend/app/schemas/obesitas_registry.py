from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.report_progress import WarmProgress


# ── Follow-up reading (one EPUS visit) ───────────────────────────────────
class ObesitasFollowUpReading(BaseModel):
    """One kunjungan with an anthropometry reading — every visit in the month is
    listed (date order), each evaluated independently against the L16 target.
    ``tanggal`` is null for a Missed Visit.

    Missed Visit rows appear only in the CONTROL WINDOW (baseline month +3 … +6):
    the sheet evaluates the target "pada 3-6 bulan berikutnya", so an empty month
    outside that window is simply blank, not a missed one.
    """

    tanggal: date | None = None  # the visit (scrape) date — Tanggal Pemeriksaan
    bb: float | None = None  # Berat Badan (kg)
    tb: float | None = None  # Tinggi Badan (cm)
    imt: float | None = None  # DERIVED: BB / (TB/100)^2, 1 decimal
    # Weight change from the CKG baseline weight, POSITIVE for a loss (so it
    # reads the same way the legend words the target, "penurunan BB >5%").
    # Negative = the patient gained weight. Null when either weight is missing.
    penurunan_pct: float | None = None
    # Legend (L16) wording: "Pasien Obesitas dengan target tercapai" |
    # "Pasien Obesitas dengan target tidak tercapai" | "Pasien Missed Visit" | ""
    interpretasi: str = ""


# ── Per-field source provenance ──────────────────────────────────────────
class ObesitasRegistrySources(BaseModel):
    """Which source each baseline value came from — "ASIK" | "EPUS" | None
    (field absent). ASIK is the source of truth; ePuskesmas (EPUS) is the
    per-field fallback. Follow Up is always ePuskesmas (not surfaced here).
    Shown as small tags in the dashboard detail panel.

    ``antropometri`` is one tag for BB and TB together: the two are merged per
    field from one form, so a per-slot tag would be misleading. IMT has no tag at
    all — it is derived here, never sourced.
    """

    antropometri: str | None = None
    riwayat_ht: str | None = None
    riwayat_dm: str | None = None


# ── Registry row (one patient / NIK) ─────────────────────────────────────
class ObesitasRegistryRow(BaseModel):
    """One patient (NIK) in the Obesitas registry."""

    puskesmas_name: str
    tahun_pelaporan: int

    # Identitas. The sheet's "Identitas Pasien" band runs A–I, i.e. it also
    # covers Tanggal Berkunjung and both Riwayat columns below.
    nik: str
    nama: str
    jenis_kelamin: str = ""
    tanggal_lahir: date | None = None
    no_tlp: str = ""
    alamat: str = ""
    tanggal_berkunjung: date | None = None  # earliest MATCHED/CKG visit date
    # Reported, NOT filtered on — the registry admits on IMT alone.
    riwayat_ht: str = "Tidak"  # "Ya" | "Tidak"
    riwayat_dm: str = "Tidak"  # "Ya" | "Tidak"

    # Baseline "Hasil Pemeriksaan Antopometri" (on Tanggal Berkunjung)
    bb: float | None = None  # Berat Badan (kg)
    tb: float | None = None  # Tinggi Badan (cm)
    imt: float | None = None  # DERIVED — ASIK ships no adult IMT value
    # "Obesitas I" | "Obesitas II" | "Normal" | "" — every row in the registry is
    # Obesitas I or II by construction (the syarat filter); the other values
    # exist because the same model is used before filtering.
    interpretasi: str = ""

    # Per-field source provenance (ASIK / ePuskesmas) for the dashboard.
    sources: ObesitasRegistrySources = Field(
        default_factory=ObesitasRegistrySources
    )

    # Follow Up: month number (1..12) → readings in that month
    followup: dict[int, list[ObesitasFollowUpReading]] = Field(default_factory=dict)


class ObesitasRegistryDashboardOut(BaseModel):
    """Paginated registry response with cache metadata (mirrors the Hipertensi,
    DM and Dislipidemia registries: cache_hit + computed_at + computing so the UI
    can show fresh/cached status and a cold cache returns immediately)."""

    items: list[ObesitasRegistryRow]
    total: int
    # Band counts over the (search-filtered) rows. Unlike the Dislipidemia
    # registry's four overlapping analyte counts these are MUTUALLY EXCLUSIVE and
    # DO sum to ``total`` — the syarat is one IMT scale cut in two.
    obesitas_1: int = 0  # IMT 25 – <30
    obesitas_2: int = 0  # IMT >= 30
    page: int
    size: int
    pages: int
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
    progress: WarmProgress | None = None  # approx warm progress while computing


class ObesitasRegistrySummaryOut(BaseModel):
    """Per-puskesmas aggregate counts over the Obesitas registry: total pasien
    (CKG), the two IMT bands, dan pasien dengan riwayat HT / DM (Ya). There is no
    "dalam pengobatan" count — the Obesitas sheet has no Jenis Obat column.
    Same cache metadata so a cold cache returns immediately and the caller polls
    back."""

    total: int
    obesitas_1: int = 0
    obesitas_2: int = 0
    riwayat_ht_ya: int
    riwayat_dm_ya: int
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
