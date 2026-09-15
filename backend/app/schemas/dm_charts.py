from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.report_progress import WarmProgress


class DmKohort2Tahun(BaseModel):
    """Chart 1 — DM 2 tahun berturut-turut (absolute counts). Bar-1 population is
    "DM murni" (glukosa mencapai ambang diagnosis), NOT registry membership —
    see ``dm_charts_scan._dm_murni``."""

    dm_2025: int = 0
    diperiksa_2026: int = 0
    dm_2026_tinggi: int = 0  # glukosa 2026 masih >= ambang diagnosis DM
    dm_2026_terkendali: int = 0  # glukosa 2026 di bawah ambang (dari diperiksa_2026)
    # Diobati/tidak, masing-masing dipecah dari dm_2026_tinggi / dm_2026_terkendali
    # (bukan total dari diperiksa_2026) — pernah diobati kapan saja 2025-2026.
    tinggi_diobati: int = 0
    tinggi_tidak_diobati: int = 0
    terkendali_diobati: int = 0
    terkendali_tidak_diobati: int = 0


class DmCharts2026(BaseModel):
    """Chart 2 — DM CKG 2026 (absolute counts). Bar-1 population is "DM murni"
    (glukosa mencapai ambang diagnosis), NOT registry membership."""

    dm_2026: int = 0
    pasien_baru: int = 0  # tanpa riwayat DM
    sudah_dm: int = 0  # ada riwayat DM
    # Diobati/tidak, masing-masing dipecah dari pasien_baru / sudah_dm
    # (bukan total dari dm_2026) — pernah diobati kapan saja 2025-2026.
    baru_diobati: int = 0
    baru_tidak_diobati: int = 0
    sudah_diobati: int = 0
    sudah_tidak_diobati: int = 0


class DmChartsOut(BaseModel):
    """The 2-chart DM dashboard payload for one puskesmas (rolling cross-year
    window). Carries ABSOLUTE counts; percentages are computed on the frontend.
    Same cache-metadata triad as the registry dashboards, so a cold cache returns
    immediately and the caller polls back."""

    kohort_2tahun: DmKohort2Tahun = Field(default_factory=DmKohort2Tahun)
    dm_2026: DmCharts2026 = Field(default_factory=DmCharts2026)
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
    progress: WarmProgress | None = None  # approx warm progress while computing
