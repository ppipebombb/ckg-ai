from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.report_progress import WarmProgress


# ── Follow-up reading (one EPUS visit) ───────────────────────────────────
class DmFollowUpReading(BaseModel):
    """One kunjungan with a glucose reading — every visit in the month is listed
    (date order), each evaluated independently against the U17 target.
    ``tanggal`` is null for a Missed Visit (a month with no kunjungan).

    Expect most of these to be sparse: measured on live data, only ~4% of
    ePuskesmas visits carry any glucose value at all (vs blood pressure, which
    is recorded at nearly every visit). That emptiness is the intended signal.
    """

    tanggal: date | None = None  # the visit (scrape) date — Tanggal Pemeriksaan
    gds: float | None = None  # Gula Darah Sewaktu (mg/dL)
    gdp: float | None = None  # Gula Darah Puasa (mg/dL)
    gd2pp: float | None = None  # Gula Darah 2 Jam Post Prandial (mg/dL)
    hba1c: float | None = None  # HbA1C (%)
    # Legend (U17) wording: "Pasien DM terkendali (target tercapai)" |
    # "... tidak terkendali (target tidak tercapai)" | "Pasien Missed Visit" | ""
    interpretasi: str = ""
    obat: list[str] = Field(default_factory=list)  # antidiabetics for the visit


# ── Per-field source provenance ──────────────────────────────────────────
class DmRegistrySources(BaseModel):
    """Which source each baseline value came from — "ASIK" | "EPUS" | None
    (field absent). ASIK is the source of truth; ePuskesmas (EPUS) is the
    per-field fallback. Follow Up is always ePuskesmas (not surfaced here).
    Shown as small tags in the dashboard detail panel.

    ``gula_darah`` is one tag for the whole reading block: the CKG values are
    split across several ASIK layanan and merged per field, so a single
    per-slot tag would be misleading.
    """

    gula_darah: str | None = None
    riwayat_dm: str | None = None
    obat: str | None = None


# ── Registry row (one patient / NIK) ─────────────────────────────────────
class DmRegistryRow(BaseModel):
    """One patient (NIK) in the Diabetes Melitus registry."""

    puskesmas_name: str
    tahun_pelaporan: int

    # Identitas
    nik: str
    nama: str
    jenis_kelamin: str = ""
    tanggal_lahir: date | None = None
    no_tlp: str = ""
    alamat: str = ""

    # Baseline "Hasil pemeriksaan Gula Darah" (on Tanggal Berkunjung)
    tanggal_berkunjung: date | None = None  # earliest MATCHED/CKG visit date
    riwayat_dm: str = "Tidak"  # "Ya" | "Tidak"
    gds1: float | None = None
    gds2: float | None = None
    gdp: float | None = None
    gd2pp: float | None = None
    hba1c: float | None = None
    # "Diabetes Melitus" | "Prediabetes" | "Normal" |
    # "Tidak dapat diinterpretasikan" | ""
    interpretasi: str = ""
    obat: list[str] = Field(default_factory=list)  # baseline visit drug list

    # Per-field source provenance (ASIK / ePuskesmas) for the dashboard.
    sources: DmRegistrySources = Field(default_factory=DmRegistrySources)

    # Follow Up: month number (1..12) → readings in that month
    followup: dict[int, list[DmFollowUpReading]] = Field(default_factory=dict)


class DmRegistryDashboardOut(BaseModel):
    """Paginated registry response with cache metadata (mirrors the Hipertensi
    registry: cache_hit + computed_at + computing so the UI can show
    fresh/cached status and a cold cache returns immediately)."""

    items: list[DmRegistryRow]
    total: int
    # Interpretasi-band split of ``total`` (they sum to it): Diabetes Melitus vs
    # Prediabetes. Respects the search filter, like ``total``.
    total_dm: int = 0
    total_prediabetes: int = 0
    page: int
    size: int
    pages: int
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
    progress: WarmProgress | None = None  # approx warm progress while computing


class DmRegistrySummaryOut(BaseModel):
    """Per-puskesmas aggregate counts over the DM registry: total pasien (CKG)
    split into Diabetes Melitus / Prediabetes bands, pasien dengan riwayat DM
    (Ya), dan pasien dalam pengobatan (≥1 obat diresepkan pada baseline). Same
    cache metadata so a cold cache returns immediately and the caller polls back."""

    total: int
    total_dm: int = 0
    total_prediabetes: int = 0
    riwayat_dm_ya: int
    dalam_pengobatan: int
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
