"""Safe default values for ASIK required questions we have no data for.

ASIK rejects a form submission when a *required* question is left blank. When the
merge produced no value for such a question, the sync fills a **safe default** and
logs it (see `patients.asik_default_fills`), so dashboards can separate real data
from auto-filled placeholders.

Policy (see `ASIK_DEFAULT_FILLS.md`):
  - choice (radio / dropdown) → the **lowest-risk** option. When ASIK scores the
    options (`nilai_poin`), lowest score == least-risk == the default (Ya/Tidak →
    Tidak, PHQ frequency → "Tidak sama sekali", …). Otherwise a negative/normal
    keyword, else the first option.
  - number → a fixed **clinically-normal, in-range** value (never a sentinel like
    50 that could be impossible for Hb or dangerous for blood pressure and would
    also trip ASIK's own min/max validator).
  - **Usia (age) is never defaulted** — it is derived from the patient's DOB.

The map is keyed by a *normalized* question label so the live ASIK title matches
the documented `asik_form_mapping.json` label despite whitespace drift. The map is
built here (backend) and passed to the sync scraper, which applies it at fill-time;
anything not in the map falls back to a live heuristic in the scraper.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_MAPPING_PATH = Path(__file__).resolve().parent.parent / "data" / "asik_form_mapping.json"

# Fixed clinical, in-range defaults for every number question in ASIK. Matched by
# substring against the normalized label (ORDER MATTERS: more specific first, e.g.
# "gula darah sewaktu kedua" before "gula darah sewaktu", "kreatinin urin" before
# "kreatinin"). Values are round + clinically normal so they always pass ASIK's
# per-field min/max validators. `None` marks a field we must NOT auto-fill.
_NUMBER_DEFAULTS: tuple[tuple[str, object], ...] = (
    ("usia", None),  # never fabricate age — derived from DOB
    ("berat badan", 60),
    ("tinggi badan", 160),
    ("lingkar perut", 80),
    ("hemoglobin", 13),
    ("sgot", 25),
    ("trombosit", 250000),
    ("gula darah sewaktu kedua", 100),
    ("gds 2", 100),
    ("gula darah sewaktu", 100),
    ("gula darah puasa", 90),
    ("gula darah 2 jam", 110),
    ("2 jam pp", 110),
    ("kadar co", 3),
    ("kolesterol total", 180),
    ("trigliserida", 120),
    ("hdl", 55),
    ("kreatinin urin", 100),
    ("konsentrasi kreatinin", 100),
    ("kreatinin", 0.9),
    ("ureum", 25),
    ("e-lfg", 95),
    ("ckd-epi", 95),
    ("albumin urin", 15),
    ("sistolik", 120),
    ("diastolik", 80),
    ("ldl", 100),
)

# Negative / normal keywords used to pick a safe option when ASIK does not score
# the choices. Ordered most-specific-first.
_SAFE_OPTION_KEYWORDS = (
    "tidak ada", "tidak sama sekali", "negatif", "normal", "non ",
    "tidak", "belum", "tidak batuk",
)

# Unambiguous "no finding / negative result" option phrases. These WIN over ASIK's
# raw `nilai_poin` because ASIK does not score consistently: for a newborn lab the
# option "Positif" is scored *lower* than "Negatif", so a naive lowest-score pick
# would default a congenital-disease screen to Positif. Ordered most-specific-first.
_SAFE_RESULT_KEYWORDS = (
    "tidak ada", "tidak sama sekali", "non reaktif", "non-reaktif",
    "tidak reaktif", "negatif", "tidak batuk", "bukan",
)

# Disease-present / abnormal result words. We NEVER auto-default a required question
# to one of these (a fabricated positive diagnosis is the worst failure of this tool);
# when the safe pole can't be identified we return None and let the scraper's live
# fallback (which sees the real options) pick the negative one, or leave it blank.
_DISEASE_KEYWORDS = ("positif", "reaktif", "abnormal", "kusta", "bakteriologis", "klinis")
_NEGATION_TOKENS = ("non", "tidak", "bukan", "negatif")


def _is_safe_result_option(text: str) -> bool:
    t = text.lower()
    if any(kw in t for kw in _SAFE_RESULT_KEYWORDS):
        return True
    return "normal" in t and "abnormal" not in t


def _is_disease_option(text: str) -> bool:
    t = text.lower()
    if _is_safe_result_option(t):
        return False
    for w in _DISEASE_KEYWORDS:
        if w in t and not any(neg in t for neg in _NEGATION_TOKENS):
            return True
    return False


def normalize_label(label: str | None) -> str:
    """Canonical form for matching a live ASIK title to a documented label.

    Strips a leading "N." number prefix and a trailing "*", collapses whitespace
    (incl. non-breaking spaces), and lowercases — mirrors the scraper's
    `_clean_question_label` plus lowercasing so both sides compare equal.
    """
    s = (label or "").replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^\d+\.\s*", "", s)
    s = re.sub(r"\s*\*\s*$", "", s)
    return s.strip().lower()


def _number_default(norm_label: str) -> object | None:
    """Fixed in-range value for a number question, or None if we must not fill it."""
    for needle, value in _NUMBER_DEFAULTS:
        if needle in norm_label:
            return value
    return None


def _choice_default(question: dict) -> str | None:
    """Clinically-safe option for a choice question, or None if none can be trusted.

    ASIK's `nilai_poin` is NOT a universal risk score — some forms (newborn SHK/G6PD
    lab results, geriatric SPPB/SKILAS performance bands) score it inverted, so a naive
    "lowest score" pick would default a screen to "Positif" or the worst-frailty band.
    So an explicit clinical-safe signal wins over the raw score:

      1. an unambiguous negative/normal result option (Negatif, Non Reaktif, Normal…);
      2. a Ya/Tidak pair → "Tidak" (risk/symptom absent — safe for the vast majority;
         the rare capability question, e.g. "dapat mengingat", also lands on "Tidak",
         which is over-cautious but never a fabricated diagnosis);
      3. a graded time/performance band ("… detik") → the best band (highest score);
      4. else lowest `nilai_poin`, but never a disease-present option;
      5. else None — we do NOT fabricate a positive/abnormal finding; the scraper's
         live fallback (real options) or an honest skip handles it.

    Returns the exact option text so the scraper's case-insensitive match hits.
    """
    choices = question.get("choices") or []
    scored = [
        (c.get("nilai_poin"), c.get("line"))
        for c in choices
        if c.get("line")
    ]
    lines = [l for _, l in scored]

    if not lines:
        options = [o for o in (question.get("live_options") or []) if o]
        if not options:
            return None
        for kw in _SAFE_OPTION_KEYWORDS:
            for o in options:
                if kw in o.lower():
                    return o
        return options[0]

    # 1. An explicit "no finding / negative" option wins over ASIK's raw score.
    for l in lines:
        if _is_safe_result_option(l):
            return l

    # 2. Ya/Tidak → "Tidak" (risk/symptom absent). ASIK's nilai_poin is unreliable here
    #    (some risk questions score "Ya" lower), so we ignore the score and use the pole.
    low = [l.lower() for l in lines]
    if low and set(low) <= {"ya", "tidak"}:
        for l in lines:
            if l.lower() == "tidak":
                return l
        return None  # only "Ya" in the spec (a risk symptom) → let the live fallback pick "Tidak"

    # 3. Graded time/performance band → the best-performing band (highest score).
    if any("detik" in l.lower() for l in lines) and any(p is not None for p, _ in scored):
        best = max((s for s in scored if s[0] is not None), key=lambda x: x[0])
        return best[1]

    # 4. Lowest nilai_poin, but never a disease-present option.
    usable = [(p, l) for p, l in scored if p is not None and not _is_disease_option(l)]
    if usable:
        usable.sort(key=lambda x: x[0])
        return usable[0][1]

    # 5. Unscored non-disease options: keyword net; else don't fabricate a finding.
    non_disease = [l for l in lines if not _is_disease_option(l)]
    for kw in _SAFE_OPTION_KEYWORDS:
        for o in non_disease:
            if kw in o.lower():
                return o
    return non_disease[0] if non_disease else None


def _question_kind(question: dict) -> str:
    lk = question.get("live_kind")
    if lk in ("radio", "dropdown", "number", "text"):
        return lk
    # Spec-only question (no live audit): infer from presence of choices.
    if question.get("choices") or question.get("live_options"):
        return "radio"
    return "unknown"


@lru_cache(maxsize=1)
def build_default_values_map() -> dict[str, dict]:
    """{normalized_label: {"value": <default>, "kind": <radio|dropdown|number|text>}}.

    Covers every question in `asik_form_mapping.json` for which a safe default can
    be derived. Questions with no derivable default (e.g. an unknown-type spec-only
    field, or Usia) are omitted — the scraper leaves those to its live fallback /
    keeps them blank (a still-blank required field means the form can't submit,
    which is the honest outcome rather than a fabricated number).
    """
    data = json.loads(_MAPPING_PATH.read_text())
    out: dict[str, dict] = {}
    for form in data.get("forms", []):
        for q in form.get("questions", []):
            label = q.get("label")
            if not label:
                continue
            norm = normalize_label(label)
            if not norm or norm in out:
                continue
            # Classify by the AUDITED live_kind only. A loose "does the label contain
            # a measurement word" test wrongly tags radios like "Apakah berat badan
            # Anda turun…?" as numbers → the scraper would try to type 60 into a
            # Ya/Tidak radio and fail. Number-value matching stays label-based, but
            # only for questions ASIK actually renders as a number input.
            kind = _question_kind(q)
            if kind == "number":
                value = _number_default(norm)
                if value is None:
                    continue  # never-default (age)
                out[norm] = {"value": value, "kind": "number"}
            else:
                value = _choice_default(q)
                if value is None:
                    continue
                out[norm] = {"value": value, "kind": kind if kind != "unknown" else "radio"}
    return out
