"""Tests for the ASIK default-value policy (app/services/asik_defaults.py).

The sync fills a safe default for REQUIRED ASIK questions we have no data for.
This guards the policy that decides those values (see ASIK_DEFAULT_FILLS.md):
choice → lowest-risk option, number → clinical in-range value, age → never faked.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from app.services.asik_defaults import (
    _is_disease_option,
    build_default_values_map,
    normalize_label,
)

_SCRAPERS = Path(__file__).resolve().parents[2] / "scrapers"


def _load_scraper_sync():
    """Import scrapers/asik_sync/sync.py (the live scraper) for its pure helpers,
    skipping if its runtime deps (playwright, rich, …) aren't installed."""
    for p in (_SCRAPERS / "asik_sync", _SCRAPERS / "asik"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    try:
        spec = importlib.util.spec_from_file_location(
            "asik_sync_sync", _SCRAPERS / "asik_sync" / "sync.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:  # pragma: no cover - env without scraper deps
        pytest.skip(f"scraper module not importable: {exc}")


def _default_for(label: str):
    return build_default_values_map().get(normalize_label(label))


def test_choice_defaults_to_lowest_risk_option():
    # Hati risk questions (Ya/Tidak) → the negative answer.
    assert _default_for("Apakah Anda pernah menjalani cuci darah atau hemodialisis?") == {
        "value": "Tidak",
        "kind": "radio",
    }
    # PHQ-4 frequency → the zero-score option.
    d = _default_for(
        "Dalam 2 minggu terakhir, seberapa sering anda merasa murung, tertekan, atau putus asa?"
    )
    assert d == {"value": "Tidak sama sekali", "kind": "radio"}


def test_choice_defaults_normal_status_options():
    assert _default_for("Apakah Anda sedang hamil?")["value"] == "Tidak"
    assert _default_for("Apakah Anda penyandang disabilitas?")["value"] == "Non disabilitas"


def test_number_defaults_are_clinical_and_in_range():
    assert _default_for("Berat Badan (Kg)") == {"value": 60, "kind": "number"}
    assert _default_for("Kadar Hemoglobin")["value"] == 13
    assert _default_for("Tekanan Darah Sistolik")["value"] == 120
    assert _default_for("Tekanan darah diastolik")["value"] == 80
    # No impossible sentinels (Hb 50, systolic 50) that would fail ASIK validation.
    assert _default_for("Kadar Hemoglobin")["value"] != 50


def test_age_is_never_defaulted():
    # Usia is derived from the patient's DOB — never fabricated.
    assert _default_for("Usia") is None
    assert normalize_label("Usia") not in build_default_values_map()


def test_normalize_label_strips_number_prefix_and_asterisk():
    assert normalize_label("1. Berat Badan (Kg) *") == "berat badan (kg)"
    assert normalize_label("  Kadar   Hemoglobin  ") == "kadar hemoglobin"


def test_map_is_nonempty_and_values_present():
    m = build_default_values_map()
    assert len(m) > 200
    for norm, entry in m.items():
        assert entry.get("value") is not None
        assert entry.get("kind") in ("radio", "dropdown", "number", "text")


# --- Clinical-safety: ASIK's `nilai_poin` is NOT a universal risk score. A naive
# "lowest score" default fabricated positive diagnoses / worst-frailty scores on some
# forms. These guard the safe-keyword override that replaced it. ---

def test_lab_results_never_default_to_positif():
    # Newborn screening (SHK/G6PD/HAK) scores "Positif" *lower* than "Negatif" — a
    # naive lowest-score pick would default a congenital-disease screen to positive.
    for label in (
        "Skrining Hipotiroid Kongenital - Hasil pemeriksaan laboratorium (m[IU]/L)",
        "Skrining Defisiensi G6PD - hasil pemeriksaan laboratorium (U/dL)",
        "Skrining Hiperplasia Adrenal Kongenital (HAK)- hasil pemeriksaan laboratorium",
        "Hasil tes konfirmasi Defisiensi G6PD",
    ):
        assert _default_for(label) == {"value": "Negatif", "kind": "radio"}


def test_no_default_is_ever_a_disease_present_result():
    # The strongest invariant: not one entry in the map may be a positive/abnormal
    # finding (Positif / Reaktif / Abnormal / Kusta …). New drift trips this.
    for norm, entry in build_default_values_map().items():
        if entry["kind"] in ("radio", "dropdown"):
            assert not _is_disease_option(str(entry["value"])), (norm, entry)


def test_abnormal_findings_default_to_normal():
    for label in (
        "Hasil pemeriksaan pupil",             # was "Curiga Katarak"
        "Pemeriksaan Inspekulo",               # was "Curiga kanker"
        "Berapa Hasil Kramer pada Bayi Kuning ?",  # was "Bayi Kuning Kramer 1-3"
    ):
        assert _default_for(label)["value"] == "Normal"


def test_yes_no_risk_defaults_to_tidak_even_when_ya_scores_lower():
    # Regression guard: several risk questions score "Ya" LOWER than "Tidak"; the
    # default must still be "Tidak" (symptom absent), never a fabricated symptom.
    d = _default_for("Apakah Anda pernah menjalani tes untuk Hepatitis B dan mendapatkan hasil positif?")
    assert d["value"] == "Tidak"


def test_geriatric_performance_band_defaults_to_best_not_worst():
    # Gait/chair-stand time bands: safe default is the FASTEST (best) band.
    d = _default_for("tes kecepatan berjalan: Waktu untuk berjalan sejauh empat meter")
    assert d["value"] == "4,82 detik"


def test_disease_only_question_is_not_fabricated():
    # An EKG "abnormality detail" whose only option is abnormal must NOT be defaulted.
    assert _default_for("Detail Abnormalitas (EKG)") is None


def test_scraper_pick_safe_option_never_selects_abnormal():
    # The scraper's live fallback mirrors the backend policy. Regression guard for the
    # "normal" in "abnormal" substring bug: disease options are excluded BEFORE the
    # keyword net, so ["Abnormal", "Normal"] must resolve to "Normal", never "Abnormal".
    s = _load_scraper_sync()
    assert s._pick_safe_option(["Abnormal", "Normal"]) == "Normal"
    assert s._pick_safe_option(["Positif", "Negatif"]) == "Negatif"
    assert s._pick_safe_option(["Ya", "Tidak"]) == "Tidak"
    # A disease-only option list must not be fabricated → None (form fails safe).
    assert s._pick_safe_option(["Abnormal Gambaran Abnormal Lainnya"]) is None
