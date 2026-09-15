"""Unit tests for the cross-year Diabetes Melitus dashboard-charts scan.

Focus on the two properties the charts add on top of the DM registry:
  - Bar-1 "DM murni" (glukosa reaches the diagnosis threshold, riwayat gate OFF)
    is a STRICTER population than registry membership — a riwayat-gated patient
    whose glucose is actually normal is a registry member but must NOT count here;
  - the "Diobati" bar is nested under the category split (per-category
    diobati/tidak), not a flat total.

Real Fernet encryption over synthetic blobs + a fake Session (same shape as
test_dm_registry), so it runs without Postgres, with a fixed ``as_of``.
"""

import uuid
from datetime import date
from types import SimpleNamespace

from app.core.security import encrypt_json
from app.models.patient import MatchStatus
from app.services.dm_charts_scan import scan_dm_charts

_ASOF = date(2026, 7, 15)
M, E = MatchStatus.MATCHED, MatchStatus.EPUS_ONLY

# EPUS only fills GDS-1 (never GDS-2) and does not by itself cross the DM line
# via a sewaktu reading, so GDP is the field that makes a patient "DM murni"
# through ePuskesmas: GDP >=126 -> Diabetes Melitus, 100-125 -> Prediabetes.
_RIWAYAT_Q = "Apakah Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?"


def _epus(*, nik, gdp=None, obat=None):
    pem = {}
    if gdp is not None:
        pem["Pemeriksaan Gula Darah Puasa"] = str(gdp)
    tabs = {
        "Resep": (
            {"tables": {"Resep": [{"Nama Obat": o} for o in obat]}}
            if obat
            else {"fields": {}}
        )
    }
    if pem:
        tabs["PTM"] = {"fields": {"Pemeriksaan": pem}}
    return {
        "data_pasien": {"NIK": nik, "Nama Pasien": "PX", "Jenis Kelamin": "P"},
        "penyakit_khusus": [],
        "tabs": tabs,
    }


def _asik(riwayat=None):
    """Raw ASIK blob carrying only the riwayat self-report answer on a gula-darah
    layanan (charts don't need ASIK glucose/obat — EPUS supplies those)."""
    fd = {}
    if riwayat is not None:
        fd[_RIWAYAT_Q] = riwayat
    return {
        "pelayanan_nakes": [
            {"layanan": "Pemeriksaan Gula Darah Dewasa Lansia", "form_data": fd}
        ],
        "pemeriksaan_mandiri": [],
    }


def _row(nik, fd, status, epus, *, asik=None, group=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        nik=nik,
        nama="PX",
        filter_date=fd,
        match_status=status,
        match_group_id=group,
        scraped_epus_data=encrypt_json(epus),
        scraped_asik_data=encrypt_json(asik) if asik is not None else None,
    )


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeDB:
    def __init__(self, rows):
        self._main = sorted(rows, key=lambda r: (r.nik, r.filter_date))
        self._asik = [
            SimpleNamespace(id=r.id, scraped_asik_data=r.scraped_asik_data)
            for r in rows
        ]
        self.calls = 0

    def execute(self, _stmt):
        self.calls += 1
        return _FakeResult(self._main if self.calls == 1 else self._asik)


def _scan(rows):
    return scan_dm_charts(_FakeDB(rows), uuid.uuid4(), as_of=_ASOF)


def test_kohort_2tahun_dm_murni_excludes_riwayat_gated_and_nests_diobati():
    rows = [
        # P1: DM murni 2025 (GDP 180) -> diperiksa 2026, terkendali (GDP 110), diobati.
        _row("P1", date(2025, 3, 1), M, _epus(nik="P1", gdp=180), asik=_asik()),
        _row("P1", date(2026, 4, 1), M, _epus(nik="P1", gdp=110, obat=["Metformin"]), asik=_asik()),
        # P2: DM murni 2025 (GDP 180) -> tidak diperiksa lagi di 2026.
        _row("P2", date(2025, 5, 1), M, _epus(nik="P2", gdp=180), asik=_asik()),
        # P3: glukosa normal 2025 (GDP 90) tapi riwayat Ya -> anggota registri,
        # TAPI bukan "DM murni" -> harus dikeluarkan dari dm_2025.
        _row("P3", date(2025, 6, 1), M, _epus(nik="P3", gdp=90), asik=_asik(riwayat="Ya")),
        # P4: DM murni 2025 (GDP 180) -> diperiksa 2026, masih tinggi (GDP 200), tidak diobati.
        _row("P4", date(2025, 2, 1), M, _epus(nik="P4", gdp=180), asik=_asik()),
        _row("P4", date(2026, 3, 1), M, _epus(nik="P4", gdp=200), asik=_asik()),
    ]
    k = _scan(rows)["kohort_2tahun"]
    assert k["dm_2025"] == 3  # P1, P2, P4 — P3 excluded (riwayat-gated, normal)
    assert k["diperiksa_2026"] == 2  # P1, P4
    assert k["dm_2026_tinggi"] == 1  # P4
    assert k["dm_2026_terkendali"] == 1  # P1
    # tinggi + terkendali partition diperiksa_2026.
    assert k["dm_2026_tinggi"] + k["dm_2026_terkendali"] == k["diperiksa_2026"]
    assert k["tinggi_diobati"] == 0
    assert k["tinggi_tidak_diobati"] == 1  # P4
    assert k["terkendali_diobati"] == 1  # P1
    assert k["terkendali_tidak_diobati"] == 0


def test_dm_2026_pasien_baru_vs_sudah_and_nested_diobati():
    rows = [
        # Q1: DM murni 2026 (GDP 180), tanpa riwayat -> Pasien Baru, diobati.
        _row("Q1", date(2026, 2, 1), M, _epus(nik="Q1", gdp=180, obat=["Metformin"]), asik=_asik()),
        # Q2: DM murni 2026 (GDP 180) DAN riwayat Ya -> Sudah DM, tidak diobati.
        _row("Q2", date(2026, 3, 1), M, _epus(nik="Q2", gdp=180), asik=_asik(riwayat="Ya")),
        # Q3: Prediabetes murni (GDP 110), tanpa riwayat -> BUKAN DM murni, dikeluarkan.
        _row("Q3", date(2026, 4, 1), M, _epus(nik="Q3", gdp=110), asik=_asik()),
    ]
    h = _scan(rows)["dm_2026"]
    assert h["dm_2026"] == 2  # Q1, Q2 — Q3 excluded (Prediabetes, not murni)
    assert h["pasien_baru"] == 1  # Q1
    assert h["sudah_dm"] == 1  # Q2
    assert h["baru_diobati"] == 1  # Q1
    assert h["baru_tidak_diobati"] == 0
    assert h["sudah_diobati"] == 0
    assert h["sudah_tidak_diobati"] == 1  # Q2
