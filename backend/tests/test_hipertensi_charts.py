"""Unit tests for the cross-year Hipertensi dashboard-charts scan.

Focus on the properties that make this scan DIFFERENT from the single-year
registry scan it reuses helpers from:
  - a 2025-registered NIK's plain (EPUS-only, non-CKG) 2026 follow-up readings
    are captured (the cross-year fix),
  - scrape-twins across the 2025/2026 boundary don't double-register,
  - Chart-6 uses STRICT reg-2025 ∩ reg-2026,
  - the "any controlled reading in the month → controlled" rule,
  - the per-month partition invariant
    ``tercapai + tidak_tercapai + tidak_berkunjung == treated_cumulative``.

Uses real Fernet encryption over synthetic blobs + a fake Session (same shape as
test_hipertensi_registry) so it runs without Postgres, and a fixed ``as_of`` so
the rolling axis is deterministic.
"""

import uuid
from datetime import date
from types import SimpleNamespace

from app.core.security import encrypt_json
from app.models.patient import MatchStatus
from app.services.hipertensi_charts_scan import (
    scan_hipertensi_bundle,
    scan_hipertensi_charts,
)

_ASOF = date(2026, 7, 15)  # current month = 2026-07
M, E = MatchStatus.MATCHED, MatchStatus.EPUS_ONLY


# ── blob builders (compact) ────────────────────────────────────────────────
def _epus(sys, dia, *, nik, icd=None, obat=None, nama="PX", no_tlp=None, alamat=None):
    resep = (
        {"tables": {"Resep": [{"Nama Obat": o} for o in obat]}}
        if obat
        else {"fields": {}}
    )
    return {
        "data_pasien": {
            "NIK": nik,
            "Nama Pasien": nama,
            "Jenis Kelamin": "P",
            "Tempat/Tgl Lahir": "X/ 01-01-1980",
            "No Telp / HP": no_tlp,
            "Alamat": alamat,
        },
        "penyakit_khusus": ([{"ICDX": icd, "Penyakit": ""}] if icd else []),
        "tabs": {
            "Anamnesa": {
                "fields": {
                    "Periksa Fisik": {
                        "Sistole": str(sys) if sys is not None else None,
                        "Diastole": str(dia) if dia is not None else None,
                    }
                }
            },
            "Resep": resep,
        },
    }


def _asik_min():
    return {"pelayanan_nakes": [], "pemeriksaan_mandiri": []}


_RIWAYAT_Q = "Apakah Anda pernah dinyatakan tekanan darah tinggi?"


def _asik(riwayat=None):
    """Raw ASIK blob carrying only the riwayat self-report answer (chart 7/8
    tests don't need ASIK TD/obat — EPUS already supplies those)."""
    fd = {}
    if riwayat is not None:
        fd[_RIWAYAT_Q] = riwayat
    return {
        "pelayanan_nakes": [{"layanan": "Tekanan Darah Dewasa Lansia", "form_data": fd}],
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
    """Main blob rows on the first execute(), baseline ASIK rows on the second
    (the scan issues exactly those two queries)."""

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
    return scan_hipertensi_charts(_FakeDB(rows), uuid.uuid4(), as_of=_ASOF)


def _by_ym(payload):
    return {r["ym"]: r for r in payload["monthly"]}


def _assert_gap_matches_chart(payload):
    """The Gap Tatalaksana list IS the gap between the two lines of Chart 2 at
    its last month. If this ever drifts, the page contradicts the graph that
    sends users to it."""
    last = payload["monthly"][-1]
    assert len(payload["gap_patients"]) == (
        last["registered_cumulative"] - last["treated_cumulative"]
    ), last


def _assert_partition_invariant(payload):
    for r in payload["monthly"]:
        assert (
            r["tercapai"] + r["tidak_tercapai"] + r["tidak_berkunjung"]
            == r["treated_cumulative"]
        ), r


# ── tests ──────────────────────────────────────────────────────────────────
def test_cross_year_epus_only_followup_is_captured():
    """A NIK registered via CKG in 2025 whose 2026 follow-up is a PLAIN EPUS
    visit (not a new CKG match) still gets its 2026 reading counted."""
    rows = [
        _row("A", date(2025, 2, 10), M, _epus(160, 100, nik="A", obat=["AMLODIPINE"]),
             asik=_asik_min()),
        _row("A", date(2026, 3, 5), E, _epus(130, 85, nik="A")),  # EPUS-only, controlled
    ]
    payload = _scan(rows)
    m = _by_ym(payload)
    # 2026-03 controlled reading is visible despite being EPUS-only / cross-year.
    assert m["2026-03"]["tercapai"] == 1
    assert m["2026-03"]["treated_cumulative"] == 1
    # Baseline month reading (160/100) is uncontrolled; a later gap month is missed.
    assert m["2025-02"]["tidak_tercapai"] == 1
    assert m["2025-03"]["tidak_berkunjung"] == 1
    _assert_partition_invariant(payload)
    # Not controlled in the current month (no 2026-07 visit).
    assert payload["cascade"] == {"registered": 1, "treated": 1, "controlled": 0}


def test_any_controlled_reading_in_month_wins():
    rows = [
        _row("K", date(2025, 2, 1), M, _epus(160, 100, nik="K", obat=["AMLODIPINE"]),
             asik=_asik_min()),
        _row("K", date(2025, 5, 3), E, _epus(150, 95, nik="K")),   # uncontrolled
        _row("K", date(2025, 5, 20), E, _epus(130, 85, nik="K")),  # controlled
    ]
    m = _by_ym(_scan(rows))
    assert m["2025-05"]["tercapai"] == 1
    assert m["2025-05"]["tidak_tercapai"] == 0


def test_proporsi_strict_intersection_and_baseline_controlled():
    rows = [
        # C: registered both years; 2026 baseline is controlled (130/85 → Pre-Hip, <140/<90).
        _row("C", date(2025, 3, 1), M, _epus(160, 100, nik="C"), asik=_asik_min()),
        _row("C", date(2026, 4, 1), M, _epus(130, 85, nik="C"), asik=_asik_min()),
        # D: 2025 only.
        _row("D", date(2025, 3, 1), M, _epus(160, 100, nik="D"), asik=_asik_min()),
    ]
    p = _scan(rows)["proporsi"]
    assert p["registry_2025"] == 2  # C, D
    assert p["both_years"] == 1  # C only
    assert p["controlled_baseline_2026"] == 1  # C's 2026 baseline is controlled


def test_boundary_twin_not_double_registered():
    """A CKG visit scraped as a Dec-2025/Jan-2026 twin (same match_group_id) must
    register once (in 2025) — NOT also as a fresh 2026 registration."""
    gid = uuid.uuid4()
    rows = [
        _row("T", date(2025, 12, 28), M, _epus(160, 100, nik="T"), asik=_asik_min(), group=gid),
        _row("T", date(2026, 1, 3), M, _epus(160, 100, nik="T"), asik=_asik_min(), group=gid),
    ]
    payload = _scan(rows)
    assert payload["cascade"]["registered"] == 1
    assert payload["proporsi"]["registry_2025"] == 1
    assert payload["proporsi"]["both_years"] == 0  # not a 2026 registration


def test_normal_no_diagnosis_excluded():
    rows = [
        _row("N", date(2025, 5, 1), M, _epus(110, 70, nik="N"), asik=_asik_min()),
    ]
    payload = _scan(rows)
    assert payload["cascade"]["registered"] == 0
    assert payload["proporsi"]["registry_2025"] == 0


def test_bundle_matches_standalone_charts_and_builds_both_registries():
    """The merged single-pass bundle produces a charts payload identical to the
    standalone charts scan, plus a registry payload per year."""
    rows = [
        # A: registered 2025 (CKG hipertensi) + a plain 2026 EPUS follow-up.
        _row("A", date(2025, 2, 10), M, _epus(160, 100, nik="A", obat=["AMLODIPINE"]),
             asik=_asik_min()),
        _row("A", date(2026, 3, 5), E, _epus(130, 85, nik="A")),
        # C: registered in BOTH years (a fresh CKG 2026 match).
        _row("C", date(2025, 3, 1), M, _epus(160, 100, nik="C"), asik=_asik_min()),
        _row("C", date(2026, 4, 1), M, _epus(130, 85, nik="C"), asik=_asik_min()),
    ]
    bundle = scan_hipertensi_bundle(_FakeDB(rows), uuid.uuid4(), [2025, 2026], as_of=_ASOF)
    standalone = scan_hipertensi_charts(_FakeDB(rows), uuid.uuid4(), as_of=_ASOF)

    # Charts payload byte-identical except the wall-clock computed_at.
    for k in ("current_month", "monthly", "cascade", "proporsi", "gap_patients"):
        assert bundle["charts"][k] == standalone[k]

    reg25 = {p["nik"] for p in bundle["registry"][2025]["patients"]}
    reg26 = {p["nik"] for p in bundle["registry"][2026]["patients"]}
    assert reg25 == {"A", "C"}  # both have a 2025 CKG baseline
    assert reg26 == {"C"}  # only C has a fresh 2026 CKG baseline
    assert bundle["charts"]["proporsi"]["both_years"] == 1  # C only


def test_gap_list_equals_the_chart_gap():
    """Untreated registry members are listed; treated ones are not, whichever
    month they were treated in."""
    rows = [
        # G1/G2: hipertensi, never any antihypertensive → in the gap.
        _row("G1", date(2025, 3, 1), M, _epus(160, 100, nik="G1"), asik=_asik_min()),
        _row("G2", date(2025, 6, 1), M, _epus(160, 100, nik="G2"), asik=_asik_min()),
        # T1: treated at baseline → never in the gap.
        _row("T1", date(2025, 4, 1), M, _epus(160, 100, nik="T1", obat=["AMLODIPINE"]),
             asik=_asik_min()),
        # T2: registered untreated, prescribed only later (2026) → still out.
        _row("T2", date(2025, 5, 1), M, _epus(160, 100, nik="T2"), asik=_asik_min()),
        _row("T2", date(2026, 2, 1), E, _epus(150, 95, nik="T2", obat=["CAPTOPRIL"])),
        # N: normal, no riwayat → not in the registry at all.
        _row("N", date(2025, 5, 1), M, _epus(110, 70, nik="N"), asik=_asik_min()),
    ]
    payload = _scan(rows)
    assert {p["nik"] for p in payload["gap_patients"]} == {"G1", "G2"}
    _assert_gap_matches_chart(payload)
    # Oldest registration month first, so the longest-waiting patient is on top.
    assert [p["registration_ym"] for p in payload["gap_patients"]] == [
        "2025-03",
        "2025-06",
    ]


def test_gap_row_carries_contact_details_and_baseline():
    rows = [
        _row("G", date(2025, 3, 4), M,
             _epus(160, 100, nik="G", nama="BUDI", no_tlp="081234", alamat="JL  MAWAR 1"),
             asik=_asik_min()),
    ]
    (row,) = _scan(rows)["gap_patients"]
    assert row["nama"] == "BUDI"
    assert row["no_tlp"] == "081234"
    assert row["alamat"] == "JL MAWAR 1"  # whitespace collapsed by _extract_identitas
    assert row["tanggal_lahir"] == "1980-01-01"
    assert row["tanggal_berkunjung"] == "2025-03-04"
    assert (row["rerata_sys"], row["rerata_dia"]) == (160, 100)
    assert row["interpretasi"] == "Hipertensi"


def test_gap_row_missing_contact_details_is_kept():
    """A patient with no phone/address in either source still has to appear —
    they are exactly the follow-up problem the list exists to surface."""
    rows = [
        _row("G", date(2025, 3, 1), M, _epus(160, 100, nik="G"), asik=_asik_min()),
    ]
    (row,) = _scan(rows)["gap_patients"]
    assert row["no_tlp"] == ""
    assert row["alamat"] == ""


def test_gap_identitas_prefers_asik():
    asik = {
        "pelayanan_nakes": [],
        "pemeriksaan_mandiri": [],
        "detail_data": {
            "data_individu": {"Nama": "SITI", "No. HP/WA orang tua": "0899"},
            "data_domisili": {"Alamat Domisili": "JL ASIK 7"},
        },
    }
    rows = [
        _row("G", date(2025, 3, 1), M,
             _epus(160, 100, nik="G", nama="BUDI", no_tlp="081234", alamat="JL EPUS 1"),
             asik=asik),
    ]
    (row,) = _scan(rows)["gap_patients"]
    assert (row["nama"], row["no_tlp"], row["alamat"]) == ("SITI", "0899", "JL ASIK 7")
    # ASIK left this one out → the EPUS value still fills the gap.
    assert row["jenis_kelamin"] == "Perempuan"


def test_cumulative_registered_is_monotonic():
    rows = [
        _row("P1", date(2025, 3, 1), M, _epus(160, 100, nik="P1"), asik=_asik_min()),
        _row("P2", date(2025, 6, 1), M, _epus(160, 100, nik="P2"), asik=_asik_min()),
    ]
    m = _by_ym(_scan(rows))
    reg = [m[k]["registered_cumulative"] for k in sorted(m)]
    assert reg == sorted(reg)  # non-decreasing
    assert m["2025-03"]["registered_cumulative"] == 1
    assert m["2025-06"]["registered_cumulative"] == 2


def test_kohort_2tahun_ht_murni_excludes_riwayat_gated_and_splits_diobati():
    """Chart 7's Bar 1 is "HT murni" (rerata TD >=140/90), NOT registry
    membership: a riwayat-gated patient whose TD is actually normal (P3) is a
    registry member but must NOT be counted here — this is the property that
    makes chart 7 different from chart 6's ``registry_2025``."""
    rows = [
        # P1: HT murni 2025 (160/100) -> diperiksa lagi 2026, terkendali, diobati.
        _row("P1", date(2025, 3, 1), M, _epus(160, 100, nik="P1"), asik=_asik_min()),
        _row("P1", date(2026, 4, 1), M, _epus(130, 85, nik="P1", obat=["AMLODIPINE"]), asik=_asik_min()),
        # P2: HT murni 2025 (150/70) -> tidak diperiksa lagi di 2026.
        _row("P2", date(2025, 5, 1), M, _epus(150, 70, nik="P2"), asik=_asik_min()),
        # P3: TD normal 2025 (120/80) tapi riwayat Ya (ASIK) -> anggota registri,
        # TAPI bukan "HT murni" -> harus dikeluarkan dari hipertensi_2025.
        _row("P3", date(2025, 6, 1), M, _epus(120, 80, nik="P3"), asik=_asik(riwayat="Ya")),
        # P4: HT murni 2025 (145/70) -> diperiksa lagi 2026, TIDAK terkendali (150/95), tidak diobati.
        _row("P4", date(2025, 2, 1), M, _epus(145, 70, nik="P4"), asik=_asik_min()),
        _row("P4", date(2026, 3, 1), M, _epus(150, 95, nik="P4"), asik=_asik_min()),
    ]
    k = _scan(rows)["kohort_2tahun"]
    assert k["hipertensi_2025"] == 3  # P1, P2, P4 — P3 excluded (riwayat-gated, TD normal)
    assert k["diperiksa_2026"] == 2  # P1, P4 — P2 has no 2026 baseline
    assert k["td_2026_tinggi"] == 1  # P4
    assert k["td_2026_terkendali"] == 1  # P1
    assert k["tinggi_diobati"] == 0
    assert k["tinggi_tidak_diobati"] == 1  # P4
    assert k["terkendali_diobati"] == 1  # P1
    assert k["terkendali_tidak_diobati"] == 0


def test_ht_2026_pasien_baru_vs_sudah_riwayat_and_diobati():
    """Chart 8 Bar 2 splits purely on the riwayat flag: Q2 has never been in
    the 2025 registry at all (first CKG in 2026) but self-reports a prior HT
    diagnosis, so it lands in "sudah_hipertensi" — per explicit client
    decision, not "registry_2025 membership". Q3 (Pre-Hipertensi by
    measurement, no riwayat) is excluded from Bar 1 entirely."""
    rows = [
        # Q1: HT murni 2026 (160/100), tanpa riwayat -> Pasien Baru, diobati.
        _row("Q1", date(2026, 2, 1), M, _epus(160, 100, nik="Q1", obat=["AMLODIPINE"]), asik=_asik_min()),
        # Q2: HT murni 2026 (145/95) DAN riwayat (self-report) -> Sudah Hipertensi,
        # walau TIDAK pernah tercatat di registri 2025 (CKG pertama kali 2026).
        _row("Q2", date(2026, 3, 1), M, _epus(145, 95, nik="Q2"), asik=_asik(riwayat="Ya")),
        # Q3: Pre-Hipertensi murni oleh pengukuran (132/86), tanpa riwayat -> BUKAN
        # HT murni, dikeluarkan dari Bar 1 sama sekali walau anggota registri.
        _row("Q3", date(2026, 4, 1), M, _epus(132, 86, nik="Q3"), asik=_asik_min()),
    ]
    h = _scan(rows)["hipertensi_2026"]
    assert h["hipertensi_2026"] == 2  # Q1, Q2 — Q3 excluded (Pre-Hipertensi, not murni)
    assert h["pasien_baru"] == 1  # Q1
    assert h["sudah_hipertensi"] == 1  # Q2
    assert h["baru_diobati"] == 1  # Q1
    assert h["baru_tidak_diobati"] == 0
    assert h["sudah_diobati"] == 0
    assert h["sudah_tidak_diobati"] == 1  # Q2
