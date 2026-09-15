"""Schemas for the newborn (Bayi Kuning) registry — Ikterus + Ikterus Berat.

EPUS-only, ikterus-band split. One scan payload per (puskesmas, year) feeds both
sheets; the route filters on the ``qualifies_*`` flags per sheet. See
``app.services.bayi_registry_scan`` for how the band + provenance are derived.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.report_progress import WarmProgress


# ── per-value provenance (mirrors the HT/DM EPUS/ASIK pill) ──────────────────
class BayiRegistrySources(BaseModel):
    """Where each value came from: "EPUS" (EPUS's own klasifikasi field) |
    "Hitung" (derived by the backend from the MTBM questionnaire) | None."""

    klasifikasi: str | None = None
    diagnosis: str | None = None


class BayiIkterusBaseline(BaseModel):
    """Hasil Pemeriksaan Bayi Kuning at the baseline (birth-screening) visit."""

    klasifikasi: str = ""  # "Ikterus" | "Ikterus berat" | "Tidak ada ikterus" | ""
    diagnosis: str = ""
    rujuk_eksternal: str = ""
    sources: BayiRegistrySources = Field(default_factory=BayiRegistrySources)


class BayiIkterusPemantauan(BayiIkterusBaseline):
    """A follow-up (Pemantauan) ikterus visit — same shape plus its own date."""

    tanggal: date | None = None


class BayiIkterus(BaseModel):
    baseline: BayiIkterusBaseline
    pemantauan: list[BayiIkterusPemantauan] = Field(default_factory=list)


# ── registry row (one bayi / NIK) ────────────────────────────────────────────
class BayiRegistryRow(BaseModel):
    """One newborn (NIK) in the Bayi Kuning registry. ``pjb`` and the raw
    ``qualifies_*`` flags ride along from the scan but are ignored here (extra
    keys are dropped) — the PJBK sheet is a separate future route."""

    puskesmas_name: str
    tahun_pelaporan: int

    nik: str
    nama: str
    jenis_kelamin: str = ""
    tanggal_lahir: date | None = None
    no_tlp: str = ""
    alamat: str = ""
    tanggal_berkunjung: date | None = None

    ikterus: BayiIkterus | None = None


class BayiRegistryDashboardOut(BaseModel):
    """Paginated registry response with cache metadata (same contract as the
    HT/DM/Obesitas registries). ``total`` is the row count of the SELECTED sheet;
    the three band counts are over the whole registry for the header context."""

    items: list[BayiRegistryRow]
    total: int
    ikterus: int = 0  # bayi with Ikterus or Ikterus berat (the Ikterus sheet)
    ikterus_berat: int = 0  # bayi with Ikterus berat (the Ikterus Berat sheet)
    pjbk: int = 0  # bayi qualifying for PJBK (future sheet)
    page: int
    size: int
    pages: int
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
    progress: WarmProgress | None = None


class BayiRegistrySummaryOut(BaseModel):
    """Per-puskesmas aggregate counts over the Bayi Kuning registry."""

    ikterus: int = 0
    ikterus_berat: int = 0
    pjbk: int = 0
    cache_hit: bool
    computed_at: datetime | None
    computing: bool = False
