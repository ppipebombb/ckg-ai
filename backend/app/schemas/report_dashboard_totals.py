import uuid

from pydantic import BaseModel


class PuskesmasTotalOut(BaseModel):
    puskesmas_id: uuid.UUID
    name: str
    # Qualified-NIK count from the warm dashboard cache. None while this
    # puskesmas's cache is cold (a recompute was enqueued; poll back).
    total: int | None
    # Hipertensi only: the interpretasi-band split of ``total`` (Hipertensi vs
    # Pre-Hipertensi; they sum to ``total``). None for GD Puasa and while cold.
    total_hipertensi: int | None = None
    total_pre_hipertensi: int | None = None


class DashboardTotalsOut(BaseModel):
    """Per-puskesmas qualified-NIK totals for one report (gdp|hipertensi), read
    from the warm dashboard caches in a single Redis round-trip — the dashboard's
    'total pasien per puskesmas' card. Replaces N per-puskesmas terkendali calls."""

    items: list[PuskesmasTotalOut]
    grand_total: int  # sum of the cached (non-None) totals
    computing: bool  # True if any puskesmas was cold → a warm was enqueued
