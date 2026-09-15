import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_id, get_db
from app.models.llm_log import LlmLog
from app.models.merge_job import MergeJob, MergeStatus
from app.models.scrape_job import ScrapeJob, ScrapeStatus
from app.schemas.stats import (
    CapacityStats,
    JobCapacityStats,
    PuskesmasScrape24h,
    Scrape24hSummary,
)

router = APIRouter(tags=["stats"])


def _scrape_stats(db: Session, cutoff: datetime) -> JobCapacityStats:
    # Subquery: per-job LLM cost from llm_logs
    log_cost_sub = (
        select(
            LlmLog.scrape_job_id,
            func.sum(LlmLog.total_cost).label("job_cost"),
        )
        .where(LlmLog.scrape_job_id.is_not(None))
        .group_by(LlmLog.scrape_job_id)
        .subquery()
    )

    row = db.execute(
        select(
            func.count().label("sample_size"),
            func.coalesce(func.sum(ScrapeJob.scraped_count), 0).label("total_patients"),
            func.coalesce(func.sum(ScrapeJob.duration_seconds), 0).label("total_duration"),
            func.avg(ScrapeJob.cpu_avg_pct).label("cpu_avg_pct"),
            func.max(ScrapeJob.cpu_peak_pct).label("cpu_peak_pct"),
            func.avg(ScrapeJob.mem_avg_mb).label("mem_avg_mb"),
            func.max(ScrapeJob.mem_peak_mb).label("mem_peak_mb"),
            func.sum(log_cost_sub.c.job_cost).label("total_llm_cost"),
        )
        .outerjoin(log_cost_sub, log_cost_sub.c.scrape_job_id == ScrapeJob.id)
        .where(
            ScrapeJob.status == ScrapeStatus.SUCCESS,
            ScrapeJob.finished_at >= cutoff,
            # Excludes pre-resource-sampler jobs (sample_size reflects only
            # post-deploy runs). Soft-delete filter is auto-injected.
            ScrapeJob.cpu_avg_pct.is_not(None),
        )
    ).one()

    total_patients = int(row.total_patients or 0)
    total_duration = float(row.total_duration or 0)
    return JobCapacityStats(
        sample_size=row.sample_size or 0,
        total_patients=total_patients,
        total_duration_sec=round(total_duration, 2),
        avg_duration_per_patient_sec=(
            round(total_duration / total_patients, 3) if total_patients > 0 else None
        ),
        cpu_avg_pct=round(row.cpu_avg_pct, 2) if row.cpu_avg_pct is not None else None,
        cpu_peak_pct=round(row.cpu_peak_pct, 2) if row.cpu_peak_pct is not None else None,
        mem_avg_mb=round(row.mem_avg_mb, 1) if row.mem_avg_mb is not None else None,
        mem_peak_mb=round(row.mem_peak_mb, 1) if row.mem_peak_mb is not None else None,
        total_llm_cost_usd=round(float(row.total_llm_cost), 6) if row.total_llm_cost is not None else None,
        avg_llm_cost_per_patient_usd=(
            round(float(row.total_llm_cost) / total_patients, 6)
            if row.total_llm_cost is not None and total_patients > 0
            else None
        ),
    )


def _merge_stats(db: Session, cutoff: datetime) -> JobCapacityStats:
    log_cost_sub = (
        select(
            LlmLog.merge_job_id,
            func.sum(LlmLog.total_cost).label("job_cost"),
        )
        .where(LlmLog.merge_job_id.is_not(None))
        .group_by(LlmLog.merge_job_id)
        .subquery()
    )

    row = db.execute(
        select(
            func.count().label("sample_size"),
            func.coalesce(func.sum(MergeJob.processed_count), 0).label("total_patients"),
            func.coalesce(func.sum(MergeJob.duration_seconds), 0).label("total_duration"),
            func.avg(MergeJob.cpu_avg_pct).label("cpu_avg_pct"),
            func.max(MergeJob.cpu_peak_pct).label("cpu_peak_pct"),
            func.avg(MergeJob.mem_avg_mb).label("mem_avg_mb"),
            func.max(MergeJob.mem_peak_mb).label("mem_peak_mb"),
            func.sum(log_cost_sub.c.job_cost).label("total_llm_cost"),
        )
        .outerjoin(log_cost_sub, log_cost_sub.c.merge_job_id == MergeJob.id)
        .where(
            MergeJob.status == MergeStatus.SUCCESS,
            MergeJob.finished_at >= cutoff,
            # Excludes pre-resource-sampler jobs (sample_size reflects only
            # post-deploy runs). Soft-delete filter is auto-injected.
            MergeJob.cpu_avg_pct.is_not(None),
        )
    ).one()

    total_patients = int(row.total_patients or 0)
    total_duration = float(row.total_duration or 0)
    return JobCapacityStats(
        sample_size=row.sample_size or 0,
        total_patients=total_patients,
        total_duration_sec=round(total_duration, 2),
        avg_duration_per_patient_sec=(
            round(total_duration / total_patients, 3) if total_patients > 0 else None
        ),
        cpu_avg_pct=round(row.cpu_avg_pct, 2) if row.cpu_avg_pct is not None else None,
        cpu_peak_pct=round(row.cpu_peak_pct, 2) if row.cpu_peak_pct is not None else None,
        mem_avg_mb=round(row.mem_avg_mb, 1) if row.mem_avg_mb is not None else None,
        mem_peak_mb=round(row.mem_peak_mb, 1) if row.mem_peak_mb is not None else None,
        total_llm_cost_usd=round(float(row.total_llm_cost), 6) if row.total_llm_cost is not None else None,
        avg_llm_cost_per_patient_usd=(
            round(float(row.total_llm_cost) / total_patients, 6)
            if row.total_llm_cost is not None and total_patients > 0
            else None
        ),
    )


@router.get("/admin/stats/capacity", response_model=CapacityStats)
def get_capacity_stats(
    window_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> CapacityStats:
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    return CapacityStats(
        window_days=window_days,
        scrape=_scrape_stats(db, cutoff),
        merge=_merge_stats(db, cutoff),
    )


@router.get("/admin/stats/scrape-24h", response_model=Scrape24hSummary)
def get_scrape_24h(
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> Scrape24hSummary:
    """Patients scraped per puskesmas in the last 24h.

    Sums ``scraped_count`` over SUCCESS scrape jobs finished within the window,
    grouped by puskesmas (one row per puskesmas). A patient scraped by both ASIK
    and EPUS is counted in each — this reflects scrape activity, not distinct
    patients. Soft-delete filter on ScrapeJob is auto-injected.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    rows = db.execute(
        select(
            ScrapeJob.puskesmas_id,
            func.coalesce(func.sum(ScrapeJob.scraped_count), 0).label("scraped"),
        )
        .where(
            ScrapeJob.status == ScrapeStatus.SUCCESS,
            ScrapeJob.finished_at >= cutoff,
        )
        .group_by(ScrapeJob.puskesmas_id)
    ).all()
    return Scrape24hSummary(
        cutoff=cutoff,
        items=[
            PuskesmasScrape24h(puskesmas_id=r.puskesmas_id, scraped_count=int(r.scraped))
            for r in rows
        ],
    )
