from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.report_progress import WarmProgress


# ── Gap Tatalaksana row (one patient / NIK) ──────────────────────────────
class HipertensiGapRow(BaseModel):
    """One registry member who has NEVER been prescribed an antihypertensive —
    the drill-down behind the gap between the two lines of the dashboard chart
    "Pasien Hipertensi Tertatalaksana".

    Identitas comes from the same baseline blobs the Kertas Kerja registry
    reads (ASIK wins per field, ePuskesmas fills the gaps), so a patient's
    nama / no telp / alamat can never disagree between the two pages. Fields the
    source left blank arrive as ``""`` / ``null`` — the caller renders the em
    dash; rows are NOT dropped for missing contact details."""

    puskesmas_name: str

    # Identitas
    nik: str
    nama: str
    jenis_kelamin: str = ""
    tanggal_lahir: date | None = None
    no_tlp: str = ""
    alamat: str = ""

    # CKG baseline of the year the patient entered the registry
    tanggal_berkunjung: date | None = None
    rerata_sys: float | None = None
    rerata_dia: float | None = None
    interpretasi: str = ""  # "Hipertensi" | "Pre-Hipertensi"

    # "YYYY-MM" — the month the patient entered the registry (how long they
    # have been waiting for treatment).
    registration_ym: str


class HipertensiGapOut(BaseModel):
    """Paginated Gap Tatalaksana response. Same cache metadata as the registry
    (cache_hit / computed_at / computing / progress) because it is served off
    the same warm as the charts payload: a cold cache returns immediately with
    ``computing=True`` and the caller polls back."""

    items: list[HipertensiGapRow] = []
    total: int = 0
    page: int = 1
    size: int = 20
    pages: int = 0
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
    progress: WarmProgress | None = None
