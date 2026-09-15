"""Tests for the newborn (PJBK + Ikterus + Ikterus Berat) registry scan.

EPUS-only, single decrypt pass (no ASIK second query), so the fake Session is a
single-``execute`` stub over real-Fernet-encrypted synthetic blobs. Coverage:

  1. **Bayi vs. parent** — the parent record (umur 30) sharing the bayi's NIK is
     excluded; only the ``umur==0`` / "BAYI " record is read.
  2. **Ikterus classification** is read from the EPUS field directly, across the
     several plausible ``saved_detail`` shapes the defensive extractor must
     tolerate (the live filled shape is verified at re-scrape — see the scan
     module docstring).
  3. **PJB pulse-ox** — Tangan Kanan (%) / Kaki (%) / interpretasi, from either
     ``saved_detail`` or the ``tables`` fallback; the PJBK syarat
     (Waspada/Terduga) decides inclusion.
  4. **Per-sheet inclusion + counts** — a bayi qualifying for no sheet is
     dropped; ``count_sheet_bands`` matches the ``qualifies_*`` flags.
  5. **Pemantauan** — a follow-up ikterus visit becomes a pemantauan row; a
     re-scrape twin (same ``match_group_id``) collapses.

A **past** report year keeps the scan deterministic regardless of run date.
"""

import uuid
from datetime import date
from types import SimpleNamespace

from app.core.security import encrypt_json
from app.services.bayi_registry_scan import (
    _IKTERUS,
    _IKTERUS_BERAT,
    _IKTERUS_TIDAK,
    _SRC_DERIVED,
    _SRC_EPUS,
    _extract_ikterus_klasifikasi,
    _extract_pjb,
    _is_bayi,
    _pjb_qualifies,
    count_sheet_bands,
    scan_bayi_registry,
)

_YEAR = 2026


# ── blob builders ──────────────────────────────────────────────────────────
def _bayi_dp(nik="3175010101010001", nama="BAYI NYONYA LINDA", jk="L"):
    return {
        "NIK": nik,
        "Nama Pasien": nama,
        "Jenis Kelamin": jk,
        "Umur": "0 Thn 3 Hari",
        "Tempat/Tgl Lahir": "JAKARTA/ 05-08-2026",
        "No Telp / HP": "08123456789",
        "Alamat": "jl melati RT 1 RW 2 Kel Tebet",
    }


def _mem_ikterus(kuning, *, onset=None, telapak=None):
    """A "Memeriksa Ikterus" questionnaire block (server-rendered in ``fields``)."""
    return {
        "Apakah bayi kuning": kuning,
        "Pada umur berapa pertama kali timbul kuning?": onset,
        "Ada kuning di mata atau kulit?": "Ya" if kuning == "Ya" else "Tidak",
        "Lihat telapak tangan dan telapak kaki bayi, apakah kuning": telapak,
    }


def _epus_bayi(*, nik="3175010101010001", nama="BAYI NYONYA LINDA",
               ikterus_sd=None, ikterus_q=None, pjb_tab=None, penyakit=None,
               rujukan=None):
    tabs: dict = {}
    if ikterus_sd is not None or ikterus_q is not None:
        mtbm: dict = {"module": "mtbm", "fields": {}, "saved_detail": ikterus_sd}
        if ikterus_q is not None:
            mtbm["fields"]["Memeriksa Ikterus"] = ikterus_q
        tabs["Manajemen Terpadu Bayi Muda"] = mtbm
    if pjb_tab is not None:
        tabs["Skrining PJB"] = {"module": "skriningpjb", **pjb_tab}
    return {
        "data_pasien": _bayi_dp(nik=nik, nama=nama),
        "penyakit_khusus": penyakit or [],
        "tabs": tabs,
        "rujukan": rujukan or {},
    }


def _epus_parent(*, nik="3175010101010001"):
    """The mother sharing the bayi's NIK — must be excluded by the bayi filter."""
    return {
        "data_pasien": {
            "NIK": nik, "Nama Pasien": "NI KOMANG LINDA", "Jenis Kelamin": "P",
            "Umur": "30 Thn 2 Bln", "Tempat/Tgl Lahir": "JAKARTA/ 01-01-1996",
        },
        "penyakit_khusus": [],
        "tabs": {},
    }


def _pjb_sd(tangan="Tangan Kanan", sat_tangan="98", sat_kaki="95", interp="Terduga PJB"):
    return {"saved_detail": {"pemeriksaan": [{
        "tangan": tangan, "saturasi_tangan": sat_tangan,
        "kaki": "Kaki Kanan", "saturasi_kaki": sat_kaki,
        "interpretasi": interp, "warna": "Merah muda",
    }]}}


def _pjb_tables(sat_tangan="99", sat_kaki="97", interp="Waspada PJB"):
    return {"tables": {"Pemeriksaan Pulse Oksimetri": [{
        "Tangan": "Tangan Kanan", "Saturasi Tangan": sat_tangan,
        "Saturasi Kaki": sat_kaki, "Interpretasi": interp,
    }]}}


def _row(fd, epus, *, nik="3175010101010001", nama="BAYI NYONYA LINDA", group=None):
    return SimpleNamespace(
        id=uuid.uuid4(), nik=nik, nama=nama, filter_date=fd,
        match_group_id=group, scraped_epus_data=encrypt_json(epus),
    )


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeDB:
    """Single-execute stub — the EPUS-only scan issues exactly one query."""

    def __init__(self, rows):
        self._rows = sorted(rows, key=lambda r: (r.nik, r.filter_date))

    def execute(self, _stmt):
        return _FakeResult(self._rows)


def _scan(rows):
    return {b["nik"]: b for b in scan_bayi_registry(_FakeDB(rows), uuid.uuid4(), _YEAR)["bayi"]}


# ── bayi vs parent identity ────────────────────────────────────────────────
def test_is_bayi_by_name_and_umur():
    assert _is_bayi(_epus_bayi()) is True
    assert _is_bayi({"data_pasien": {"Nama Pasien": "SITI", "Umur": "0 Thn 1 Hari"}}) is True
    assert _is_bayi(_epus_parent()) is False
    assert _is_bayi({"data_pasien": {"Nama Pasien": "BUDI", "Umur": "25 Thn"}}) is False
    assert _is_bayi(None) is False


def test_parent_sharing_nik_is_excluded():
    """Parent + bayi share the NIK; only the bayi (positive ikterus) is emitted."""
    rows = [
        _row(date(_YEAR, 8, 5), _epus_parent(), nama="NI KOMANG LINDA"),
        _row(date(_YEAR, 8, 5), _epus_bayi(ikterus_sd={"klasifikasi": {"2": "2"}})),
    ]
    out = _scan(rows)
    assert len(out) == 1
    b = next(iter(out.values()))
    assert b["nama"] == "BAYI NYONYA LINDA"
    assert b["ikterus"]["baseline"]["klasifikasi"] == _IKTERUS
    assert b["ikterus"]["baseline"]["sources"]["klasifikasi"] == _SRC_EPUS


# ── ikterus classification: EPUS saved_detail (source of truth) ─────────────
def test_ikterus_from_saved_detail_is_epus_sourced():
    def klas(sd):
        return _extract_ikterus_klasifikasi(_epus_bayi(ikterus_sd=sd))

    # bracketed [klasifikasi][2] = code, as a nested {index: code} dict
    assert klas({"klasifikasi": {"2": "2"}}) == (_IKTERUS, _SRC_EPUS)
    assert klas({"klasifikasi": {"2": "3"}}) == (_IKTERUS_BERAT, _SRC_EPUS)
    assert klas({"klasifikasi": {"2": "1"}}) == (_IKTERUS_TIDAK, _SRC_EPUS)
    # list of detail records
    assert klas([{"klasifikasi": "3"}]) == (_IKTERUS_BERAT, _SRC_EPUS)
    # already a label string
    assert klas({"MtbmDetail": {"klasifikasi": "Ikterus berat"}}) == (_IKTERUS_BERAT, _SRC_EPUS)
    # nothing recognisable, no questionnaire → ("", "")
    assert klas({"lain": "x"}) == ("", "")
    # no mtbm tab at all → ("", "")
    assert _extract_ikterus_klasifikasi(_epus_bayi()) == ("", "")


# ── ikterus classification: derived from the MTBM questionnaire (fallback) ───
def test_ikterus_derived_from_questionnaire():
    def d(**kw):
        return _extract_ikterus_klasifikasi(_epus_bayi(ikterus_q=_mem_ikterus(**kw)))

    assert d(kuning="Tidak") == (_IKTERUS_TIDAK, _SRC_DERIVED)
    assert d(kuning="Ya", onset="> 24 jam s/d 14 hari") == (_IKTERUS, _SRC_DERIVED)
    # MTBM severe criteria: onset < 24 jam, onset > 14 hari, OR kuning at soles
    assert d(kuning="Ya", onset="< 24 jam") == (_IKTERUS_BERAT, _SRC_DERIVED)
    assert d(kuning="Ya", onset="> 14 hari") == (_IKTERUS_BERAT, _SRC_DERIVED)
    assert d(kuning="Ya", onset="> 24 jam s/d 14 hari", telapak="Ya") == (
        _IKTERUS_BERAT, _SRC_DERIVED)
    # unanswered kuning → no classification
    assert d(kuning=None) == ("", "")


def test_epus_saved_detail_wins_over_questionnaire():
    """When both exist, EPUS's own klasifikasi field takes priority + tags EPUS."""
    epus = _epus_bayi(ikterus_sd={"klasifikasi": {"2": "3"}},
                      ikterus_q=_mem_ikterus(kuning="Tidak"))
    assert _extract_ikterus_klasifikasi(epus) == (_IKTERUS_BERAT, _SRC_EPUS)


# ── PJB pulse-ox ───────────────────────────────────────────────────────────
def test_pjb_from_saved_detail():
    pjb = _extract_pjb(_epus_bayi(pjb_tab=_pjb_sd(sat_tangan="97", sat_kaki="92")))
    assert pjb["saturasi_tangan_kanan"] == "97"
    assert pjb["saturasi_kaki"] == "92"
    assert pjb["interpretasi"] == "Terduga PJB"
    assert _pjb_qualifies(pjb) is True


def test_pjb_from_tables_fallback():
    pjb = _extract_pjb(_epus_bayi(pjb_tab=_pjb_tables(interp="Waspada PJB")))
    assert pjb["saturasi_tangan_kanan"] == "99"
    assert pjb["saturasi_kaki"] == "97"
    assert _pjb_qualifies(pjb) is True


def test_pjb_negative_not_qualifying():
    pjb = _extract_pjb(_epus_bayi(pjb_tab=_pjb_sd(interp="Normal")))
    assert pjb is not None
    assert _pjb_qualifies(pjb) is False


def test_pjb_absent_is_none():
    assert _extract_pjb(_epus_bayi()) is None


# ── per-sheet inclusion + counts ───────────────────────────────────────────
def test_no_qualifying_data_is_dropped():
    rows = [_row(date(_YEAR, 8, 5), _epus_bayi(ikterus_sd={"klasifikasi": {"2": "1"}}))]
    assert _scan(rows) == {}  # "Tidak ada ikterus" + no PJB → no sheet


def test_sheet_flags_and_counts():
    rows = [
        _row(date(_YEAR, 8, 5),
             _epus_bayi(nik="1", nama="BAYI A", ikterus_sd={"klasifikasi": {"2": "3"}}),
             nik="1", nama="BAYI A"),
        _row(date(_YEAR, 8, 6),
             _epus_bayi(nik="2", nama="BAYI B", ikterus_sd={"klasifikasi": {"2": "2"}}),
             nik="2", nama="BAYI B"),
        _row(date(_YEAR, 8, 7),
             _epus_bayi(nik="3", nama="BAYI C", pjb_tab=_pjb_sd(interp="Waspada PJB")),
             nik="3", nama="BAYI C"),
    ]
    out = _scan(rows)
    assert out["1"]["qualifies_ikterus"] and out["1"]["qualifies_ikterus_berat"]
    assert out["2"]["qualifies_ikterus"] and not out["2"]["qualifies_ikterus_berat"]
    assert out["3"]["qualifies_pjbk"] and not out["3"]["qualifies_ikterus"]
    pjbk, ikt, berat = count_sheet_bands(list(out.values()))
    assert (pjbk, ikt, berat) == (1, 2, 1)


def test_pemantauan_and_twin_collapse():
    rows = [
        # baseline (positive ikterus)
        _row(date(_YEAR, 8, 5), _epus_bayi(ikterus_sd={"klasifikasi": {"2": "3"}}), group=None),
        # follow-up visit → pemantauan row
        _row(date(_YEAR, 8, 12), _epus_bayi(ikterus_sd={"klasifikasi": {"2": "2"}}),
             group=uuid.uuid4()),
    ]
    # add a re-scrape twin of the follow-up (same match_group_id) → collapses
    twin_group = rows[1].match_group_id
    rows.append(
        _row(date(_YEAR, 8, 12), _epus_bayi(ikterus_sd={"klasifikasi": {"2": "2"}}),
             group=twin_group)
    )
    b = next(iter(_scan(rows).values()))
    assert b["ikterus"]["baseline"]["klasifikasi"] == _IKTERUS_BERAT
    assert len(b["ikterus"]["pemantauan"]) == 1  # twin collapsed
    assert b["ikterus"]["pemantauan"][0]["klasifikasi"] == _IKTERUS


def test_diagnosis_from_penyakit_khusus():
    b = next(iter(_scan([
        _row(date(_YEAR, 8, 5), _epus_bayi(
            ikterus_sd={"klasifikasi": {"2": "3"}},
            penyakit=[{"ICDX": "P59.9", "Penyakit": "Neonatal jaundice"}],
        )),
    ]).values()))
    assert "Neonatal jaundice" in b["ikterus"]["baseline"]["diagnosis"]
    assert b["ikterus"]["baseline"]["sources"]["diagnosis"] == _SRC_EPUS


def test_rujuk_eksternal_from_show_referral():
    """Rujuk Eksternal = destination facilities from the show-page referral table,
    de-duplicated and joined; absent → ""."""
    ruj = {"external": [
        {"No.": "1", "Tanggal": "05-08-2026", "Rujukan External": "RSUD POSO"},
        {"No.": "2", "Rujukan External": "RSUD POSO"},          # dup collapses
        {"No.": "3", "Rujukan External": "RSU SINAR KASIH"},
    ]}
    b = next(iter(_scan([
        _row(date(_YEAR, 8, 5),
             _epus_bayi(ikterus_q=_mem_ikterus(kuning="Ya", onset="< 24 jam"),
                        rujukan=ruj)),
    ]).values()))
    assert b["ikterus"]["baseline"]["rujuk_eksternal"] == "RSUD POSO; RSU SINAR KASIH"


def test_rujuk_eksternal_absent_is_blank():
    b = next(iter(_scan([
        _row(date(_YEAR, 8, 5),
             _epus_bayi(ikterus_q=_mem_ikterus(kuning="Ya", onset="< 24 jam"))),
    ]).values()))
    assert b["ikterus"]["baseline"]["rujuk_eksternal"] == ""


def test_derived_bayi_qualifies_end_to_end():
    """A bayi classified only via the questionnaire still qualifies + tags Hitung."""
    rows = [_row(date(_YEAR, 8, 5),
                 _epus_bayi(ikterus_q=_mem_ikterus(kuning="Ya", onset="< 24 jam")))]
    b = next(iter(_scan(rows).values()))
    assert b["qualifies_ikterus"] and b["qualifies_ikterus_berat"]
    assert b["ikterus"]["baseline"]["klasifikasi"] == _IKTERUS_BERAT
    assert b["ikterus"]["baseline"]["sources"]["klasifikasi"] == _SRC_DERIVED
