import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.gdp_report_job import GdpReportJob, GdpReportPhase, GdpReportStatus
from app.models.scrape_job import TriggererType
from app.schemas.report_progress import WarmProgress


class GdpReportJobCreate(BaseModel):
    puskesmas_id: uuid.UUID
    date_from: date
    date_to: date
    skip_asik_detail: bool = False

    @model_validator(mode="after")
    def _check(self) -> "GdpReportJobCreate":
        if self.date_from > self.date_to:
            raise ValueError("date_from must be <= date_to")
        # Cap range to one year. The orchestrator schedules one EPUS scrape per
        # NIK per date — at 4 months × 100 NIKs that is already ~12k jobs.
        if (self.date_to - self.date_from).days > 366:
            raise ValueError("date range must be <= 366 days")
        return self


class GdpReportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    puskesmas_id: uuid.UUID
    puskesmas_name: str
    date_from: date
    date_to: date
    triggered_by_id: uuid.UUID
    triggered_by_type: TriggererType
    status: GdpReportStatus
    phase: GdpReportPhase
    celery_task_id: str | None
    nik_total: int | None
    nik_done: int
    dates_total: int
    dates_done: int
    epus_jobs_total: int | None
    epus_jobs_done: int
    epus_jobs_failed: int
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    notes: str | None
    skip_asik_detail: bool
    created_at: datetime
    updated_at: datetime


def gdp_report_to_out(obj: GdpReportJob, puskesmas_name: str) -> GdpReportJobOut:
    return GdpReportJobOut(
        id=obj.id,
        puskesmas_id=obj.puskesmas_id,
        puskesmas_name=puskesmas_name,
        date_from=obj.date_from,
        date_to=obj.date_to,
        triggered_by_id=obj.triggered_by_id,
        triggered_by_type=obj.triggered_by_type,
        status=obj.status,
        phase=obj.phase,
        celery_task_id=obj.celery_task_id,
        nik_total=obj.nik_total,
        nik_done=obj.nik_done,
        dates_total=obj.dates_total,
        dates_done=obj.dates_done,
        epus_jobs_total=obj.epus_jobs_total,
        epus_jobs_done=obj.epus_jobs_done,
        epus_jobs_failed=obj.epus_jobs_failed,
        started_at=obj.started_at,
        finished_at=obj.finished_at,
        error_message=obj.error_message,
        notes=obj.notes,
        skip_asik_detail=obj.skip_asik_detail,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


class GdpReportLogOut(BaseModel):
    lines: list[str]


# ── Dashboard report row ─────────────────────────────────────────────────
class GdpReportRow(BaseModel):
    """One patient (NIK) row in the GDP per-month dashboard."""

    puskesmas_name: str
    tahun_pelaporan: int
    nama: str
    nik: str
    tanggal_diagnosis: date | None  # earliest EPUS visit date in selected year
    # Tertatalaksana checkboxes — derived from PTM > Pemeriksaan over the
    # year. Any visit reading sets the flag true.
    #   Pemberian Obat     ← Terapi Farmakologi == "Diberikan Obat"
    #   Pemberian Edukasi  ← Edukasi == "Ya"
    tertatalaksana_obat: bool = False
    tertatalaksana_edukasi: bool = False
    # Map of month number 1..12 → max GDP (mg/dl) for that month, or null.
    # float (not Decimal) so JSON serializes as number — frontend zod schema
    # validates with z.number().nullable(); Decimal would dump as string.
    gdp_by_month: dict[int, float | None] = Field(default_factory=dict)
    # Raw per-day readings for the "Full Review Diagnose" tab. Keyed by ISO
    # date → {"lab": value|null, "ptm": value|null}. Unlike gdp_by_month (one
    # collapsed lab>PTM pick), this keeps both sources separate per visit day.
    gdp_by_day: dict[str, dict[str, float | None]] = Field(default_factory=dict)
    # Terkendali columns — mirror the spreadsheet MAP/LAMBDA formulas. Values:
    # "Terkendali" | "Tidak terkendali" | "Tidak ada kunjungan" |
    # "Belum 3 bulan" | "" (when tanggal_diagnosis is missing).
    terkendali_bulan_berjalan: str = ""
    terkendali_tw1: str = ""
    terkendali_tw2: str = ""
    terkendali_tw3: str = ""
    terkendali_tw4: str = ""


class GdpReportDashboardOut(BaseModel):
    """Paginated dashboard response with cache metadata.

    Mirrors the Page[...] shape but adds `cache_hit` + `computed_at` so the UI
    can show fresh/cached status and expose a Clear-cache action.
    """

    items: list[GdpReportRow]
    total: int
    page: int
    size: int
    pages: int
    cache_hit: bool
    computed_at: datetime | None  # None while a background recompute is running
    computing: bool = False  # True → recompute enqueued, poll until data arrives
    progress: WarmProgress | None = None  # approx warm progress while computing
