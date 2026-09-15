from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.report_progress import WarmProgress


class HipertensiChartsMonthPoint(BaseModel):
    """One month on the cumulative axis. Invariant:
    ``tercapai + tidak_tercapai + tidak_berkunjung == treated_cumulative``."""

    ym: str  # "YYYY-MM"
    registered_cumulative: int  # Chart 2 line 1 (cumulative registered)
    treated_cumulative: int  # Chart 2 line 2 (cumulative treated) = area base
    tercapai: int  # Chart 3
    tidak_tercapai: int  # Chart 4
    tidak_berkunjung: int  # Chart 5


class HipertensiCascade(BaseModel):
    """Chart 1 — cascade at the current month (absolute counts)."""

    registered: int = 0
    treated: int = 0
    controlled: int = 0


class HipertensiProporsi(BaseModel):
    """Chart 6 — Proporsi 2025→2026 (absolute counts)."""

    registry_2025: int = 0
    both_years: int = 0
    controlled_baseline_2026: int = 0
    controlled_current_month: int = 0


class HipertensiKohort2Tahun(BaseModel):
    """Chart 7 — Kohort 2 tahun berturut-turut (absolute counts). Bar-1
    population is "HT murni" (rerata TD ≥140/90), NOT registry membership —
    see ``hipertensi_charts_scan._ht_murni``."""

    hipertensi_2025: int = 0
    diperiksa_2026: int = 0
    td_2026_tinggi: int = 0  # TD 2026 >=140/90 (dari diperiksa_2026)
    td_2026_terkendali: int = 0  # TD 2026 <140/90 (dari diperiksa_2026)
    # Diobati/tidak, masing-masing dipecah dari td_2026_tinggi / td_2026_terkendali
    # (bukan total dari diperiksa_2026) — pernah diobati kapan saja 2025-2026.
    tinggi_diobati: int = 0
    tinggi_tidak_diobati: int = 0
    terkendali_diobati: int = 0
    terkendali_tidak_diobati: int = 0


class HipertensiHT2026(BaseModel):
    """Chart 8 — Hipertensi 2026 (absolute counts). Bar-1 population is "HT
    murni" (rerata TD ≥140/90), NOT registry membership."""

    hipertensi_2026: int = 0
    pasien_baru: int = 0  # tanpa riwayat HT
    sudah_hipertensi: int = 0  # ada riwayat HT
    # Diobati/tidak, masing-masing dipecah dari pasien_baru / sudah_hipertensi
    # (bukan total dari hipertensi_2026) — pernah diobati kapan saja 2025-2026.
    baru_diobati: int = 0
    baru_tidak_diobati: int = 0
    sudah_diobati: int = 0
    sudah_tidak_diobati: int = 0


class HipertensiChartsOut(BaseModel):
    """The 8-chart dashboard payload for one puskesmas (rolling cross-year
    window). Carries ABSOLUTE counts + cohort bases; percentages are computed on
    the frontend. Same cache-metadata triad as the registry dashboards, so a cold
    cache returns immediately and the caller polls back."""

    current_month: str | None = None  # "YYYY-MM"
    monthly: list[HipertensiChartsMonthPoint] = Field(default_factory=list)
    cascade: HipertensiCascade = Field(default_factory=HipertensiCascade)
    proporsi: HipertensiProporsi = Field(default_factory=HipertensiProporsi)
    kohort_2tahun: HipertensiKohort2Tahun = Field(default_factory=HipertensiKohort2Tahun)
    hipertensi_2026: HipertensiHT2026 = Field(default_factory=HipertensiHT2026)
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
    progress: WarmProgress | None = None  # approx warm progress while computing
