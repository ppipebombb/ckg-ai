from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.report_progress import WarmProgress


# ── Dashboard report row ─────────────────────────────────────────────────
class HipertensiReportRow(BaseModel):
    """One patient (NIK) row in the Hipertensi per-month dashboard."""

    puskesmas_name: str
    tahun_pelaporan: int
    nama: str
    nik: str
    tanggal_diagnosis: date | None  # earliest EPUS visit date in selected year
    # Tertatalaksana checkboxes — derived from PTM > Pemeriksaan over the year.
    #   Pemberian Obat     ← Terapi Farmakologi == "Diberikan Obat"
    #   Pemberian Edukasi  ← Edukasi == "Ya"
    tertatalaksana_obat: bool = False
    tertatalaksana_edukasi: bool = False
    # Map of month number 1..12 → latest Sistolik / Diastolik (mmHg) for that
    # month, or null. The pair is taken from the same chosen visit.
    sistolik_by_month: dict[int, float | None] = Field(default_factory=dict)
    diastolik_by_month: dict[int, float | None] = Field(default_factory=dict)
    # Raw per-day readings for the "Full Review Diagnose" tab. Keyed by ISO date
    # → {"sys": value|null, "dia": value|null} (one pair per visit day).
    bp_by_day: dict[str, dict[str, float | None]] = Field(default_factory=dict)
    # Terkendali columns — mirror the spreadsheet MAP/LAMBDA formulas. Green rule
    # is Sistole<140 AND Diastole<90. Values: "Terkendali" | "Tidak terkendali" |
    # "Tidak ada kunjungan" | "Belum 3 bulan" | "" (when tanggal_diagnosis is
    # missing).
    terkendali_bulan_berjalan: str = ""
    terkendali_tw1: str = ""
    terkendali_tw2: str = ""
    terkendali_tw3: str = ""
    terkendali_tw4: str = ""


class HipertensiReportDashboardOut(BaseModel):
    """Paginated dashboard response with cache metadata.

    Mirrors GdpReportDashboardOut: adds `cache_hit` + `computed_at` so the UI can
    show fresh/cached status and expose a Clear-cache action, and `computing` so
    a cold-cache request returns immediately while a background warm runs.
    """

    items: list[HipertensiReportRow]
    total: int
    page: int
    size: int
    pages: int
    cache_hit: bool
    computed_at: datetime | None  # None while a background recompute is running
    computing: bool = False  # True → recompute enqueued, poll until data arrives
    progress: WarmProgress | None = None  # approx warm progress while computing
