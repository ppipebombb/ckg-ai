from datetime import datetime

from pydantic import BaseModel


class TerkendaliSummaryOut(BaseModel):
    """Aggregate of the per-NIK ``terkendali_bulan_berjalan`` status over a whole
    (puskesmas, year) report. Shared by the GD Puasa and Hipertensi summaries.

    The five buckets partition ``total``:
        terkendali + tidak_terkendali + belum_3_bulan
        + tidak_ada_kunjungan + tanpa_status == total
    """

    total: int
    terkendali: int
    tidak_terkendali: int
    belum_3_bulan: int
    tidak_ada_kunjungan: int
    tanpa_status: int  # "" — no tanggal_diagnosis yet
    cache_hit: bool
    computed_at: datetime | None  # None while a background recompute is running
    computing: bool = False  # True → recompute enqueued, poll until data arrives


class QuarterStatus(BaseModel):
    """One quarter's terkendali tally. The three buckets partition ``total``;
    ``belum_atau_tidak_ada`` folds 'Belum 3 bulan' + 'Tidak ada kunjungan' +
    'tanpa diagnosis' (the spreadsheet's non-controlled, non-uncontrolled rest)."""

    terkendali: int
    tidak_terkendali: int
    belum_atau_tidak_ada: int


class TerkendaliDashboardOut(BaseModel):
    """Per-(puskesmas, year) dashboard aggregate: a per-quarter terkendali tally
    plus tatalaksana (obat/edukasi) counts. Computed from the same Redis cache as
    the dashboard table — no recompute. Shared by GD Puasa and Hipertensi."""

    total: int
    tw1: QuarterStatus
    tw2: QuarterStatus
    tw3: QuarterStatus
    tw4: QuarterStatus
    pemberian_obat: int
    pemberian_edukasi: int
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
