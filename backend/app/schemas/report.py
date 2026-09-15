import uuid
from datetime import datetime

from pydantic import BaseModel


class DelayBucket(BaseModel):
    """One delay-day bucket for the delayed-input distribution."""

    days: int  # gap in days between the EPUS and ASIK entry of a delayed CKG visit (1..MATCH_WINDOW_DAYS)
    count: int  # delayed CKG visits with exactly this gap
    pct: float  # count / delayed_ckg * 100 (0.0 when delayed_ckg == 0)


class VisitSummaryOut(BaseModel):
    """Per-visit counts. Matched cross-date twins (same real visit scraped on
    different filter_dates, linked by match_group_id) are collapsed into one
    visit so `matched` is not doubled by the backfill."""

    data_on_asik: int  # visits with scraped_asik_data (asik_only + matched)
    data_on_epus: int  # visits with scraped_epus_data (epus_only + matched)
    matched: int  # NIK present in both ASIK and EPUS
    tandai_ckg: int  # visits with epus_tandai_ckg = TRUE (sudah CKG)
    delayed_ckg: int  # CKG visits whose EPUS/ASIK entries landed 1..MATCH_WINDOW_DAYS apart
    delayed_ckg_pct: float  # delayed_ckg / tandai_ckg * 100 (0.0 when tandai_ckg == 0)
    delay_distribution: list[DelayBucket]  # per-day breakdown of delayed_ckg, days 1..MATCH_WINDOW_DAYS


class GdpSourceQualityOut(BaseModel):
    """GD Puasa data-source quality among CKG visits (epus_tandai_ckg true),
    counted per distinct person (puskesmas_id, nik). The GD Puasa report reads
    Laboratorium GDP first and falls back to the less-reliable PTM Pemeriksaan
    GDP. This surfaces how often that fallback happens.

    Heavy (decrypts EPUS blobs) → Redis-cached, warmed nightly by
    cron.warm_reports."""

    puskesmas_id: uuid.UUID | None
    people_with_gdp: int  # distinct CKG people with any GDP value (lab or ptm)
    lab_backed: int  # people who have a Laboratorium GDP (trusted source)
    ptm_fallback: int  # people with only a PTM GDP, no lab (forced onto unreliable source)
    ptm_fallback_pct: float  # ptm_fallback / people_with_gdp * 100 (0.0 when none)
    computed_at: datetime | None  # None while a background recompute is running
    cache_hit: bool
    computing: bool = False  # True → recompute enqueued, poll until data arrives
