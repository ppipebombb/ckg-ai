"""Canonical ASIK `paket` (sub-section) lookup for merge post-processing.

`asik_form_mapping.json` exports the live PROD ASIK schema as a flat list of
forms. Each form has a `layanan_name` (parent — what we currently slugify as
`merged_data["sections"]` key) and a `paket_name` (sub-section card the ASIK
UI renders inside each layanan). The mapping file's `layanan_name → paket_name`
binding is incomplete (one layanan may reach several pakets in PROD that the
file doesn't list), so we resolve paket by (label + theme + gender) using the
GLOBAL label-to-paket index plus heuristic fallbacks.

Public API: `paket_for(layanan_name, label, gender) -> (paket_name, paket_slug)`.

Returns `(None, None)` when no mapping or heuristic match is found — caller
should fall back to a `"lainnya"` bucket.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from typing import Iterable

# Public type alias for caller convenience.
Paket = tuple[str | None, str | None]


# ─── Theme rules — high-precedence keyword heuristics ─────────────────────
# Applied BEFORE label-index lookup. Catches ambiguous labels that multiple
# pakets share (e.g. `Berat Badan (Kg)` is in both Laki-laki + Perempuan
# Gizi pakets). Each tuple: (regex_pattern, paket_name_template).
# Template placeholders: `{gender}` expands to "Perempuan" or "Laki-laki".

_GIZI_KEYS = (
    r"\bberat badan\b",
    r"\btinggi badan\b",
    r"\blingkar perut\b",
    r"\bindex massa tubuh\b",
    r"\bimt\b",
)
_TEKANAN_KEYS = (
    r"\btekanan darah\b",
    r"\bsistol",
    r"\bdiastol",
    r"tekanan darah tinggi",
    r"hipertensi",
)
_GULA_KEYS = (
    r"\bgula darah\b",
    r"\bgds\b",
    r"\bgdp\b",
    r"\bgd ?2\b",
    r"diabetes",
    r"kencing manis",
)
_HBA1C_KEYS = (r"hba1c", r"hb1ac")
_LIPID_KEYS = (r"kolesterol", r"cholesterol", r"\bhdl\b", r"\bldl\b", r"trigliserida")


def _matches_any(label: str, patterns: Iterable[str]) -> bool:
    low = label.lower()
    return any(re.search(p, low) for p in patterns)


def _theme_paket(label: str, gender: str | None) -> str | None:
    """Match label against high-confidence theme rules. Returns paket_name or None."""
    if _matches_any(label, _GIZI_KEYS):
        # Gender-specific Gizi paket. Default to Perempuan when unknown — both
        # variants share fields verbatim, so the slug just disambiguates.
        suffix = "Laki-laki" if gender == "Laki-laki" else "Perempuan"
        return f"Gizi (BB - TB - Lingkar Perut) {suffix}"
    if _matches_any(label, _TEKANAN_KEYS):
        return "Tekanan Darah Dewasa Lansia"
    if _matches_any(label, _GULA_KEYS):
        return "Pemeriksaan Gula Darah Dewasa Lansia"
    if _matches_any(label, _HBA1C_KEYS):
        return "Pemeriksaan Hb1AC"
    if _matches_any(label, _LIPID_KEYS):
        return "Profil Lipid"
    return None


# ─── pediatric (under-18) forms ───────────────────────────────────────────
# Under-18 ASIK forms are self-contained cards (the form IS the paket card). They
# must NOT fall through to the adult theme keywords above — a kid's "Berat Badan"
# / "Tekanan Darah Sistol" / "Gula Darah Sewaktu (GDS)" would otherwise be filed
# under an ADULT card ("Gizi (BB - TB - Lingkar Perut)", "Tekanan Darah Dewasa
# Lansia", …). Detect by the layanan (form) name and group each kid form under its
# own form-named card. Tokens are chosen to never match an adult/lansia form name.
_PEDIATRIC_LAYANAN_TOKENS = (
    "anak", "balita", "bayi", "remaja", "prasekolah", "pra sekolah",
)


def _is_pediatric_layanan(layanan_name: str | None) -> bool:
    s = (layanan_name or "").lower()
    return any(tok in s for tok in _PEDIATRIC_LAYANAN_TOKENS)


@lru_cache(maxsize=1)
def _label_index() -> dict[str, list[tuple[str, str]]]:
    """Build `{label: [(layanan_name, paket_name), ...]}` from asik_form_mapping.json.

    A label appears under as many (layanan, paket) pairs as ASIK PROD declares.
    The first call lazily loads the mapping; subsequent calls hit the cache.
    """
    data = json.loads(
        (resources.files("app.data") / "asik_form_mapping.json").read_text(
            encoding="utf-8"
        )
    )
    idx: dict[str, list[tuple[str, str]]] = {}
    for f in data.get("forms", []) or []:
        layanan = f.get("layanan_name")
        paket = f.get("paket_name")
        if not isinstance(layanan, str) or not isinstance(paket, str):
            continue
        for q in f.get("questions") or []:
            lbl = (q.get("label") or "").strip()
            if not lbl:
                continue
            idx.setdefault(lbl, []).append((layanan, paket))
    return idx


_GENDER_DROP = {
    "Perempuan": re.compile(r"Laki[- ]?laki", re.IGNORECASE),
    "Laki-laki": re.compile(r"Perempuan", re.IGNORECASE),
}


def _filter_by_gender(
    candidates: list[tuple[str, str]], gender: str | None
) -> list[tuple[str, str]]:
    if not gender or gender not in _GENDER_DROP:
        return candidates
    drop_re = _GENDER_DROP[gender]
    filtered = [(l, p) for (l, p) in candidates if not drop_re.search(p)]
    return filtered or candidates


_SLUG_NONALNUM_RE = re.compile(r"[^a-z0-9]+")


def paket_slug(paket_name: str) -> str:
    """Slugify a paket name with the same rules as form-name slugify.

    Matches `merge._slugify_form` byte-for-byte (lowercase, replace `=>` with
    ` di_atas `, strip `()/-&`, collapse non-alphanumerics to `_`).
    """
    s = paket_name.lower()
    s = s.replace("=>", " di_atas ")
    s = re.sub(r"[()\/\-&]", " ", s)
    s = _SLUG_NONALNUM_RE.sub("_", s)
    return s.strip("_")


def paket_for(layanan_name: str | None, label: str, gender: str | None = None) -> Paket:
    """Resolve `(paket_name, paket_slug)` for one (layanan, label).

    Resolution order:
      1. Theme heuristic (`_theme_paket`) — high-confidence keyword match.
      2. Global label index, filtered to candidates bound to `layanan_name`.
      3. Global label index, filtered by gender after dropping mismatching variants.
      4. First remaining candidate.
      5. `(None, None)` → caller buckets into `"lainnya"`.
    """
    if not isinstance(label, str) or not label.strip():
        return (None, None)
    label = label.strip()

    # Pediatric forms are self-contained cards — bypass the adult theme keywords
    # so a kid's BB/TB/BP/glucose lands under its own kid form, not an adult card.
    if _is_pediatric_layanan(layanan_name):
        return (layanan_name, paket_slug(layanan_name))

    themed = _theme_paket(label, gender)
    if themed is not None:
        return (themed, paket_slug(themed))

    candidates = _label_index().get(label) or []
    if not candidates:
        return (None, None)

    if layanan_name:
        bound = [(l, p) for (l, p) in candidates if l == layanan_name]
        if bound:
            chosen = _filter_by_gender(bound, gender)[0][1]
            return (chosen, paket_slug(chosen))

    chosen = _filter_by_gender(candidates, gender)[0][1]
    return (chosen, paket_slug(chosen))


LAINNYA_PAKET_NAME = "Lainnya"
LAINNYA_PAKET_SLUG = "lainnya"
