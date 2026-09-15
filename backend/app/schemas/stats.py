import uuid
from datetime import datetime

from pydantic import BaseModel


class JobCapacityStats(BaseModel):
    sample_size: int
    total_patients: int
    total_duration_sec: float
    avg_duration_per_patient_sec: float | None
    cpu_avg_pct: float | None
    cpu_peak_pct: float | None
    mem_avg_mb: float | None
    mem_peak_mb: float | None
    total_llm_cost_usd: float | None
    avg_llm_cost_per_patient_usd: float | None


class CapacityStats(BaseModel):
    window_days: int
    scrape: JobCapacityStats
    merge: JobCapacityStats


class PuskesmasScrape24h(BaseModel):
    puskesmas_id: uuid.UUID
    scraped_count: int


class Scrape24hSummary(BaseModel):
    cutoff: datetime
    items: list[PuskesmasScrape24h]
