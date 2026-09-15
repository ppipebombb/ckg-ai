"""Regression tests for `_read_all_form_fields` (the SurveyJS DOM reader).

These pin the behavior of the form reader against silent-corruption bugs found
while building the Tatalaksana scrape (2026-06-16). They run entirely offline —
the SurveyJS DOM is built as a string fixture and loaded into a headless
Chromium via `page.set_content`, so no ASIK login / network is needed.

Each test guards a specific, previously-broken case:
  * empty radio/checkbox  -> null  (NOT the first option as a phantom default)
  * prefix-related distinct questions are both kept (dedup must not delete one)
  * radio "Lainnya" + free text appends the typed detail
  * SurveyJS boolean reads true/false/unanswered correctly
  * filled text/number("0")/textarea/dropdown still read; empties stay null

Run:
    cd scrapers/asik && pytest tests/test_form_reader.py        # under pytest
    python3 tests/test_form_reader.py                           # standalone
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright  # noqa: E402
from patient_scraper import _read_all_form_fields  # noqa: E402


# ── SurveyJS DOM fixture builders ────────────────────────────────────────────
def _q(name, title, content):
    title_html = (
        f'<div class="sd-question__title"><span class="sv-string-viewer">{title}</span></div>'
        if title else ""
    )
    return (
        f'<div class="sd-question" data-name="{name}" style="display:block">'
        f'{title_html}<div class="sd-question__content">{content}</div></div>'
    )


def _radio(name, options, checked=None):
    s = ""
    for val, lbl in options:
        c = "checked" if val == checked else ""
        s += (
            f'<label class="sd-selectbase__label"><input type="radio" name="{name}" '
            f'value="{val}" {c}><span class="sd-item__control-label">'
            f'<span class="sv-string-viewer">{lbl}</span></span></label>'
        )
    return f'<div class="sd-selectbase">{s}</div>'


def _checkbox(name, options, checked=()):
    s = ""
    for val, lbl in options:
        c = "checked" if val in checked else ""
        s += (
            f'<label class="sd-selectbase__label"><input type="checkbox" name="{name}" '
            f'value="{val}" {c}><span class="sd-item__control-label">'
            f'<span class="sv-string-viewer">{lbl}</span></span></label>'
        )
    return f'<div class="sd-selectbase">{s}</div>'


def _boolean(name, checked):
    c = "checked" if checked else ""
    return (
        f'<div class="sd-boolean"><input type="checkbox" class="sd-boolean__checkbox" name="{name}" {c}>'
        '<span class="sd-boolean__label sd-boolean__label--false"><span class="sv-string-viewer">Tidak</span></span>'
        '<span class="sd-boolean__label sd-boolean__label--true"><span class="sv-string-viewer">Ya</span></span></div>'
    )


_YN = [("ya", "Ya"), ("tidak", "Tidak")]

_RADIO_OTHER = (
    '<div class="sd-selectbase">'
    '<label class="sd-selectbase__label"><input type="radio" name="ro" value="a">'
    '<span class="sd-item__control-label"><span class="sv-string-viewer">Demam</span></span></label>'
    '<label class="sd-selectbase__label"><input type="radio" name="ro" value="other" checked>'
    '<span class="sd-item__control-label"><span class="sv-string-viewer">Lainnya</span></span></label>'
    '<input type="text" class="sd-input sd-comment" value="Sakit kepala hebat">'
    "</div>"
)

_FIXTURE = "<!doctype html><html><body>" + "".join([
    _q("r_ya", "Apakah pasien diberikan diagnosis ?", _radio("r_ya", _YN, checked="ya")),
    _q("r_tidak", "Apakah pasien dirujuk ?", _radio("r_tidak", _YN, checked="tidak")),
    _q("r_empty", "Apakah pasien diberikan obat", _radio("r_empty", _YN, checked=None)),
    _q("cb_one", "Gejala yang dialami", _checkbox("cb_one", [("a", "Pusing"), ("b", "Mual")], checked=("a",))),
    _q("cb_multi", "Gejala", _checkbox("cb_multi", [("a", "Pusing"), ("b", "Mual"), ("c", "Demam")], checked=("a", "c"))),
    _q("cb_empty", "Riwayat alergi", _checkbox("cb_empty", [("a", "Obat"), ("b", "Makanan")], checked=())),
    _q("txt", "Tanggal pelaksanaan", '<input type="text" class="sd-input" value="2026-05-05">'),
    _q("txt_empty", "Catatan tambahan", '<input type="text" class="sd-input" value="">'),
    _q("num_zero", "Jumlah anak", '<input type="number" class="sd-input" value="0">'),
    _q("ta", "Catatan dokter", '<textarea class="sd-input">Pasien stabil</textarea>'),
    _q("dd", "Jenis kelamin",
       '<div class="sd-dropdown" role="combobox"><div class="sd-dropdown__value">'
       '<span class="sv-string-viewer">Perempuan</span></div></div>'),
    _q("dd_empty", "Golongan darah",
       '<div class="sd-dropdown" role="combobox">'
       '<input class="sd-dropdown__filter-string-input" placeholder="Pilih..." value=""></div>'),
    # prefix-collision: two DISTINCT questions, one label a prefix of the other, same value
    _q("p1", "Apakah pasien dirujuk", _radio("p1", _YN, checked="ya")),
    _q("p2", "Apakah pasien dirujuk ke FKTL", _radio("p2", _YN, checked="ya")),
    _q("ro", "Keluhan utama", _RADIO_OTHER),
    _q("bt", "Setuju ikut program (true)", _boolean("bt", True)),
    _q("bf", "Setuju ikut program (false)", _boolean("bf", False)),
    _q("bu", "Setuju ikut program (unset)", _boolean("bu", False)),  # indeterminate set below
]) + "</body></html>"


# Read the whole fixture once; share across assertions (chromium launch is slow).
_RESULT_CACHE = {}


def _result():
    if "data" not in _RESULT_CACHE:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(_FIXTURE)
            # SurveyJS represents an unanswered boolean as indeterminate.
            page.evaluate(
                "() => { const cb = document.querySelector('input[name=\"bu\"]');"
                " if (cb) cb.indeterminate = true; }"
            )
            _RESULT_CACHE["data"] = _read_all_form_fields(page)
            browser.close()
    return _RESULT_CACHE["data"]


# ── Tests ────────────────────────────────────────────────────────────────────
def test_answered_radio_reads_label():
    assert _result().get("Apakah pasien diberikan diagnosis ?") == "Ya"
    assert _result().get("Apakah pasien dirujuk ?") == "Tidak"


def test_empty_radio_is_null_not_first_option():
    # The bug: an unanswered radio read back as "Ya" (the first option).
    assert _result().get("Apakah pasien diberikan obat") is None


def test_answered_checkbox_reads_label():
    assert _result().get("Gejala yang dialami") == "Pusing"


def test_multiple_checkboxes_joined():
    assert _result().get("Gejala") == "Pusing, Demam"


def test_empty_checkbox_is_null():
    assert _result().get("Riwayat alergi") is None


def test_filled_text_and_number_and_textarea():
    assert _result().get("Tanggal pelaksanaan") == "2026-05-05"
    assert _result().get("Jumlah anak") == "0"          # "0" must not be lost as falsy
    assert _result().get("Catatan dokter") == "Pasien stabil"


def test_empty_text_is_null():
    assert _result().get("Catatan tambahan") is None


def test_dropdown_answered_and_empty():
    assert _result().get("Jenis kelamin") == "Perempuan"
    assert _result().get("Golongan darah") is None


def test_prefix_related_questions_both_kept():
    # The bug: the dedup deleted "...dirujuk ke FKTL" because it starts with
    # "...dirujuk" and shares the "Ya" value.
    r = _result()
    assert r.get("Apakah pasien dirujuk") == "Ya"
    assert r.get("Apakah pasien dirujuk ke FKTL") == "Ya"


def test_radio_lainnya_appends_free_text():
    assert _result().get("Keluhan utama") == "Lainnya: Sakit kepala hebat"


def test_boolean_true_false_unset():
    r = _result()
    assert r.get("Setuju ikut program (true)") == "Ya"
    assert r.get("Setuju ikut program (false)") == "Tidak"   # explicit false, NOT null
    assert r.get("Setuju ikut program (unset)") is None


def test_title_less_display_elements_dropped():
    # A question with no visible title is a display/expression panel, not data.
    assert "" not in _result()


if __name__ == "__main__":
    tests = sorted(k for k, v in dict(globals()).items() if k.startswith("test_") and callable(v))
    failed = 0
    for name in tests:
        try:
            globals()[name]()
            print(f"  [PASS] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
