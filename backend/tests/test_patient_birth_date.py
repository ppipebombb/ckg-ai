"""Unit tests for birth-date extraction + the age-range boundary math.

Pure functions — no DB. Covers the edge cases the umur/age filter must not miss:
the two source formats (EPUS slash vs jaksel comma; ASIK "DD NamaBulan YYYY"),
impossible dates, EPUS-wins precedence, and the off-by-one at the year boundary
(including a Feb-29 birthday).
"""

from datetime import date

from app.api.routes.patients import _years_ago
from app.services.birthdate import (
    birth_date_from_asik,
    birth_date_from_epus,
    birth_date_for_patient,
)


def _epus(ttl):
    return {"data_pasien": {"Tempat/Tgl Lahir": ttl}}


def _asik(tgl):
    return {"detail_data": {"data_individu": {"Tanggal Lahir": tgl}}}


# ── EPUS parsing ────────────────────────────────────────────────────────────
def test_epus_slash_format():
    assert birth_date_from_epus(_epus("BEKASI/ 08-06-1974")) == date(1974, 6, 8)


def test_epus_jaksel_comma_key_and_separator():
    assert birth_date_from_epus(
        {"data_pasien": {"Tempat & Tgl Lahir": "Jakarta, 07-10-1978"}}
    ) == date(1978, 10, 7)


def test_epus_newline_and_whitespace_noise():
    assert birth_date_from_epus(_epus("BEKASI/\n  08-06-1974")) == date(1974, 6, 8)


def test_epus_impossible_date_is_none():
    assert birth_date_from_epus(_epus("X/ 31-02-1990")) is None


def test_epus_missing_or_garbage_is_none():
    assert birth_date_from_epus(_epus("")) is None
    assert birth_date_from_epus(_epus("no date here")) is None
    assert birth_date_from_epus({}) is None
    assert birth_date_from_epus(None) is None


# ── ASIK parsing ────────────────────────────────────────────────────────────
def test_asik_indonesian_month():
    assert birth_date_from_asik(_asik("25 Januari 2000")) == date(2000, 1, 25)


def test_asik_unknown_month_is_none():
    assert birth_date_from_asik(_asik("25 Janooary 2000")) is None


def test_asik_missing_is_none():
    assert birth_date_from_asik(_asik("")) is None
    assert birth_date_from_asik({}) is None
    assert birth_date_from_asik(None) is None


# ── Precedence: EPUS wins, ASIK fills ───────────────────────────────────────
def test_precedence_epus_wins_when_both_present():
    epus = _epus("X/ 08-06-1974")
    asik = _asik("25 Januari 2000")
    assert birth_date_for_patient(epus, asik) == date(1974, 6, 8)


def test_precedence_falls_back_to_asik_when_epus_absent():
    assert birth_date_for_patient(None, _asik("25 Januari 2000")) == date(2000, 1, 25)
    assert birth_date_for_patient(_epus(""), _asik("25 Januari 2000")) == date(2000, 1, 25)


def test_precedence_none_when_neither_parseable():
    assert birth_date_for_patient(_epus("junk"), _asik("junk")) is None


# ── Age-range boundary math (current age = today - birth_date) ───────────────
# Predicate: min_age -> birth_date <= _years_ago(today, min_age)
#            max_age -> birth_date >  _years_ago(today, max_age + 1)
TODAY = date(2026, 6, 23)


def test_years_ago_basic():
    assert _years_ago(TODAY, 60) == date(1966, 6, 23)
    assert _years_ago(TODAY, 61) == date(1965, 6, 23)


def test_years_ago_feb29_clamps_to_28_in_nonleap_target():
    assert _years_ago(date(2024, 2, 29), 1) == date(2023, 2, 28)


def test_years_ago_feb29_preserved_in_leap_target():
    assert _years_ago(date(2024, 2, 29), 4) == date(2020, 2, 29)


def test_person_exactly_60_today_is_in_band_60_60():
    born = date(1966, 6, 23)  # turns 60 exactly today
    assert born <= _years_ago(TODAY, 60)        # min_age=60 includes (equal)
    assert born > _years_ago(TODAY, 60 + 1)     # max_age=60 includes


def test_person_who_just_turned_61_today_excluded_from_max_60():
    born = date(1965, 6, 23)  # turns 61 exactly today -> age 61
    assert not (born > _years_ago(TODAY, 60 + 1))  # max_age=60 excludes


def test_person_still_60_until_tomorrow_included_in_max_60():
    born = date(1965, 6, 24)  # 61 tomorrow, still 60 today
    assert born > _years_ago(TODAY, 60 + 1)     # max_age=60 includes
