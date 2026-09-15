import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager, load_only

from app.api.deps import (
    Principal,
    get_dashboard_principal,
    get_db,
    get_principal,
)
from app.api.pagination import Page, PageParams, page_params
from app.celery_app import celery_app
from app.core.rate_limit import redis_client
from app.core.report_warm import make_progress_writer, read_progress, request_warm
from app.crud import gdp_report_job as crud
from app.crud import scrape_job as scrape_crud
from app.models.gdp_report_job import GdpReportJob, GdpReportStatus
from app.models.puskesmas import Puskesmas
from app.models.scrape_job import ScrapeJob, ScrapeStatus, TriggererType
from app.schemas.gdp_report import (
    GdpReportDashboardOut,
    GdpReportJobCreate,
    GdpReportJobOut,
    GdpReportRow,
    gdp_report_to_out,
)
from app.schemas.report_summary import (
    QuarterStatus,
    TerkendaliDashboardOut,
    TerkendaliSummaryOut,
)
from app.services.dashboard_scan import DashboardSpec, DecRows, scan_dashboard_payloads
from app.services.gdp_diagnose_export import build_gdp_diagnose_workbook
from app.services.gdp_export import build_gdp_workbook
from app.tasks.gdp_report import cancel_key

log = logging.getLogger(__name__)

router = APIRouter(tags=["gdp-report"])

# Dashboard cache: blob decryption is heavy; cache the per (puskesmas, year)
# aggregate (qualified NIKs + monthly values + name index). Search and
# pagination are applied on top of the cached aggregate. TTL is 30h — longer
# than the 24h nightly warm-up cron (5am) so the cache never expires in the
# 6h gap between two cron runs.
_DASHBOARD_CACHE_TTL_SECONDS = 30 * 60 * 60


def _dashboard_cache_key(puskesmas_id: uuid.UUID, year: int) -> str:
    return f"gdp_report:dashboard:{puskesmas_id}:{year}"


_LAB_TABLE_NAME = "Ubah Data Laboratorium"
# Pemeriksaan reads like "<CATEGORY> / Glukosa Puasa". The category prefix
# varies per puskesmas lab config ("Kimia Darah", "PEMERIKSAAN KIMIA KLINIK",
# …), so match only the exam name after the last "/". This still excludes
# "Glukosa Sewaktu", "Glukosa 2 Jam PP" and "Glukosa Urine".
_LAB_GDP_EXAM = "glukosa puasa"


def _is_lab_gdp_pemeriksaan(pem: str) -> bool:
    return pem.rsplit("/", 1)[-1].strip().lower() == _LAB_GDP_EXAM


def _parse_decimal(raw: Any) -> Decimal | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return Decimal(str(raw).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return None


def _extract_lab_gdp(epus_entry: Any) -> Decimal | None:
    """Pull `Hasil` for the "… / Glukosa Puasa" exam from EPUS lab table.

    Path: tabs.Laboratorium.tables["Ubah Data Laboratorium"] — list of dicts
    with keys like Pemeriksaan / Tarif / Hasil. Multiple matches in the same
    array → take the last entry (per-array latest).
    """
    if not isinstance(epus_entry, dict):
        return None
    rows = (
        ((epus_entry.get("tabs") or {}).get("Laboratorium") or {})
        .get("tables", {})
        .get(_LAB_TABLE_NAME)
    )
    if not isinstance(rows, list):
        return None
    last: Decimal | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        pem = row.get("Pemeriksaan")
        if not isinstance(pem, str) or not _is_lab_gdp_pemeriksaan(pem):
            continue
        v = _parse_decimal(row.get("Hasil"))
        if v is not None:
            last = v
    return last


def _ptm_pemeriksaan(epus_entry: Any) -> dict | None:
    """Return tabs.PTM.fields.Pemeriksaan dict, or None if missing/wrong shape."""
    if not isinstance(epus_entry, dict):
        return None
    pem = (
        ((epus_entry.get("tabs") or {}).get("PTM") or {})
        .get("fields", {})
        .get("Pemeriksaan")
        or {}
    )
    return pem if isinstance(pem, dict) else None


def _extract_ptm_gdp(epus_entry: Any) -> Decimal | None:
    """Pull "Pemeriksaan Gula Darah Puasa" from EPUS PTM tab.

    Path: tabs.PTM.fields.Pemeriksaan["Pemeriksaan Gula Darah Puasa"]. Read
    directly from the encrypted blob — the report computes GDP from the blob,
    not from any denormalized column.
    """
    pem = _ptm_pemeriksaan(epus_entry)
    if pem is None:
        return None
    return _parse_decimal(pem.get("Pemeriksaan Gula Darah Puasa"))


def _eligible_date(diag: date, offset_months: int) -> date:
    """Excel EOMONTH(diag, offset)+1 — first day of (diag.month + offset + 1)."""
    m = diag.month + offset_months + 1
    y = diag.year + (m - 1) // 12
    m = ((m - 1) % 12) + 1
    return date(y, m, 1)


def _classify_terkendali(value: float | None) -> str:
    if value is None:
        return ""
    return "Terkendali" if 80 <= value <= 130 else "Tidak terkendali"


def _compute_terkendali_quarter(
    monthly: dict[int, float | None],
    diag: date | None,
    tahun: int,
    months_window: tuple[int, int, int],
    cutoff_month: int,
) -> str:
    """Per-quarter status (TW1-4). Mirrors the spreadsheet MAP/LAMBDA formula.

    months_window: e.g. (1,2,3) for TW1.
    cutoff_month:  first month AFTER the quarter (4 for TW1, 7/10/12 …).
    """
    if diag is None:
        return ""
    eligible = _eligible_date(diag, 3)
    cutoff = date(tahun, cutoff_month, 1)
    if eligible >= cutoff:
        return "Belum 3 bulan"
    last_val: float | None = None
    for m in reversed(months_window):
        month_start = date(tahun, m, 1)
        if month_start < eligible:
            continue
        v = monthly.get(m)
        if v is None:
            continue
        last_val = v
        break
    if last_val is None:
        return "Tidak ada kunjungan"
    return _classify_terkendali(last_val)


def _compute_terkendali_berjalan(
    monthly: dict[int, float | None],
    diag: date | None,
    tahun: int,
) -> str:
    """Rolling-3-month status anchored on TODAY (mirrors spreadsheet)."""
    if diag is None:
        return ""
    today = date.today()
    bulan_aktif = today.month
    eligible = _eligible_date(diag, 3)
    if date(today.year, bulan_aktif, 1) < eligible:
        return "Belum 3 bulan"
    last_val: float | None = None
    for m in range(bulan_aktif, bulan_aktif - 3, -1):
        if m < 1 or m > 12:
            continue
        v = monthly.get(m)
        if v is None or v <= 0:
            continue
        last_val = v
        break
    if last_val is None:
        return "Tidak ada kunjungan"
    return _classify_terkendali(last_val)


def _extract_tertatalaksana(epus_entry: Any) -> tuple[bool, bool]:
    """Return (pemberian_obat, pemberian_edukasi) flags from PTM > Pemeriksaan.

      - Pemberian Obat checkbox    ← Terapi Farmakologi == "Diberikan Obat"
      - Pemberian Edukasi checkbox ← Edukasi == "Ya"

    Any other value (null, "Tidak", "Tidak Diberikan Obat", missing) → False.
    """
    pem = _ptm_pemeriksaan(epus_entry)
    if pem is None:
        return (False, False)
    farmakologi = pem.get("Terapi Farmakologi")
    edukasi = pem.get("Edukasi")
    obat = (
        isinstance(farmakologi, str) and farmakologi.strip() == "Diberikan Obat"
    )
    edukasi_flag = isinstance(edukasi, str) and edukasi.strip() == "Ya"
    return (obat, edukasi_flag)


_GDP_OUT_COLS = (
    GdpReportJob.id, GdpReportJob.puskesmas_id, GdpReportJob.date_from,
    GdpReportJob.date_to, GdpReportJob.triggered_by_id, GdpReportJob.triggered_by_type,
    GdpReportJob.status, GdpReportJob.phase, GdpReportJob.celery_task_id,
    GdpReportJob.nik_total, GdpReportJob.nik_done,
    GdpReportJob.dates_total, GdpReportJob.dates_done,
    GdpReportJob.epus_jobs_total, GdpReportJob.epus_jobs_done, GdpReportJob.epus_jobs_failed,
    GdpReportJob.started_at, GdpReportJob.finished_at, GdpReportJob.error_message,
    GdpReportJob.notes, GdpReportJob.skip_asik_detail,
    GdpReportJob.created_at, GdpReportJob.updated_at,
)


def _trigger_kind(principal: Principal) -> tuple[uuid.UUID, TriggererType]:
    if principal.typ == "admin":
        return principal.id, TriggererType.ADMIN
    return principal.id, TriggererType.USER


def _authorize(principal: Principal, puskesmas_id: uuid.UUID) -> None:
    # puskesmas-scope check, run BEFORE the resource is fetched (create /
    # dashboard endpoints): a user passing any non-own puskesmas_id gets 403
    # whether or not it exists, so there's no existence oracle to close here.
    if principal.typ == "user" and principal.puskesmas_id != puskesmas_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")


def _authorize_job(principal: Principal, puskesmas_id: uuid.UUID) -> None:
    # Object-level (run AFTER fetching a report job): a foreign job returns the
    # SAME 404 as a nonexistent one — no 403-vs-404 oracle on job ids.
    if principal.typ == "user" and principal.puskesmas_id != puskesmas_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")


@router.post(
    "/gdp-reports",
    response_model=GdpReportJobOut,
    status_code=status.HTTP_201_CREATED,
)
def create_gdp_report(
    body: GdpReportJobCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> GdpReportJobOut:
    _authorize(principal, body.puskesmas_id)
    pk = db.execute(
        select(
            Puskesmas.name,
            Puskesmas.asik_cred.isnot(None),
            Puskesmas.epus_cred.isnot(None),
            Puskesmas.asik_url, Puskesmas.epus_url,
        ).where(Puskesmas.id == body.puskesmas_id)
    ).one_or_none()
    if pk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    pk_name, has_asik, has_epus, asik_url, epus_url = pk
    if not (has_asik and has_epus):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ASIK and EPUS credentials must both be set on the puskesmas",
        )
    if not (asik_url and epus_url):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ASIK and EPUS base URLs must both be set on the puskesmas",
        )

    triggered_by_id, triggered_by_type = _trigger_kind(principal)
    try:
        job = crud.create(
            db,
            puskesmas_id=body.puskesmas_id,
            date_from=body.date_from,
            date_to=body.date_to,
            triggered_by_id=triggered_by_id,
            triggered_by_type=triggered_by_type,
            skip_asik_detail=body.skip_asik_detail,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a GDP report job is already running for this puskesmas",
        ) from e

    try:
        celery_app.send_task("gdp_report.run", args=[str(job.id)])
    except Exception as e:
        crud.mark_failed(db, job, f"broker unreachable: {e}", datetime.now(UTC))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "broker unavailable"
        ) from e

    return gdp_report_to_out(job, pk_name)


@router.get("/gdp-reports", response_model=Page[GdpReportJobOut])
def list_gdp_reports(
    params: PageParams = Depends(page_params),
    puskesmas_id: uuid.UUID | None = Query(None),
    job_status: GdpReportStatus | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> Page[GdpReportJobOut]:
    if principal.typ == "user":
        if puskesmas_id is not None and puskesmas_id != principal.puskesmas_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
        puskesmas_id = principal.puskesmas_id
    stmt = (
        select(GdpReportJob)
        .join(GdpReportJob.puskesmas)
        .options(
            load_only(*_GDP_OUT_COLS),
            contains_eager(GdpReportJob.puskesmas).load_only(Puskesmas.name),
        )
        .order_by(GdpReportJob.created_at.desc())
    )
    if puskesmas_id is not None:
        stmt = stmt.where(GdpReportJob.puskesmas_id == puskesmas_id)
    if job_status is not None:
        stmt = stmt.where(GdpReportJob.status == job_status)
    # Inline pagination (paginate() in pagination.py uses db.scalars which
    # works because GdpReportJob is the primary entity here).
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = db.scalar(count_stmt) or 0
    items = list(
        db.scalars(stmt.offset((params.page - 1) * params.size).limit(params.size)).all()
    )
    pages = (total + params.size - 1) // params.size if total else 0
    return Page[GdpReportJobOut](
        items=[gdp_report_to_out(i, i.puskesmas.name) for i in items],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )


def _gdp_fields(epus: Any) -> dict[str, Decimal | None]:
    """Per-day cell sources for GD Puasa — lab + PTM kept separate (diagnose tab)."""
    return {"lab": _extract_lab_gdp(epus), "ptm": _extract_ptm_gdp(epus)}


def _gdp_choose_month(dec_rows: DecRows) -> tuple[str | None, date | None]:
    """Month's GDP value: lab beats PTM, latest filter_date wins (rows are DESC).

    Returns (value_str, chosen_row_date); chosen_row_date feeds the per-NIK
    tanggal_diagnosis (earliest qualifying month, lab > PTM) — NOT MIN(filter_date).
    """
    for fd, epus in dec_rows:
        if epus is None:
            continue
        v = _extract_lab_gdp(epus)
        if v is not None:
            return str(v), fd
    for fd, epus in dec_rows:
        if epus is None:
            continue
        v = _extract_ptm_gdp(epus)
        if v is not None:
            return str(v), fd
    return None, None


# GD Puasa report spec for the shared single-pass scanner (app.services.dashboard_scan).
GDP_SPEC = DashboardSpec(extract_fields=_gdp_fields, choose_month=_gdp_choose_month)


def _compute_dashboard_payload(
    db: Session, puskesmas_id: uuid.UUID, year: int, *, progress=None
) -> dict:
    """Build the cacheable GD Puasa dashboard aggregate for (puskesmas, year):
    qualified NIKs + monthly values + per-NIK name/first_epus_date, in one decrypt
    pass. Search and pagination are applied on top of this payload at request time."""
    return scan_dashboard_payloads(
        db,
        puskesmas_id,
        year,
        {"gdp": GDP_SPEC},
        extract_tertatalaksana=_extract_tertatalaksana,
        progress=progress,
    )["gdp"]


def warm_gdp_dashboard(
    db: Session, rc, puskesmas_id: uuid.UUID, year: int, ttl: int
) -> dict:
    """Compute the dashboard aggregate and write it to Redis. Shared by the
    on-miss endpoint path and the nightly warm-up cron (cron.warm_reports)."""
    cache_key = _dashboard_cache_key(puskesmas_id, year)
    payload = _compute_dashboard_payload(
        db, puskesmas_id, year, progress=make_progress_writer(rc, cache_key)
    )
    try:
        rc.set(cache_key, json.dumps(payload), ex=ttl)
    except Exception as exc:
        log.warning("redis set failed for %s: %s", cache_key, exc)
    return payload


def _gdp_by_month_from_payload(
    monthly: dict[str, dict[str, str]], nik: str
) -> dict[int, float | None]:
    cell = monthly.get(nik) or {}
    out: dict[int, float | None] = {}
    for m in range(1, 13):
        v = cell.get(str(m))
        out[m] = float(v) if v is not None else None
    return out


def _gdp_by_day_from_payload(
    daily: dict[str, dict[str, dict[str, str | None]]], nik: str
) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    for d, c in (daily.get(nik) or {}).items():
        out[d] = {
            "lab": float(c["lab"]) if c.get("lab") is not None else None,
            "ptm": float(c["ptm"]) if c.get("ptm") is not None else None,
        }
    return out


@router.get("/gdp-reports/dashboard", response_model=GdpReportDashboardOut)
def gdp_report_dashboard(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    q: str | None = Query(None, max_length=64),
    ckg_only: bool = Query(False),
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> GdpReportDashboardOut:
    """Per-NIK GDP report.

    All Patient rows for the puskesmas and year, grouped by NIK regardless of
    match status (ASIK-only, EPUS-only, MATCHED). Eligibility AND output
    values both come from the encrypted EPUS blob:

      - Primary: tabs.Laboratorium.tables["Ubah Data Laboratorium"] row where
        Pemeriksaan == "Kimia Darah / Glukosa Puasa" → Hasil.
      - Fallback: tabs.PTM.fields.Pemeriksaan["Pemeriksaan Gula Darah Puasa"].

    A NIK is listed iff at least one Patient row in the year has either
    reading. Per (NIK, MONTH) value picks latest filter_date; lab beats PTM
    when same date carries both.

    Aggregate (NIKs + monthly values) is cached in Redis for 30 hours keyed by
    (puskesmas, year). Search and pagination are applied in-memory on top of
    the cached payload. Use DELETE /gdp-reports/dashboard/cache to force a
    rebuild.
    """
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    cache_key = _dashboard_cache_key(puskesmas_id, year)
    rc = redis_client()
    cached: str | None = None
    try:
        cached = rc.get(cache_key)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", cache_key, exc)

    cache_hit = False
    payload: dict | None = None
    if cached:
        try:
            payload = json.loads(cached)
            cache_hit = True
        except Exception:
            payload = None
            cache_hit = False
    if payload is None:
        # Decrypt scan can take minutes — recompute in the background and return
        # a `computing` placeholder so the request never blocks (no timeout).
        request_warm(rc, cache_key, "gdp_dashboard", {"puskesmas_id": str(puskesmas_id), "year": year})
        return GdpReportDashboardOut(
            items=[],
            total=0,
            page=params.page,
            size=params.size,
            pages=0,
            cache_hit=False,
            computed_at=None,
            computing=True,
            progress=read_progress(rc, cache_key),
        )

    niks: list[dict[str, Any]] = payload.get("niks") or []
    monthly: dict[str, dict[str, str]] = payload.get("monthly") or {}
    # Payloads cached before the diagnose tab lack "daily" → empty per row until
    # the cache is rebuilt (Clear cache / nightly warm).
    daily: dict[str, dict[str, dict[str, str | None]]] = payload.get("daily") or {}

    # CKG-only filter, applied in-memory on the cached payload. Payloads cached
    # before this field existed lack "tandai_ckg" → those NIKs are excluded
    # until the cache is rebuilt (Clear cache / nightly warm).
    if ckg_only:
        niks = [n for n in niks if n.get("tandai_ckg")]

    # Search filter (case-insensitive substring on nama OR nik).
    if q:
        needle = q.strip().casefold()
        if needle:
            niks = [
                n for n in niks
                if needle in n["nama"].casefold() or needle in n["nik"].casefold()
            ]

    total = len(niks)
    pages = (total + params.size - 1) // params.size if total else 0
    start = (params.page - 1) * params.size
    page_slice = niks[start : start + params.size]

    items: list[GdpReportRow] = []
    for n in page_slice:
        gdp_by_month = _gdp_by_month_from_payload(monthly, n["nik"])
        diag = (
            date.fromisoformat(n["first_epus_date"])
            if n.get("first_epus_date") else None
        )
        items.append(
            GdpReportRow(
                puskesmas_name=pk_name,
                tahun_pelaporan=year,
                nama=n["nama"],
                nik=n["nik"],
                tanggal_diagnosis=diag,
                tertatalaksana_obat=bool(n.get("tertatalaksana_obat", False)),
                tertatalaksana_edukasi=bool(n.get("tertatalaksana_edukasi", False)),
                gdp_by_month=gdp_by_month,
                gdp_by_day=_gdp_by_day_from_payload(daily, n["nik"]),
                terkendali_bulan_berjalan=_compute_terkendali_berjalan(
                    gdp_by_month, diag, year
                ),
                terkendali_tw1=_compute_terkendali_quarter(
                    gdp_by_month, diag, year, (1, 2, 3), 4
                ),
                terkendali_tw2=_compute_terkendali_quarter(
                    gdp_by_month, diag, year, (4, 5, 6), 7
                ),
                terkendali_tw3=_compute_terkendali_quarter(
                    gdp_by_month, diag, year, (7, 8, 9), 10
                ),
                terkendali_tw4=_compute_terkendali_quarter(
                    gdp_by_month, diag, year, (10, 11, 12), 12
                ),
            )
        )
    return GdpReportDashboardOut(
        items=items,
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
        cache_hit=cache_hit,
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        computing=False,
    )


def _export_filename(pk_name: str, year: int) -> str:
    """ASCII-safe attachment filename. Non-ASCII chars (rare in puskesmas
    names) are dropped so the Content-Disposition header stays valid."""
    safe = "".join(c if (c.isalnum() or c in " -_") else "_" for c in pk_name).strip()
    return f"GD Puasa - {safe or 'Puskesmas'} - {year}.xlsx"


@router.get("/gdp-reports/dashboard/export")
def export_gdp_dashboard(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    ckg_only: bool = Query(False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> StreamingResponse:
    """Download the GD Puasa report as an .xlsx for (puskesmas, year).

    Reuses the same cached aggregate as ``/gdp-reports/dashboard`` (no recompute)
    but emits ALL NIKs — no pagination or search. The Terkendali (S–W) and Rekap
    columns stay as live spreadsheet formulas; only the raw data columns (A–R) are
    filled. See ``app.services.gdp_export``.
    """
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    cache_key = _dashboard_cache_key(puskesmas_id, year)
    rc = redis_client()
    payload: dict | None = None
    try:
        cached = rc.get(cache_key)
        if cached:
            payload = json.loads(cached)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", cache_key, exc)
    if payload is None:
        payload = warm_gdp_dashboard(db, rc, puskesmas_id, year, _DASHBOARD_CACHE_TTL_SECONDS)

    niks: list[dict[str, Any]] = payload.get("niks") or []
    monthly: dict[str, dict[str, str]] = payload.get("monthly") or {}

    # Match the dashboard's CKG-only filter so the export reflects the view.
    if ckg_only:
        niks = [n for n in niks if n.get("tandai_ckg")]

    rows = [
        {
            "nama": n["nama"],
            "tanggal_diagnosis": (
                date.fromisoformat(n["first_epus_date"])
                if n.get("first_epus_date") else None
            ),
            "tertatalaksana_obat": bool(n.get("tertatalaksana_obat", False)),
            "tertatalaksana_edukasi": bool(n.get("tertatalaksana_edukasi", False)),
            "gdp_by_month": _gdp_by_month_from_payload(monthly, n["nik"]),
        }
        for n in niks
    ]

    content = build_gdp_workbook(pk_name, year, rows)
    filename = _export_filename(pk_name, year)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _diagnose_export_filename(pk_name: str, year: int) -> str:
    """ASCII-safe attachment filename for the Full Review Diagnose export."""
    safe = "".join(c if (c.isalnum() or c in " -_") else "_" for c in pk_name).strip()
    return f"Full Review Diagnosa - {safe or 'Puskesmas'} - {year}.xlsx"


@router.get("/gdp-reports/dashboard/diagnose-export")
def export_gdp_diagnose(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    ckg_only: bool = Query(False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> StreamingResponse:
    """Download the Full Review Diagnose view as an .xlsx for (puskesmas, year).

    Reuses the same cached aggregate as ``/gdp-reports/dashboard`` (no recompute)
    and emits ALL NIKs — no pagination or search — honoring the ``ckg_only``
    filter so the export matches the on-screen Diagnose table. One row per
    visit-day reading; see ``app.services.gdp_diagnose_export``.
    """
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    cache_key = _dashboard_cache_key(puskesmas_id, year)
    rc = redis_client()
    payload: dict | None = None
    try:
        cached = rc.get(cache_key)
        if cached:
            payload = json.loads(cached)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", cache_key, exc)
    if payload is None:
        payload = warm_gdp_dashboard(db, rc, puskesmas_id, year, _DASHBOARD_CACHE_TTL_SECONDS)

    niks: list[dict[str, Any]] = payload.get("niks") or []
    daily: dict[str, dict[str, dict[str, str | None]]] = payload.get("daily") or {}

    if ckg_only:
        niks = [n for n in niks if n.get("tandai_ckg")]

    rows = []
    for n in niks:
        by_day = _gdp_by_day_from_payload(daily, n["nik"])
        if not by_day:
            continue
        readings = [
            {"date": date.fromisoformat(iso), "lab": c["lab"], "ptm": c["ptm"]}
            for iso, c in sorted(by_day.items())
        ]
        rows.append({"nama": n["nama"], "nik": n["nik"], "readings": readings})

    content = build_gdp_diagnose_workbook(pk_name, year, rows)
    filename = _diagnose_export_filename(pk_name, year)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/gdp-reports/dashboard/cache", status_code=status.HTTP_204_NO_CONTENT)
def clear_gdp_dashboard_cache(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    principal: Principal = Depends(get_dashboard_principal),
) -> None:
    _authorize(principal, puskesmas_id)
    key = _dashboard_cache_key(puskesmas_id, year)
    rc = redis_client()
    try:
        rc.delete(key)
    except Exception as exc:
        log.warning("redis delete failed: %s", exc)
    # Start the recompute now so it's ready by the time the client polls back.
    request_warm(rc, key, "gdp_dashboard", {"puskesmas_id": str(puskesmas_id), "year": year})


# Status strings produced by _compute_terkendali_*; anything else (e.g. "" when
# there is no tanggal_diagnosis) falls into `tanpa_status`.
_TERKENDALI_BUCKETS = (
    "Terkendali",
    "Tidak terkendali",
    "Belum 3 bulan",
    "Tidak ada kunjungan",
)


def build_terkendali_summary(
    statuses: list[str], *, cache_hit: bool, computed_at: datetime | None
) -> TerkendaliSummaryOut:
    """Tally a list of per-NIK terkendali_bulan_berjalan strings into the summary
    schema. Shared by the GD Puasa and Hipertensi summary endpoints so both reports
    bucket statuses identically."""
    counts = dict.fromkeys(_TERKENDALI_BUCKETS, 0)
    tanpa = 0
    for s in statuses:
        if s in counts:
            counts[s] += 1
        else:
            tanpa += 1
    return TerkendaliSummaryOut(
        total=len(statuses),
        terkendali=counts["Terkendali"],
        tidak_terkendali=counts["Tidak terkendali"],
        belum_3_bulan=counts["Belum 3 bulan"],
        tidak_ada_kunjungan=counts["Tidak ada kunjungan"],
        tanpa_status=tanpa,
        cache_hit=cache_hit,
        computed_at=computed_at,
        computing=False,
    )


def _load_dashboard_cache(
    *,
    db: Session,
    principal: Principal,
    puskesmas_id: uuid.UUID,
    year: int,
    cache_key: str,
    report_type: str,
) -> tuple[dict | None, datetime | None]:
    """Authorize + read a report's Redis dashboard aggregate.

    Returns ``(payload, computed_at)`` on a hit. On a miss — no cache OR a cached
    payload that predates the ``computed_at`` field — enqueues a warm and returns
    ``(None, None)`` so the caller emits its ``computing`` placeholder. Shared by
    the /dashboard/summary and /dashboard/terkendali endpoints (GD Puasa + Hipertensi)."""
    _authorize(principal, puskesmas_id)
    if db.scalar(select(Puskesmas.id).where(Puskesmas.id == puskesmas_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    rc = redis_client()
    payload: dict | None = None
    try:
        cached = rc.get(cache_key)
        if cached:
            payload = json.loads(cached)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", cache_key, exc)

    computed_at_raw = payload.get("computed_at") if payload else None
    if payload is None or not computed_at_raw:
        request_warm(
            rc, cache_key, report_type,
            {"puskesmas_id": str(puskesmas_id), "year": year},
        )
        return None, None
    return payload, datetime.fromisoformat(computed_at_raw)


def dashboard_summary_response(
    *,
    db: Session,
    principal: Principal,
    puskesmas_id: uuid.UUID,
    year: int,
    cache_key: str,
    report_type: str,
    compute_statuses: Callable[[dict], list[str]],
) -> TerkendaliSummaryOut:
    """Shared body for the GD Puasa / Hipertensi ``/dashboard/summary`` endpoints.
    Tallies the per-NIK terkendali_bulan_berjalan statuses (the per-report
    difference is the ``compute_statuses`` callback)."""
    payload, computed_at = _load_dashboard_cache(
        db=db, principal=principal, puskesmas_id=puskesmas_id, year=year,
        cache_key=cache_key, report_type=report_type,
    )
    if payload is None:
        return TerkendaliSummaryOut(
            total=0, terkendali=0, tidak_terkendali=0, belum_3_bulan=0,
            tidak_ada_kunjungan=0, tanpa_status=0,
            cache_hit=False, computed_at=None, computing=True,
        )
    return build_terkendali_summary(
        compute_statuses(payload), cache_hit=True, computed_at=computed_at
    )


# Per-NIK quarter row: ((tw1..tw4 status strings), pemberian_obat, pemberian_edukasi)
DashboardRow = tuple[tuple[str, str, str, str], bool, bool]


def _tally_quarter(rows: list[DashboardRow], idx: int) -> QuarterStatus:
    terkendali = tidak = 0
    for tws, _obat, _edukasi in rows:
        s = tws[idx]
        if s == "Terkendali":
            terkendali += 1
        elif s == "Tidak terkendali":
            tidak += 1
    return QuarterStatus(
        terkendali=terkendali,
        tidak_terkendali=tidak,
        belum_atau_tidak_ada=len(rows) - terkendali - tidak,
    )


def build_terkendali_dashboard(
    rows: list[DashboardRow], *, cache_hit: bool, computed_at: datetime | None
) -> TerkendaliDashboardOut:
    """Tally per-NIK (tw1..tw4, obat, edukasi) rows into the dashboard aggregate.
    Shared by the GD Puasa and Hipertensi /dashboard/terkendali endpoints."""
    return TerkendaliDashboardOut(
        total=len(rows),
        tw1=_tally_quarter(rows, 0),
        tw2=_tally_quarter(rows, 1),
        tw3=_tally_quarter(rows, 2),
        tw4=_tally_quarter(rows, 3),
        pemberian_obat=sum(1 for _t, obat, _e in rows if obat),
        pemberian_edukasi=sum(1 for _t, _o, edukasi in rows if edukasi),
        cache_hit=cache_hit,
        computed_at=computed_at,
        computing=False,
    )


def dashboard_terkendali_response(
    *,
    db: Session,
    principal: Principal,
    puskesmas_id: uuid.UUID,
    year: int,
    cache_key: str,
    report_type: str,
    compute_rows: Callable[[dict], list[DashboardRow]],
) -> TerkendaliDashboardOut:
    """Shared body for the GD Puasa / Hipertensi ``/dashboard/terkendali`` endpoints."""
    payload, computed_at = _load_dashboard_cache(
        db=db, principal=principal, puskesmas_id=puskesmas_id, year=year,
        cache_key=cache_key, report_type=report_type,
    )
    if payload is None:
        z = QuarterStatus(terkendali=0, tidak_terkendali=0, belum_atau_tidak_ada=0)
        return TerkendaliDashboardOut(
            total=0, tw1=z, tw2=z, tw3=z, tw4=z,
            pemberian_obat=0, pemberian_edukasi=0,
            cache_hit=False, computed_at=None, computing=True,
        )
    return build_terkendali_dashboard(
        compute_rows(payload), cache_hit=True, computed_at=computed_at
    )


@router.get("/gdp-reports/dashboard/summary", response_model=TerkendaliSummaryOut)
def gdp_report_dashboard_summary(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> TerkendaliSummaryOut:
    """Terkendali Bulan Berjalan tally over ALL NIKs for (puskesmas, year).

    Reuses the same Redis aggregate as ``/gdp-reports/dashboard`` (no recompute)
    and the same ``_compute_terkendali_berjalan`` classifier — only the counts
    are returned, never the per-NIK rows. On a cold cache the recompute is
    enqueued and ``computing`` is set so the caller polls back.
    """
    def _statuses(payload: dict) -> list[str]:
        niks: list[dict[str, Any]] = payload.get("niks") or []
        monthly: dict[str, dict[str, str]] = payload.get("monthly") or {}
        return [
            _compute_terkendali_berjalan(
                _gdp_by_month_from_payload(monthly, n["nik"]),
                date.fromisoformat(n["first_epus_date"]) if n.get("first_epus_date") else None,
                year,
            )
            for n in niks
        ]

    return dashboard_summary_response(
        db=db,
        principal=principal,
        puskesmas_id=puskesmas_id,
        year=year,
        cache_key=_dashboard_cache_key(puskesmas_id, year),
        report_type="gdp_dashboard",
        compute_statuses=_statuses,
    )


@router.get(
    "/gdp-reports/dashboard/terkendali", response_model=TerkendaliDashboardOut
)
def gdp_report_dashboard_terkendali(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    ckg_only: bool = Query(False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> TerkendaliDashboardOut:
    """Per-quarter (TW1-4) terkendali tally + pemberian obat/edukasi counts over
    ALL NIKs for (puskesmas, year). Reuses the dashboard Redis cache (no recompute).

    ``ckg_only`` restricts the tally to NIKs flagged sudah CKG (same filter as
    ``/gdp-reports/dashboard``)."""
    def _rows(payload: dict) -> list[DashboardRow]:
        niks: list[dict[str, Any]] = payload.get("niks") or []
        if ckg_only:
            niks = [n for n in niks if n.get("tandai_ckg")]
        monthly: dict[str, dict[str, str]] = payload.get("monthly") or {}
        out: list[DashboardRow] = []
        for n in niks:
            gbm = _gdp_by_month_from_payload(monthly, n["nik"])
            diag = (
                date.fromisoformat(n["first_epus_date"])
                if n.get("first_epus_date")
                else None
            )
            tws = (
                _compute_terkendali_quarter(gbm, diag, year, (1, 2, 3), 4),
                _compute_terkendali_quarter(gbm, diag, year, (4, 5, 6), 7),
                _compute_terkendali_quarter(gbm, diag, year, (7, 8, 9), 10),
                _compute_terkendali_quarter(gbm, diag, year, (10, 11, 12), 12),
            )
            out.append(
                (
                    tws,
                    bool(n.get("tertatalaksana_obat")),
                    bool(n.get("tertatalaksana_edukasi")),
                )
            )
        return out

    return dashboard_terkendali_response(
        db=db,
        principal=principal,
        puskesmas_id=puskesmas_id,
        year=year,
        cache_key=_dashboard_cache_key(puskesmas_id, year),
        report_type="gdp_dashboard",
        compute_rows=_rows,
    )


@router.get("/gdp-reports/{job_id}", response_model=GdpReportJobOut)
def get_gdp_report(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> GdpReportJobOut:
    obj = db.scalar(
        select(GdpReportJob)
        .join(GdpReportJob.puskesmas)
        .options(
            load_only(*_GDP_OUT_COLS),
            contains_eager(GdpReportJob.puskesmas).load_only(Puskesmas.name),
        )
        .where(GdpReportJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj.puskesmas_id)
    return gdp_report_to_out(obj, obj.puskesmas.name)


@router.post("/gdp-reports/{job_id}/retry", response_model=GdpReportJobOut)
def retry_gdp_report(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> GdpReportJobOut:
    """Resume a CANCELLED or FAILED GDP report job from where it left off.

    Resets the job back to PENDING and re-queues the orchestrator. The
    orchestrator's _resume_or_spawn reuses any SUCCESS child (so a finished
    ASIK is not re-run) and waits on any still-RUNNING child.
    """
    obj = db.scalar(
        select(GdpReportJob)
        .join(GdpReportJob.puskesmas)
        .options(
            load_only(*_GDP_OUT_COLS),
            contains_eager(GdpReportJob.puskesmas).load_only(Puskesmas.name),
        )
        .where(GdpReportJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj.puskesmas_id)
    if obj.status not in (GdpReportStatus.CANCELLED, GdpReportStatus.FAILED):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"job is {obj.status.value}, only cancelled/failed jobs can be retried",
        )

    pk_name = obj.puskesmas.name
    crud.reset_for_retry(db, obj)
    # Clear cancel flag so a fresh orchestrator run is not aborted by a stale
    # cancel signal from the previous attempt.
    try:
        redis_client().delete(cancel_key(str(job_id)))
    except Exception:
        pass

    try:
        celery_app.send_task("gdp_report.run", args=[str(obj.id)])
    except Exception as e:
        crud.mark_failed(db, obj, f"broker unreachable: {e}", datetime.now(UTC))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "broker unavailable"
        ) from e

    db.refresh(obj)
    return gdp_report_to_out(obj, pk_name)


@router.post("/gdp-reports/{job_id}/cancel", response_model=GdpReportJobOut)
def cancel_gdp_report(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> GdpReportJobOut:
    obj = db.scalar(
        select(GdpReportJob)
        .join(GdpReportJob.puskesmas)
        .options(
            load_only(*_GDP_OUT_COLS),
            contains_eager(GdpReportJob.puskesmas).load_only(Puskesmas.name),
        )
        .where(GdpReportJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj.puskesmas_id)
    if obj.status not in (GdpReportStatus.PENDING, GdpReportStatus.RUNNING):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"job is {obj.status.value}, cannot cancel"
        )
    pk_name = obj.puskesmas.name
    crud.mark_cancelled(db, obj)
    rc = redis_client()
    rc.set(cancel_key(str(job_id)), "1", ex=86400)
    if obj.celery_task_id:
        try:
            celery_app.control.revoke(obj.celery_task_id, terminate=False)
        except Exception:
            pass

    # Cascade to children. Without this, scrape worker keeps running until its
    # subprocess finishes — orchestrator's redis-flag relay only fires while
    # it is in _wait_child, but the parent task may already have returned.
    children = db.scalars(
        select(ScrapeJob)
        .options(load_only(
            ScrapeJob.id, ScrapeJob.status, ScrapeJob.celery_task_id,
            ScrapeJob.finished_at,
        ))
        .where(
            ScrapeJob.parent_gdp_job_id == job_id,
            ScrapeJob.status.in_((ScrapeStatus.PENDING, ScrapeStatus.RUNNING)),
        )
    ).all()
    for child in children:
        scrape_crud.mark_cancelled(db, child)
        try:
            rc.set(f"scrape:job:{child.id}:cancel", "1", ex=86400)
        except Exception:
            pass
        if child.celery_task_id:
            try:
                celery_app.control.revoke(child.celery_task_id, terminate=False)
            except Exception:
                pass

    db.refresh(obj)
    return gdp_report_to_out(obj, pk_name)
