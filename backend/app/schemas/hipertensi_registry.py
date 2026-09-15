from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.report_progress import WarmProgress


# ── Follow-up reading (one EPUS visit) ───────────────────────────────────
class FollowUpReading(BaseModel):
    """One kunjungan with a TD reading — every visit in the month is listed
    (date order), each evaluated independently. ``tanggal`` is null for a
    Missed Visit (a month with no kunjungan)."""

    tanggal: date | None = None  # the visit (scrape) date — Tanggal Pemeriksaan
    sys: float | None = None  # TD Sistolik (mmHg)
    dia: float | None = None  # TD Diastolik (mmHg)
    # Legend (O16) wording: "Pasien hipertensi terkendali (target tercapai)" |
    # "... tidak terkendali (target tidak tercapai)" | "Pasien Missed Visit" | ""
    interpretasi: str = ""
    obat: list[str] = Field(default_factory=list)  # antihypertensives for the visit


# ── Per-field source provenance ──────────────────────────────────────────
class RegistrySources(BaseModel):
    """Which source each baseline value came from — "ASIK" | "EPUS" | None
    (field absent). ASIK is the source of truth; ePuskesmas (EPUS) is the
    per-field fallback. TD2 is ASIK-only; Follow Up is always ePuskesmas (not
    surfaced here). Shown as small tags in the dashboard detail panel."""

    td1: str | None = None
    td2: str | None = None
    riwayat_ht: str | None = None
    obat: str | None = None


# ── Registry row (one patient / NIK) ─────────────────────────────────────
class HipertensiRegistryRow(BaseModel):
    """One patient (NIK) in the V8juni2026 Hipertensi registry."""

    puskesmas_name: str
    tahun_pelaporan: int

    # Identitas
    nik: str
    nama: str
    jenis_kelamin: str = ""
    tanggal_lahir: date | None = None
    no_tlp: str = ""
    alamat: str = ""

    # Baseline "Hasil pemeriksaan TD" (on Tanggal Berkunjung)
    tanggal_berkunjung: date | None = None  # earliest MATCHED/CKG visit date
    riwayat_ht: str = "Tidak"  # "Ya" | "Tidak"
    td_sys1: float | None = None
    td_dia1: float | None = None
    td_sys2: float | None = None
    td_dia2: float | None = None
    rerata_sys: float | None = None
    rerata_dia: float | None = None
    # "Hipertensi" | "Pre-Hipertensi" | "Normal" | ""
    interpretasi: str = ""
    obat: list[str] = Field(default_factory=list)  # baseline visit drug list

    # Per-field source provenance (ASIK / ePuskesmas) for the dashboard.
    sources: RegistrySources = Field(default_factory=RegistrySources)

    # Follow Up: month number (1..12) → readings in that month
    followup: dict[int, list[FollowUpReading]] = Field(default_factory=dict)


class HipertensiRegistryDashboardOut(BaseModel):
    """Paginated registry response with cache metadata (mirrors the GDP/HT
    dashboards: cache_hit + computed_at + computing so the UI can show
    fresh/cached status and a cold cache returns immediately)."""

    items: list[HipertensiRegistryRow]
    total: int
    # Interpretasi-band split of ``total`` (they sum to it): Hipertensi vs
    # Pre-Hipertensi. Respects the search filter, like ``total``.
    total_hipertensi: int = 0
    total_pre_hipertensi: int = 0
    page: int
    size: int
    pages: int
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
    progress: WarmProgress | None = None  # approx warm progress while computing


class HipertensiRegistrySummaryOut(BaseModel):
    """Per-puskesmas aggregate counts over the Hipertensi registry, for the
    dashboard 'Status per Puskesmas' card: total pasien (CKG) split into
    Hipertensi / Pre-Hipertensi bands, pasien dengan riwayat hipertensi (Ya), dan
    pasien dalam pengobatan (≥1 obat diresepkan pada baseline). Same cache
    metadata so a cold cache returns immediately and the caller polls back."""

    total: int
    total_hipertensi: int = 0
    total_pre_hipertensi: int = 0
    riwayat_ht_ya: int
    dalam_pengobatan: int
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
