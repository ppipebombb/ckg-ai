"""Regression tests for the NIK-locate ASIK-year gate.

The sync locates a patient by NIK with NO date filter (ASIK's screening lands
days/weeks — sometimes a year — off the ePus date), then fills ONLY when a
matched search row's `screening_date` year equals the ePus (`filter_date`) year.
A wrong gate silently pushes one year's data onto another year's screening, so
these pin the two pure functions that decide it. Fully offline — no ASIK login.

Real cases these encode (verified live by the operator on Cipondoh):
  * MARGODIYONO 3208312508650001 — ePus 2025-07-21, ASIK screening 2026-04-21
    → year mismatch → skip.
  * a same-year screening → fill.
  * HERMAN 3173082605850004 — not present in any tab → no matched rows.

Run:
    cd scrapers/asik_sync && pytest tests/test_year_gate.py
    python3 tests/test_year_gate.py
"""
import os
import sys

_SYNC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SYNC_DIR)
sys.path.insert(0, os.path.dirname(_SYNC_DIR))            # scrapers/  (for _lifecycle)
sys.path.insert(0, os.path.join(os.path.dirname(_SYNC_DIR), "asik"))  # helpers

from sync import _asik_year_skip, _extract_search_rows  # noqa: E402


# ── _extract_search_rows ─────────────────────────────────────────────────────
def test_extract_reads_nik_and_screening_date():
    body = {"data": [
        {"patient_nik": "3208312508650001", "screening_date": "2026-04-21",
         "patient_full_name": "MARGODIYONO", "reg_id": "R1"},
    ]}
    rows = _extract_search_rows(body)
    assert rows == [{"nik": "3208312508650001",
                     "screening_date": "2026-04-21", "name": "MARGODIYONO"}]


def test_extract_handles_nested_data_and_missing_screening_date():
    rows = _extract_search_rows({"data": {"list": [{"nik": "X"}]}})
    assert rows == [{"nik": "X", "screening_date": None, "name": ""}]


def test_extract_empty_vs_unrecognised():
    assert _extract_search_rows({"data": []}) == []   # recognised-but-empty tab
    assert _extract_search_rows({"foo": 1}) is None   # unknown shape → cannot verify
    assert _extract_search_rows("nope") is None


# ── _asik_year_skip ──────────────────────────────────────────────────────────
def test_year_mismatch_skips():
    rows = [{"nik": "3208312508650001", "screening_date": "2026-04-21"}]
    assert _asik_year_skip(rows, "2025-07-21") == (True, ["2026"])


def test_same_year_fills():
    rows = [{"nik": "N", "screening_date": "2025-07-25"}]
    assert _asik_year_skip(rows, "2025-07-21") == (False, ["2025"])


def test_multiple_years_not_a_mismatch_but_caller_treats_as_ambiguous():
    # The gate reports no year-mismatch (2025 IS among the years) and surfaces
    # BOTH years. The caller (run) sees len(years) > 1 and safe-skips as
    # "ambiguous_multi_year" rather than risk filling the wrong screening.
    rows = [{"nik": "N", "screening_date": "2025-03-01"},
            {"nik": "N", "screening_date": "2026-01-09"}]
    should_skip, years = _asik_year_skip(rows, "2025-07-21")
    assert should_skip is False and years == ["2025", "2026"]


def test_no_rows_never_year_skips():
    # not-found is handled by the caller as a separate skip, not here
    assert _asik_year_skip([], "2025-07-21") == (False, [])


def test_missing_screening_date_is_not_a_year_mismatch():
    # The gate itself reports (no year-mismatch, no years). When there is no
    # year to compare, the CALLER (run) safe-skips as "no_screening_date" rather
    # than filling blind — so an empty row_years must not read as a mismatch.
    assert _asik_year_skip([{"nik": "N", "screening_date": None}], "2025-07-21") == (False, [])


def test_no_filter_date_proceeds():
    assert _asik_year_skip([{"nik": "N", "screening_date": "2026-04-21"}], None) == (False, ["2026"])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
