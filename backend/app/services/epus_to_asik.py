"""Deterministic EPUS → ASIK CKG form converter.

Input: decrypted ``scraped_epus_data`` dict (shape produced by the EPUS
scraper — top-level keys ``data_pasien``, ``penyakit_khusus``, ``tabs``).

Output: dict keyed by ASIK form name → field-name → value, ready to feed
into the ASIK SurveyJS payloads (one entry per ``pemeriksaan_link`` /
``FormLink`` returned by ``/api/pkg/detail-screening``).

Forms emitted are gated by:
1. Age + gender (klaster) — derived from ``data_pasien``.
2. Chronic-disease flags — read from ``tabs.Diagnosa`` and ``penyakit_khusus``.

Field-level conditional reveals (SurveyJS ``visibleIf``) are honoured by
populating the child key only when the parent answer matches the trigger.

No LLM. No network. Pure dict-in dict-out.
"""

from __future__ import annotations

import re
from typing import Any

ASIK_FormName = str
ASIK_FieldName = str
ASIK_Result = dict[ASIK_FormName, dict[ASIK_FieldName, Any]]

_DM_ICDX_PREFIXES = ("E10", "E11", "E12", "E13", "E14")
_HT_ICDX_PREFIXES = ("I10", "I11", "I12", "I13", "I15")
_LUNG_CHRONIC_ICDX_PREFIXES = ("J40", "J41", "J42", "J43", "J44", "J45", "J47")
_HEART_CHRONIC_ICDX_PREFIXES = ("I20", "I21", "I22", "I23", "I24", "I25", "I50")
_CANCER_ICDX_PREFIXES = tuple(f"C{n:02d}" for n in range(0, 98))
_TB_ICDX_PREFIXES = ("A15", "A16", "A17", "A18", "A19")
_HIV_ICDX_PREFIXES = ("B20", "B21", "B22", "B23", "B24")
_SYPH_ICDX_PREFIXES = ("A50", "A51", "A52", "A53")
_DISLIPID_ICDX_PREFIXES = ("E78",)
# Hepatitis ICDX: B16 = Hep B akut, B17.0/B18.0/B18.1 = Hep B chronic carrier.
# B17.1/B18.2 = Hep C chronic. Use prefix grouping that distinguishes B vs C
# at the .x level for chronic (B18.0/.1 = B; B18.2 = C); B16 is always B.
_HEP_B_ICDX_PREFIXES = ("B16", "B18.0", "B18.1")
_HEP_C_ICDX_PREFIXES = ("B17.1", "B18.2")


# ─── value coercion helpers ───────────────────────────────────────────────


def _yatidak(v: Any, ya: str = "Ya", tidak: str = "Tidak") -> str | None:
    """Normalise EPUS Ya/Iya/Tidak (any case) to a chosen pair."""
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("ya", "iya", "y"):
        return ya
    if s in ("tidak", "tdk", "no", "n"):
        return tidak
    return None


def _num(v: Any) -> int | float | None:
    if v is None or v == "":
        return None
    try:
        s = str(v).replace(",", ".").strip()
        return float(s) if "." in s else int(s)
    except (ValueError, TypeError):
        return None


# ─── Laboratorium tab — exam/result table reader ──────────────────────────
#
# EPUS stores ordered lab tests + numeric results in the Laboratorium tab's
# ``tables`` grid (key "Ubah Data Laboratorium" once a result is saved), NOT
# in ``fields``. Each row is
#   {"Pemeriksaan": "<PANEL> / <Test>", "Hasil": "<value>", "Satuan": …, …}.
# We index every result row by its test-name leaf — the part after the last
# "/", with EPUS's "↳ " sub-item marker stripped — → first non-empty Hasil.
#
# (2026-06-03) This tab was scraped-but-unmapped: the "Laporan Jenis
# Pertanyaan" listed Albumin Urin / Trombosit / Hb as "Tidak ada di EPUS"
# because BOTH the converter and the skill's source-side audits only walked
# ``fields``. Microalbuminuria → Albumin Urin, Trombosit, and Hb live here.
#
# Test names vary BY REGION — match an EXACT normalised leaf against the alias
# tuples below, never a substring ('hb' would grab HbsAg / HbA1c). Aliases
# verified across all 3 regions (Cipondoh / Tebet / Pekayon Jaya, 2026-06-03):
#   Hb         : "Hb (Hemoglobin)" | "Hemoglobin (HGB)" | "Hemoglobin"
#   Trombosit  : "Trombosit"       | "↳ Trombosit (PLT)"
#   Albumin Urin: "Microalbuminuria" | "Microalbuminuria kuantitatif"  (Tebet)
# A NEW region's spelling that escapes these will now be SURFACED by the
# (table-aware) audit_uncovered.py — extend the tuple when it shows up.
_LAB_ALBUMIN_URIN = ("microalbuminuria", "microalbuminuria kuantitatif")
_LAB_TROMBOSIT = ("trombosit", "trombosit (plt)")
_LAB_HEMOGLOBIN = ("hb (hemoglobin)", "hemoglobin (hgb)", "hemoglobin")


def _lab_tab(epus: dict) -> dict | None:
    tabs = epus.get("tabs") or {}
    lab = tabs.get("Laboratorium")
    if isinstance(lab, dict):
        return lab
    # tab relabelled by a region? fall back to the module slug.
    return next(
        (v for v in tabs.values()
         if isinstance(v, dict) and v.get("module") == "laboratorium"),
        None,
    )


def _lab_results(epus: dict) -> dict[str, Any]:
    """Map test-name leaf (lowercased, "↳ " stripped) → first non-empty Hasil
    from the Laboratorium result table(s). Empty dict when the tab/table is
    absent — every EPUS region degrades to ``{}`` gracefully."""
    lab = _lab_tab(epus)
    if not lab:
        return {}
    out: dict[str, Any] = {}
    for rows in (lab.get("tables") or {}).values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            name, hasil = row.get("Pemeriksaan"), row.get("Hasil")
            if not name or hasil in (None, ""):
                continue
            leaf = str(name).split("/")[-1].strip().lstrip("↳").strip().lower()
            if leaf:
                out.setdefault(leaf, hasil)
    return out


def _lab_num(results: dict[str, Any], aliases: tuple[str, ...]) -> int | float | None:
    """First numeric Hasil among ``aliases`` (EXACT normalised-leaf match —
    exact, not substring, so 'hb' never grabs HbsAg / HbA1c)."""
    for a in aliases:
        if a in results:
            n = _num(results[a])
            if n is not None:
                return n
    return None


def _smoking_to_asik(v: Any) -> str | None:
    """EPUS Faktor Risiko.Merokok → ASIK PPOK Q1 (uses ``Iya``)."""
    if v is None:
        return None
    s = str(v).strip().lower()
    if "tidak" in s:
        return "Tidak"
    if "aktif" in s or "merokok" in s or "perokok" in s:
        return "Iya"
    return None


def _years_from_umur(umur: str | None) -> int | None:
    """Extract years from EPUS umur strings.

    Handles multiple EPUS variants: ``"58 Tahun 1 Bulan 15 Hari"`` /
    ``"58 Thn 6 Bln 0 Hr"`` / ``"58 thn"``.
    """
    if not umur:
        return None
    m = re.match(r"\s*(\d+)\s*(?:Tahun|Thn|T|Y)", umur, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _gender_norm(g: str | None) -> str | None:
    """EPUS gender → canonical (``Perempuan`` / ``Laki-Laki``).

    Canonical matches live ASIK form values (verified 2026-05-11 against
    `detail_data.data_individu.Jenis Kelamin` and the Mandiri form dropdown
    options for Demografi). Accepts: ``P`` / ``L`` / ``Perempuan`` /
    ``Laki-Laki`` / ``Laki-laki`` / ``Wanita`` / ``Pria``.
    """
    if not g:
        return None
    s = g.strip().lower()
    if s in ("p", "pr") or s.startswith("pere") or s.startswith("wani"):
        return "Perempuan"
    if s in ("l", "lk") or s.startswith("laki") or s.startswith("pria"):
        return "Laki-Laki"
    return None


_INDO_MONTHS = (
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
)


def _dmy_to_indo(s: str | None) -> str | None:
    """Convert ``08-06-1974`` (or ``8/6/1974``) → ``8 Juni 1974``.

    Returns the cleaned input string when month is out of range so
    downstream callers do not silently drop a partially-valid date.
    """
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    m = re.match(r"^\s*(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})\s*$", s)
    if not m:
        return s or None
    d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
    if not (1 <= mo <= 12):
        return s
    if len(y) == 2:
        y = ("19" if int(y) >= 30 else "20") + y
    return f"{d} {_INDO_MONTHS[mo]} {y}"


def _clean_text(v: Any) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _screen_yn(v: Any, ya_kw: str) -> str | None:
    """Skrining-klaster free-label answer → ASIK 'Ya'/'Tidak'. A leading 'tidak'
    wins (so 'Tidak memiliki …' / 'Tidak pernah' → 'Tidak'); otherwise a positive
    keyword (`ya_kw`, e.g. 'memiliki' / 'merokok') → 'Ya'. None when neither
    matches (leave the ASIK field to its module/fallback value)."""
    s = (_clean_text(v) or "").lower()
    if not s:
        return None
    if s.startswith("tidak"):
        return "Tidak"
    if s == "ya" or ya_kw in s:
        return "Ya"
    return None


def _visus_5level(left: Any, right: Any) -> str | None:
    """L+R Mata Kanan/Kiri Y/N → 5-level visus enum (PROD 2026-Berubah).

    EPUS only has binary Y/N per side, so we can confidently emit only
    the Normal bucket. Any non-Tidak side (gangguan present) → null and
    let ASIK clerk pick the precise level manually.
    """
    lv = _yatidak(left)
    rv = _yatidak(right)
    if lv is None and rv is None:
        return None
    if lv == "Tidak" and rv == "Tidak":
        return "Normal (visus 6/6 - 6/12)"
    return None  # ambiguous degree of impairment — clerk fills


def _pinhole_from_visus(left: Any, right: Any) -> str | None:
    """Pemeriksaan Pinhole — only emitted when visus is abnormal.

    EPUS doesn't capture pinhole follow-up. When either eye flags
    refraksi/visus, ASIK protocol asks pinhole next; we cannot derive
    so return null. Kept as a hook for future EPUS field add.
    """
    return None


def _gds_bucket(value: Any) -> str | None:
    """GDS / GDP / 2hPP → ASIK gula darah enum (4-level).

    Enum: ``Normal`` / ``Hipoglikemi`` / ``Prediabetes`` / ``Hiperglikemi``.
    Cutoffs from Kemkes pedoman skrining DM dewasa:
    - Hipoglikemi: <70
    - Normal: 70-139
    - Prediabetes: 140-199
    - Hiperglikemi: >=200
    """
    v = _num(value)
    if v is None:
        return None
    f = float(v)
    if f < 70:
        return "Hipoglikemi"
    if f < 140:
        return "Normal"
    if f < 200:
        return "Prediabetes"
    return "Hiperglikemi"


def _status_perkawinan(v: Any) -> str | None:
    """EPUS Status Perkawinan → ASIK Demografi enum.

    ASIK enum (live form 2026-05-11): ``Belum Menikah`` / ``Menikah`` /
    ``Cerai Hidup`` / ``Cerai Mati``.
    EPUS values seen in PKPR: ``Belum Menikah``, ``Menikah``, ``Janda/Duda``;
    legacy data_pasien used ``Kawin`` / ``Belum Kawin`` / ``Cerai Hidup`` /
    ``Cerai Mati``. ``Janda/Duda`` maps to ``Cerai Mati`` (widow/widower —
    spouse-death is the dominant cultural interpretation; ASIK has no
    "Janda/Duda" option so we collapse).
    """
    if not v:
        return None
    s = str(v).strip().lower()
    if s in ("kawin", "menikah"):
        return "Menikah"
    if s in ("belum kawin", "belum menikah"):
        return "Belum Menikah"
    if s == "cerai hidup":
        return "Cerai Hidup"
    if s == "cerai mati":
        return "Cerai Mati"
    if s in ("janda/duda", "janda", "duda"):
        return "Cerai Mati"
    return None


def _pkpr_field(epus: dict, key: str) -> Any:
    """Look up a PKPR field across both sub-sections.

    EPUS renders PKPR under either ``Buat Baru PKPR`` (new record path) or
    ``Ubah Data PKPR`` (existing record path). Most Kota Bekasi patients use
    Buat Baru, but Ubah Data is used for patients with prior PKPR records.
    Try Buat Baru first (more common), fall back to Ubah Data.
    """
    pkpr_fields = (
        ((epus.get("tabs") or {}).get("PKPR") or {}).get("fields") or {}
    )
    for sub in ("Buat Baru PKPR", "Ubah Data PKPR"):
        section = pkpr_fields.get(sub) or {}
        if isinstance(section, dict) and key in section and section[key] not in (None, ""):
            return section[key]
    return None


def _visus_pendengaran(left: Any, right: Any, *, normal: str, curiga: str) -> str | None:
    """OR-union of L+R EPUS PTM Gangguan answers → ASIK trinary.

    Either side ``Ya`` → ``curiga``. Both ``Tidak`` → ``normal``. All blank → None.
    """
    lv = _yatidak(left)
    rv = _yatidak(right)
    if lv is None and rv is None:
        return None
    if lv == "Ya" or rv == "Ya":
        return curiga
    return normal


# ─── disease detection ────────────────────────────────────────────────────


def _icdx_from_ptm_diagnosa(epus: dict) -> list[str]:
    """Parse free-text PTM.Diagnosa.Diagnosa 1/2/3 for ICDX codes.

    Format observed: ``"I10 - Essential (primary) hypertension"``. 81/999
    patients in the live DB have PTM Diagnosa filled but ``penyakit_khusus``
    empty — without this fallback their clinical flags would be missed.
    """
    diag = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get("Diagnosa")
        or {}
    )
    codes: list[str] = []
    for k in ("Diagnosa 1", "Diagnosa 2", "Diagnosa 3"):
        s = diag.get(k)
        if not s:
            continue
        m = re.match(r"\s*([A-Z]\d{2}(?:\.\d+)?)\b", str(s))
        if m:
            codes.append(m.group(1).upper())
    return codes


def _detect_chronic_flags(epus: dict) -> dict[str, dict[str, bool]]:
    """Two-tier disease detection.

    Returns ``{"self_report": {...}, "clinical": {...}}``.

    - ``self_report`` reflects the patient's own answer in EPUS Riwayat PTM
      Diri Sendiri — this is what ASIK's *Apakah Anda pernah dinyatakan…?*
      questions are asking, so it drives the parent radios.
    - ``clinical`` is the wider OR-union (Riwayat ∪ Diagnosa.Tandai Penyakit
      Kronis ∪ ICDX prefix scan in ``penyakit_khusus``). It drives form
      *gating* — EKG/lipid panel only appear for known HT/DM patients —
      but **never overrides the self-report radios**, because patients
      routinely deny diagnoses they have on paper (the comparator on
      32 matched records confirmed this).
    """
    tabs = epus.get("tabs") or {}
    diag = (tabs.get("Diagnosa") or {}).get("fields") or {}
    chronic_marks = (
        (diag.get("Buat Baru Diagnosa") or {}).get("Tandai Penyakit Kronis") or {}
    )
    riwayat_diri = (
        (tabs.get("PTM") or {}).get("fields", {}).get("Riwayat PTM pada Diri Sendiri")
        or {}
    )
    icdx_list = [
        (item.get("ICDX") or "").upper() for item in epus.get("penyakit_khusus") or []
    ] + _icdx_from_ptm_diagnosa(epus)

    def _icdx_any(prefixes: tuple[str, ...]) -> bool:
        return any(code.startswith(prefixes) for code in icdx_list if code)

    self_report = {
        "diabetes": _yatidak(riwayat_diri.get("Penyakit Diabetes")) == "Ya",
        "hipertensi": _yatidak(riwayat_diri.get("Penyakit Hipertensi")) == "Ya",
        "jantung_kronis": _yatidak(riwayat_diri.get("Penyakit Jantung")) == "Ya",
        "paru_kronis": _yatidak(riwayat_diri.get("Penyakit Asma")) == "Ya",
        "kanker": _yatidak(riwayat_diri.get("Penyakit Kanker")) == "Ya",
        "stroke": _yatidak(riwayat_diri.get("Penyakit Stroke")) == "Ya",
        "dislipidemia": _yatidak(riwayat_diri.get("Kolesterol Tinggi")) == "Ya",
    }
    clinical = {
        "diabetes": (
            self_report["diabetes"]
            or bool(chronic_marks.get("Diabetes Mellitus"))
            or _icdx_any(_DM_ICDX_PREFIXES)
        ),
        "hipertensi": (
            self_report["hipertensi"]
            or bool(chronic_marks.get("Hipertensi"))
            or _icdx_any(_HT_ICDX_PREFIXES)
        ),
        "jantung_kronis": (
            self_report["jantung_kronis"]
            or bool(chronic_marks.get("Penyakit Jantung Kronis"))
            or _icdx_any(_HEART_CHRONIC_ICDX_PREFIXES)
        ),
        "paru_kronis": (
            self_report["paru_kronis"]
            or bool(chronic_marks.get("Penyakit Paru Kronis"))
            or _icdx_any(_LUNG_CHRONIC_ICDX_PREFIXES)
        ),
        "kanker": (
            self_report["kanker"]
            or bool(chronic_marks.get("Kanker"))
            or _icdx_any(_CANCER_ICDX_PREFIXES)
        ),
        "stroke": self_report["stroke"] or bool(chronic_marks.get("Stroke")),
        "dislipidemia": (
            self_report["dislipidemia"]
            or bool(chronic_marks.get("Kolesterol Tinggi"))
            or bool(chronic_marks.get("Dislipidemia"))
            or _icdx_any(_DISLIPID_ICDX_PREFIXES)
        ),
        "tb": _icdx_any(_TB_ICDX_PREFIXES),
        "hiv": _icdx_any(_HIV_ICDX_PREFIXES),
        "syphilis": _icdx_any(_SYPH_ICDX_PREFIXES),
        "hep_b": _icdx_any(_HEP_B_ICDX_PREFIXES),
        "hep_c": _icdx_any(_HEP_C_ICDX_PREFIXES),
    }
    return {"self_report": self_report, "clinical": clinical}


# ─── per-form mappers ─────────────────────────────────────────────────────


def _map_tekanan_darah_dewasa_lansia(
    epus: dict, flags: dict[str, dict[str, bool]]
) -> dict[str, Any]:
    """ASIK ``Tekanan Darah Dewasa Lansia`` (live form).

    Live fields (audit 2026-04-29 + live recon 2026-05-11):
    - HT parent radio
    - Tekanan Darah Sistolik / diastolik
    - Tekanan Darah Sistolik Ke-2 / diastolik ke-2 (no EPUS source)
    - Sudah Berapa Bulan Anda Didiagnosis Hipertensi (conditional on HT=Ya)

    Sources EPUS Anamnesa.Periksa Fisik (Sistole/Diastole) with PTM.Tekanan
    Darah & IMT as fallback.
    """
    fisik = (
        ((epus.get("tabs") or {}).get("Anamnesa") or {}).get("fields", {}).get(
            "Periksa Fisik"
        )
        or {}
    )
    ptm_imt = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get(
            "Tekanan Darah & IMT"
        )
        or {}
    )
    sistole = _num(fisik.get("Sistole")) or _num(ptm_imt.get("Sistole"))
    diastole = _num(fisik.get("Diastole")) or _num(ptm_imt.get("Diastole"))
    # Parent radio mirrors the literal Riwayat PTM field (the question ASIK
    # asks). Clinical-union flags are reserved for form gating per the
    # _detect_chronic_flags docstring — using them here would contradict the
    # EPUS_BREADCRUMBS pointer (single Riwayat field) and surface as a fake
    # conflict in /merged-preview whenever the patient denied a diagnosis
    # they have on paper.
    ht_parent = "Ya" if flags["self_report"]["hipertensi"] else "Tidak"
    out: dict[str, Any] = {
        "Apakah Anda pernah dinyatakan tekanan darah tinggi?": ht_parent,
        "Tekanan Darah Sistolik": sistole,
        "Tekanan darah diastolik": diastole,
        "Tekanan Darah Sistolik Ke-2": None,
        "Tekanan darah diastolik ke-2": None,
    }
    if ht_parent == "Ya":
        # EPUS PTM has no months-since-diagnosis field. Emit None so the
        # field appears in /asik-preview as "needs manual fill".
        out[
            "Sudah Berapa Bulan Anda Didiagnosis Hipertensi Oleh Dokter? "
            "Isi Total Bulan Sejak didiagnosis dokter hingga saat ini, "
            "misal didiagnosis 1 tahun yang lalu = 12, dst"
        ] = None
    return out


def _map_pemeriksaan_gula_darah_dewasa_lansia(
    epus: dict, flags: dict[str, dict[str, bool]]
) -> dict[str, Any]:
    """ASIK ``Pemeriksaan Gula Darah Dewasa Lansia`` (live form).

    Live fields (6 Q, GDS 2 conditional on GDS 1 ≥140 + no prior DM):
    - DM parent radio
    - GDS / GDS 2 / GDP / GD 2 Jam PP
    - Sudah Berapa Bulan DM (conditional on DM=Ya)

    EPUS source: PTM.Pemeriksaan (Pemeriksaan Gula / Pemeriksaan Gula Darah
    Puasa / Pemeriksaan Gula Darah 2 Jam PP).
    """
    pem = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get("Pemeriksaan")
        or {}
    )
    gdp = _num(pem.get("Pemeriksaan Gula Darah Puasa"))
    gd_general = _num(pem.get("Pemeriksaan Gula"))
    # ``Pemeriksaan Gula`` is the generic field; treat it as GDS only when
    # the dedicated GDP/2hPP fields are empty, otherwise it duplicates GDP.
    gds = gd_general if (gd_general is not None and gdp is None) else None
    gd2pp = _num(pem.get("Pemeriksaan Gula Darah 2 Jam PP"))
    # Parent radio mirrors literal Riwayat PTM (see HT parent above).
    dm_parent = "Ya" if flags["self_report"]["diabetes"] else "Tidak"
    out: dict[str, Any] = {
        "Apakah Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?": dm_parent,
        "Gula Darah Sewaktu (GDS) (mg/dl)": gds,
        # GDS 2 has no EPUS source — only filled by nakes when GDS1 ≥140 and
        # patient not yet diagnosed. Leave None to avoid the previous bug
        # where merge copied GDS1 into GDS2 (see merged2.json regression).
        "Gula Darah Sewaktu Kedua (GDS 2). Lakukan jika hasil GDS 1 Prediabetes (≥140-199mg/dl) atau Hiperglikemia (≥200mg/dl) dan BELUM PERNAH didiagnosis Diabetes": None,
        "Gula Darah Puasa (GDP) (mg/dl)": gdp,
        "Gula Darah 2 Jam PP (mg/dl)": gd2pp,
    }
    if dm_parent == "Ya":
        out[
            "Sudah Berapa Bulan Anda Didiagnosis Diabetes Melitus Oleh Dokter? "
            "Isi Total Bulan Sejak didiagnosis dokter hingga saat ini, "
            "misal didiagnosis 1 tahun yang lalu = 12, dst"
        ] = None
    return out


def _map_gizi_bb_tb_lp(epus: dict, gender: str) -> tuple[str, dict[str, Any]]:
    """ASIK ``Gizi (BB - TB - Lingkar Perut) <Laki-laki|Perempuan>`` (live form).

    Live fields (3 Q only): BB, TB, LP. No IMT bucket — ASIK computes that
    server-side. Lingkar Perut also has no "Normal / Obesitas Sentral" enum.

    EPUS source: Anamnesa.Periksa Fisik with PTM.Tekanan Darah & IMT as
    fallback for BB/TB; PTM.Pemeriksaan as fallback for LP.
    """
    fisik = (
        ((epus.get("tabs") or {}).get("Anamnesa") or {}).get("fields", {}).get(
            "Periksa Fisik"
        )
        or {}
    )
    pem = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get("Pemeriksaan")
        or {}
    )
    ptm_imt = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get(
            "Tekanan Darah & IMT"
        )
        or {}
    )
    bb = _num(fisik.get("Berat Badan")) or _num(ptm_imt.get("Berat Badan"))
    tb = _num(fisik.get("Tinggi Badan")) or _num(ptm_imt.get("Tinggi Badan"))
    lp = _num(fisik.get("Lingkar Perut")) or _num(pem.get("Lingkar Perut"))
    # ASIK form name uses lowercase "Laki-laki" (verified live 2026-05-11).
    form_name = "Gizi (BB - TB - Lingkar Perut) " + (
        "Perempuan" if gender == "Perempuan" else "Laki-laki"
    )
    return form_name, {
        "Berat Badan (Kg)": bb,
        "Pengukuran Tinggi Badan (cm)": tb,
        "Pengukuran Lingkar Perut": lp,
    }


def _map_ppok_puma(epus: dict, years: int | None = None) -> dict[str, Any]:
    fr = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get("Faktor Risiko")
        or {}
    )
    parent = _smoking_to_asik(fr.get("Merokok"))
    out: dict[str, Any] = {
        "Apakah anda sedang/mempunyai riwayat merokok?": parent,
        "Apakah Anda pernah merasa napas pendek ketika berjalan lebih cepat pada jalan yang datar atau pada jalan yang sedikit menanjak?": _yatidak(
            fr.get(
                "Apakah Anda pernah merasa napas pendek ketika Anda berjalan lebih cepat "
                "pada jalan yang datar atau pada jalan yang sedikit menanjak?"
            )
        ),
        "Apakah Anda biasanya mempunyai dahak yang berasal dari paru atau kesulitan mengeluarkan dahak saat Anda sedang tidak menderita selesma/flu?": _yatidak(
            fr.get(
                "Apakah Anda biasanya mempunyai dahak yang berasal dari paru atau "
                "kesulitan mengeluarkan dahak saat Anda sedang tidak menderita selesma/flu?"
            )
        ),
        "Apakah Anda biasanya batuk saat sedang tidak menderita selesma/flu?": _yatidak(
            fr.get("Apakah Anda biasanya batuk saat Anda sedang tidak menderita selesma/flu?")
        ),
        "Apakah Dokter atau tenaga medis lainnya pernah meminta Anda untuk melakukan pemeriksaan spirometri atau peak flow meter (meniup ke dalam suatu alat) untuk mengetahui fungsi paru?": _yatidak(
            fr.get(
                "Apakah Dokter atau tenaga medis lainnya pernah meminta Anda untuk "
                "melakukan pemeriksaan spirometri atau peak flow meter (meniup ke dalam "
                "suatu alat) untuk mengetahui fungsi paru anda?"
            )
        ),
    }
    if parent == "Iya":
        # Prefer EPUS-computed `Pack Year` directly; fall back to manual
        # rokok×lama calculation when that field is null.
        packs: float | None = None
        epus_pack_year = _num(fr.get("Pack Year"))
        if epus_pack_year is not None:
            packs = float(epus_pack_year)
        else:
            rokok = _num(fr.get("Rata-rata Jumlah Rokok"))
            lama = _num(fr.get("Lama Merokok dalam Tahun"))
            if rokok and lama:
                packs = (float(rokok) / 20.0) * float(lama)  # 1 bungkus = 20 batang
        bucket: str | None = None
        if packs is not None:
            if packs < 20:
                bucket = "<20 bungkus per tahun"
            elif packs <= 30:
                bucket = "20-30 bungkus per tahun"
            else:
                bucket = ">30 bungkus per tahun"
        out["Jika Perokok Aktif, berapa bungkus per tahun?"] = bucket

    # Live form (audit 2026-04-29 + asik_layanan_fields) does not include
    # `Usia - skor PUMA` or `Hasil Skor Kuesioner PUMA`. Both were CSV
    # spec inventions absent from live ASIK — do not emit.
    return out


def _map_demografi(epus: dict, gender: str, years: int) -> tuple[str, dict[str, Any]]:
    pasien = epus.get("data_pasien") or {}
    fisik = (
        ((epus.get("tabs") or {}).get("Anamnesa") or {}).get("fields", {}).get(
            "Periksa Fisik"
        )
        or {}
    )
    perkawinan = _status_perkawinan(
        pasien.get("Status Perkawinan")
        or _pkpr_field(epus, "Status Perkawinan")
    )
    disabilitas = _disabilitas(epus)
    if years >= 60:
        out_lansia: dict[str, Any] = {}
        if perkawinan is not None:
            out_lansia["Status Perkawinan"] = perkawinan
        if disabilitas is not None:
            out_lansia["Apakah Anda penyandang disabilitas?"] = disabilitas
        return "Demografi Lansia", out_lansia
    form_name = (
        "Demografi Dewasa Perempuan"
        if gender == "Perempuan"
        else "Demografi Dewasa Laki-Laki"
    )
    out: dict[str, Any] = {}
    if perkawinan is not None:
        out["Status Perkawinan"] = perkawinan
    if gender == "Perempuan":
        out["Apakah Anda sedang hamil?"] = _yatidak(fisik.get("Status Hamil"))
    if disabilitas is not None:
        out["Apakah Anda penyandang disabilitas?"] = disabilitas
    return form_name, out


def _disabilitas(epus: dict) -> str | None:
    """Derive ASIK Demografi `Apakah Anda penyandang disabilitas?` from PKPR.

    ASIK enum (live form 2026-05-11): ``Non disabilitas`` / ``Penyandang disabilitas``.

    EPUS Kota Bekasi PKPR carries `15. Disabilitas Mental` + `18. Disabilitas
    Fisik` Ya/Tidak radios. These appear under either `Buat Baru PKPR`
    (common path) or `Ubah Data PKPR` (used when patient has a prior PKPR
    record — observed for NIK 3275055503020011). N→1 OR logic: either ``Ya``
    → `Penyandang disabilitas`; both ``Tidak`` → `Non disabilitas`; both
    null → None (leave for ASIK manual).
    """
    mental = _yatidak(_pkpr_field(epus, "15. Disabilitas Mental"))
    fisik = _yatidak(_pkpr_field(epus, "18. Disabilitas Fisik"))
    if mental is None and fisik is None:
        return None
    if mental == "Ya" or fisik == "Ya":
        return "Penyandang disabilitas"
    return "Non disabilitas"


def _map_telinga_mata(years: int) -> str:
    return (
        "Skrining Telinga dan Mata (=>40 tahun)"
        if years >= 40
        else "Skrining Telinga dan Mata (18-39 tahun)"
    )


def _map_iva_sadanis(epus: dict, gender: str, years: int) -> dict[str, dict[str, Any]]:
    """IVA / Inspekulo / Kanker Payudara — perempuan, age >= 30.

    Live forms (audit 2026-04-29):
    - ``Pemeriksaan Inspekulo dan IVA`` (2 Q): Pemeriksaan Inspekulo
      (Normal/Curiga kanker), Pemeriksaan IVA (Negatif/Positif).
    - ``Skrining Kanker Payudara`` (1 Q): ``Pemeriksaan yang dilakukan``
      (dropdown). Live form does **not** include ``Hasil pemeriksaan
      SADANIS`` — drop that emission.

    EPUS source: PTM.Pemeriksaan IVA dan Sadanis.Hasil IVA + Hasil Sanadis.
    """
    if gender != "Perempuan" or years < 30:
        return {}
    iva_block = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get(
            "Pemeriksaan IVA dan Sadanis"
        )
        or {}
    )
    out: dict[str, dict[str, Any]] = {}

    hasil_iva = iva_block.get("Hasil IVA")
    if hasil_iva:
        s = str(hasil_iva).strip().lower()
        iva_q2: str | None = None
        inspekulo_q1: str | None = None
        if "negat" in s:
            iva_q2 = "Negatif"
            inspekulo_q1 = "Normal"
        elif "posit" in s or "curiga" in s:
            iva_q2 = "Positif"
            inspekulo_q1 = "Curiga kanker"
        inspekulo_out: dict[str, Any] = {}
        if inspekulo_q1:
            inspekulo_out["Pemeriksaan Inspekulo"] = inspekulo_q1
        if iva_q2:
            inspekulo_out["Pemeriksaan Inspeksi Visual Asam Asetat (IVA)"] = iva_q2
        if inspekulo_out:
            out["Pemeriksaan Inspekulo dan IVA"] = inspekulo_out

    hasil_sanadis = iva_block.get("Hasil Sanadis")
    if hasil_sanadis:
        # Live form only has the "Pemeriksaan yang dilakukan" dropdown.
        # EPUS only does sadanis-style palpation, so always emit SADANIS.
        out["Skrining Kanker Payudara"] = {"Pemeriksaan yang dilakukan": "SADANIS"}

    return out


def _map_telinga_mata_fields(epus: dict, *, include_pupil: bool = False) -> dict[str, Any]:
    """EPUS PTM Gangguan Penglihatan/Pendengaran → live ASIK form fields.

    Live forms (audit 2026-04-29):
    - ``Skrining Telinga dan Mata (18-39 tahun)`` (4 Q): serumen, infeksi
      telinga, tajam pendengaran, tajam penglihatan.
    - ``Skrining Telinga dan Mata (=>40 tahun)`` (5 Q): adds ``Hasil
      pemeriksaan pupil``. Notably **no** Pinhole / penala / snellen on
      Bekasi cluster — those CSV xlsx spec fields are not on live forms.

    EPUS Gangguan Penglihatan exposes Refraksi (sight) + Katarak (lens)
    sub-blocks. EPUS Gangguan Pendengaran exposes Serumen, Congek (OMSK),
    Tuli Kongenital sub-blocks.
    """
    ptm = (epus.get("tabs") or {}).get("PTM", {}).get("fields", {})
    peng = ptm.get("Gangguan Penglihatan") or {}
    deng = ptm.get("Gangguan Pendengaran") or {}
    out: dict[str, Any] = {}

    # Tajam penglihatan — derive from Refraksi (sight problem). Only the
    # Normal bucket is safely derivable from EPUS binary Y/N per side.
    visus = _visus_5level(
        peng.get("Refraksi Mata Kiri"),
        peng.get("Refraksi Mata Kanan"),
    )
    if visus is not None:
        # Map the 5-level Normal bucket to the live 2-option enum.
        out["Apa hasil skrining tajam penglihatan?"] = "Normal (visus 6/6 - 6/12)"

    # Tajam pendengaran — OR-union of Congek + Tuli Kongenital both sides.
    # Live enum: Normal / Curiga gangguan pendengaran.
    penala_inputs = [
        deng.get("Congek Telinga Kiri"),
        deng.get("Congek Telinga Kanan"),
        deng.get("Tuli Kongenital Telinga Kiri"),
        deng.get("Tuli Kongenital Telinga Kanan"),
    ]
    penala_norms = [_yatidak(v) for v in penala_inputs]
    if any(v is not None for v in penala_norms):
        if any(v == "Ya" for v in penala_norms):
            out["Hasil pemeriksaan tajam pendengaran"] = "Curiga gangguan pendengaran"
        elif all(v == "Tidak" for v in penala_norms if v is not None):
            out["Hasil pemeriksaan tajam pendengaran"] = "Normal"

    # Serumen impaksi — OR-union of Serumen Telinga Kiri/Kanan (when EPUS
    # captures them via the Gangguan Pendengaran sub-block).
    serumen = _visus_pendengaran(
        deng.get("Serumen Telinga Kiri"),
        deng.get("Serumen Telinga Kanan"),
        normal="Tidak ada serumen impaksi",
        curiga="Ada serumen impaksi",
    )
    if serumen is not None:
        out["Apa Hasil Pemeriksaan Telinga Luar (serumen impaksi)?"] = serumen

    # Infeksi telinga — derive from Congek (OMSK = chronic ear infection).
    # Live field is a free-text dropdown; emit a defensive value matching
    # the sample observed ("Tidak ada infeksi telinga" / clerk-confirmable).
    congek_norms = [
        _yatidak(deng.get("Congek Telinga Kiri")),
        _yatidak(deng.get("Congek Telinga Kanan")),
    ]
    if any(v is not None for v in congek_norms):
        if any(v == "Ya" for v in congek_norms):
            # Live infeksi-telinga dropdown options are not enumerated in
            # audit — emit None to surface field for manual fill.
            out["Apa Hasil Pemeriksaan Telinga Luar (infeksi telinga)?"] = None
        else:
            out["Apa Hasil Pemeriksaan Telinga Luar (infeksi telinga)?"] = (
                "Tidak ada infeksi telinga"
            )

    if include_pupil:
        # Katarak (lens opacity) → pupil result. Live enum: Normal /
        # Curiga Katarak.
        pupil = _visus_pendengaran(
            peng.get("Katarak Mata Kiri"),
            peng.get("Katarak Mata Kanan"),
            normal="Normal",
            curiga="Curiga Katarak",
        )
        if pupil is not None:
            out["Hasil pemeriksaan pupil"] = pupil

    return out


_BATUK_RE = re.compile(r"\bbatuk\w*", re.IGNORECASE)
_NEGATED_BATUK_RE = re.compile(r"\b(tidak|tdk|tanpa|tak)\s+(ada\s+)?batuk\w*", re.IGNORECASE)


def _lama_sakit_days(v: Any) -> int | None:
    """Convert EPUS ``Anamnesa.Lama Sakit`` dict {tahun,bulan,hari} → total days.

    Returns None when the dict is missing/malformed. Months → 30 days,
    years → 365 days (close enough for the 2-week TB threshold).
    """
    if not isinstance(v, dict):
        return None
    try:
        y = int(str(v.get("tahun") or 0))
        m = int(str(v.get("bulan") or 0))
        d = int(str(v.get("hari") or 0))
    except (TypeError, ValueError):
        return None
    return y * 365 + m * 30 + d


def _cough_duration(epus: dict, flags: dict[str, dict[str, bool]]) -> str | None:
    """ASIK cough question ternary enum.

    Priority:
    1. TB ICDx → ``Ya, lebih dari 2 minggu`` (clinical-coded TB implies chronic cough).
    2. Keluhan Utama contains "batuk" (and not "tidak/tdk batuk"):
       - Lama Sakit ≥ 14 days → ``Ya, lebih dari 2 minggu``
       - Lama Sakit < 14 days → ``Ya, kurang dari 2 minggu``
       - Lama Sakit unknown   → ``Ya, lebih dari 2 minggu`` (conservative;
         puskesmas can downgrade during sync confirmation if needed)
    3. Keluhan Utama present but no "batuk" mention → ``Tidak batuk``.
    4. Keluhan Utama missing → None (let ASIK clerk fill).
    """
    if flags["clinical"].get("tb"):
        return "Ya, lebih dari 2 minggu"
    ana = (
        ((epus.get("tabs") or {}).get("Anamnesa") or {}).get("fields") or {}
    ).get("Anamnesa") or {}
    keluhan = ana.get("Keluhan Utama")
    if not keluhan:
        return None
    text = str(keluhan)
    has_batuk = bool(_BATUK_RE.search(text)) and not _NEGATED_BATUK_RE.search(text)
    if not has_batuk:
        return "Tidak batuk"
    days = _lama_sakit_days(ana.get("Lama Sakit"))
    if days is None or days >= 14:
        return "Ya, lebih dari 2 minggu"
    return "Ya, kurang dari 2 minggu"


def _map_faktor_risiko_tb(
    epus: dict, flags: dict[str, dict[str, bool]]
) -> dict[str, dict[str, Any]]:
    """ASIK TB risk forms — same cough Q on two live forms.

    Live forms (audit 2026-04-29):
    - ``Faktor Risiko TB - Dewasa & Lansia`` (1 Q): cough duration.
    - ``Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)`` (6 Q): same
      cough Q + 5 ASIK-only Q (radiografi, BB turun, demam, berkeringat,
      kelenjar — no EPUS source).

    EPUS source: cough duration via ``_cough_duration`` (TB ICDx +
    Anamnesa.Keluhan Utama + Lama Sakit). Emit to both forms when present.
    """
    cough = _cough_duration(epus, flags)
    if cough is None:
        return {}
    cough_q = (
        "Apakah Anda pernah atau sedang mengalami batuk yang tidak sembuh-sembuh?"
    )
    return {
        "Faktor Risiko TB - Dewasa & Lansia": {cough_q: cough},
        "Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)": {cough_q: cough},
    }


def _map_perilaku_merokok(epus: dict) -> dict[str, Any]:
    """ASIK ``Perilaku Merokok`` (live form, 2 Q only — audit 2026-04-29).

    Live fields:
    - ``Apakah Anda merokok dalam setahun terakhir ini?`` (Ya/Tidak)
    - ``Apakah Anda terpapar asap rokok atau menghirup asap rokok dari orang
      lain dalam sebulan terakhir?`` (Ya/Tidak) — no EPUS source.

    The dewasa-lansia CSV xlsx spec with 9 Q (Sudah berapa tahun, batang
    per hari, Brinkman, etc.) is **not** on live forms — drop those.
    """
    fr = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get("Faktor Risiko")
        or {}
    )
    val = fr.get("Merokok")
    if val is None:
        return {}
    s = str(val).strip().lower()
    is_active = "aktif" in s or s == "merokok" or s == "perokok"
    is_non = (
        ("tidak" in s) or ("bukan" in s) or s.startswith("non") or "non-perokok" in s
    )
    if is_active:
        return {"Apakah Anda merokok dalam setahun terakhir ini?": "Ya"}
    if is_non:
        return {"Apakah Anda merokok dalam setahun terakhir ini?": "Tidak"}
    # Ex-smoker — current Q asks specifically "dalam setahun terakhir";
    # safer to mark Tidak (ex-smoker did not smoke in last year).
    if ("eks" in s) or ("mantan" in s) or ("pernah" in s and "tidak" not in s):
        return {"Apakah Anda merokok dalam setahun terakhir ini?": "Tidak"}
    return {}


def _map_hiv(flags: dict[str, dict[str, bool]], epus: dict) -> dict[str, Any]:
    """ASIK Pemeriksaan HIV (FRM000188).

    Live enum: ``Reaktif`` / ``Non Reaktif``. Source priority:
    1. ICDX B20-B24 → ``Reaktif`` (clinical-coded HIV diagnosis).
    2. EPUS Konseling HIV tab Hasil field → value-map.
    3. else null.
    """
    if flags["clinical"].get("hiv"):
        return {"Hasil Pemeriksaan Rapid Test HIV": "Reaktif"}
    konseling = (
        ((epus.get("tabs") or {}).get("Konseling HIV") or {})
        .get("fields", {}).get("Konseling Pra Tes Isikan bila dilakukan konseling(KTS)")
        or {}
    )
    hasil = konseling.get("Hasil")
    if hasil:
        s = str(hasil).strip().lower()
        if "reaktif" in s and "non" not in s:
            return {"Hasil Pemeriksaan Rapid Test HIV": "Reaktif"}
        if "non" in s and "reaktif" in s:
            return {"Hasil Pemeriksaan Rapid Test HIV": "Non Reaktif"}
    return {}


def _map_hepatitis(flags: dict[str, dict[str, bool]]) -> dict[str, Any]:
    """ASIK ``Pemeriksaan Hepatitis``.

    Live enum: ``Reaktif`` / ``Non Reaktif`` per result. Source: ICDX B16 /
    B18.0 / B18.1 → Hep B reactive; B17.1 / B18.2 → Hep C reactive. Without
    any hepatitis ICDX, leave both null (ASIK Nakes fills manually after
    rapid test).
    """
    out: dict[str, Any] = {}
    if flags["clinical"].get("hep_b"):
        out["Hasil Rapid Test Hepatitis B"] = "Reaktif"
    if flags["clinical"].get("hep_c"):
        out["Hasil Rapid Test Hepatitis C"] = "Reaktif"
    return out


def _map_sifilis(flags: dict[str, dict[str, bool]]) -> dict[str, Any]:
    """ASIK Pemeriksaan Sifilis (FRM000191).

    ICDX A50-A53 → ``Reaktif``. Else null (puskesmas Nakes fills manually).
    """
    if flags["clinical"].get("syphilis"):
        return {"Hasil Pemeriksaan Rapid Test Sifilis": "Reaktif"}
    return {}


# EPUS ``skriningkankerparu`` field → live ASIK question label. Used by the
# klaster-primary override (coded radios; recon value→label 2026-08-12).
_KP_LABELS = {
    "diagnosis_kanker": "Apakah pernah didiagnosis/menderita kanker?",
    "keluarga_kanker": (
        "Apakah ada keluarga (ayah/ibu/saudara kandung) didiagnosis/menderita "
        "kanker sebelumnya?"
    ),
    "riwayat_merokok": "Riwayat merokok/paparan asap rokok",
    "riwayat_bekerja": (
        "Riwayat tempat kerja mengandung zat karsinogenik (Pertambangan/ pabrik/ "
        "bengkel/ garmen/ bangunan/ laboratorium/ sopir/ galangan kapal, dll)?"
    ),
    "tempat_tinggal_berpolusi": (
        "Lingkungan tempat tinggal berpotensi tinggi (lingkungan dekat pabrik/"
        "pertambangan/buangan sampah, dll)?"
    ),
    "rumah_tidak_sehat": (
        "Lingkungan dalam rumah yang tidak sehat (ventilasi buruk/atap dari asbes/"
        "lantai tanah, dapur tungku, dll)?"
    ),
    "diagnosis_paru_kronik": "Pernah didiagnosis penyakit paru kronik?",
}


def _map_skrining_kanker_paru(
    epus: dict,
    flags: dict[str, dict[str, bool]],
    *,
    skr: dict | None = None,
    gender: str | None = None,
    years: int | None = None,
) -> dict[str, Any]:
    """ASIK ``Skrining Kanker Paru (Usia =>45 thn)`` (live, audit 2026-04-29).

    Live form is gender-agnostic (8 Q). Q1/Q2/Q3/Q7 derive from EPUS; Q4-Q6
    + Q8 (Foto Torax) have no EPUS source. ``Jenis Kelamin - skor APCS``
    and ``Usia - skor APCS`` from prior CSV spec are **not** on the live
    form — drop them.

    Skrining-klaster primary (PKM 2026-08): when the EPUS ``skriningkankerparu``
    screening captured a field it OVERRIDES the module-derived answer and fills
    the four environment questions that have no module source (see the override
    block at the end).
    """
    fr = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get("Faktor Risiko")
        or {}
    )
    keluarga = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {})
        .get("Riwayat PTM pada Keluarga") or {}
    )
    out: dict[str, Any] = {}

    # Q1 self-cancer
    if flags["clinical"].get("kanker"):
        out["Apakah pernah didiagnosis/menderita kanker?"] = (
            "Memiliki diagnosis kanker <5 tahun yang lalu"
        )
    elif _yatidak(((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {})
                  .get("Riwayat PTM pada Diri Sendiri", {}).get("Penyakit Kanker")) == "Tidak":
        out["Apakah pernah didiagnosis/menderita kanker?"] = (
            "Tidak pernah didiagnosis menderita kanker"
        )

    # Q2 family-cancer
    fam = _yatidak(keluarga.get("Penyakit Kanker"))
    if fam == "Ya":
        out["Apakah ada keluarga (ayah/ibu/saudara kandung) didiagnosis/menderita kanker sebelumnya?"] = (
            "Memiliki keluarga yang terdiagnosis kanker lain"
        )
    elif fam == "Tidak":
        out["Apakah ada keluarga (ayah/ibu/saudara kandung) didiagnosis/menderita kanker sebelumnya?"] = (
            "Tidak ada keluarga yang terdiagnosis kanker"
        )

    # Q3 smoking
    smoke = fr.get("Merokok")
    if smoke is not None:
        s = str(smoke).strip().lower()
        if "tidak" in s or "bukan" in s or s.startswith("non"):
            out["Riwayat merokok/paparan asap rokok"] = "Tidak pernah merokok"
        elif "aktif" in s or "merokok" in s or "perokok" in s:
            out["Riwayat merokok/paparan asap rokok"] = (
                "Perokok aktif (dalam 1 tahun ini masih merokok)"
            )

    # Q7 paru kronik
    if flags["clinical"].get("tb"):
        out["Pernah didiagnosis penyakit paru kronik?"] = (
            "Pernah didiagnosis tuberkulosis (TBC)"
        )
    elif flags["clinical"].get("paru_kronis"):
        out["Pernah didiagnosis penyakit paru kronik?"] = (
            "Pernah didiagnosis penyakit kronis lain (PPOK, ILD, dll)"
        )
    elif _yatidak(((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {})
                  .get("Riwayat PTM pada Diri Sendiri", {}).get("Penyakit Asma")) == "Tidak":
        out["Pernah didiagnosis penyakit paru kronik?"] = (
            "Tidak pernah didiagnosis penyakit paru kronik"
        )

    # ── Skrining-klaster primary (PKM 2026-08) ──────────────────────────
    # The EPUS screening stores the numeric option code for each jQuery-checked
    # radio; decode it and OVERRIDE the module answer above. The four
    # environment questions have no module source — the screening is their only
    # source.
    screen = (skr or {}).get("skriningkankerparu") or {}

    def _kp(field: str, code_map: dict[str, str]) -> None:
        opt = code_map.get((_clean_text(screen.get(field)) or "").strip())
        if opt:
            out[_KP_LABELS[field]] = opt

    _kp("diagnosis_kanker", {
        "1": "Tidak pernah didiagnosis menderita kanker",
        "2": "Memiliki diagnosis kanker <5 tahun yang lalu",
        "3": "Memiliki diagnosis kanker >5 tahun yang lalu",
    })
    _kp("keluarga_kanker", {
        "1": "Tidak ada keluarga yang terdiagnosis kanker",
        "2": "Memiliki keluarga yang terdiagnosis kanker lain",
        "3": "Memiliki keluarga yang terdiagnosis kanker paru",
    })
    _kp("riwayat_merokok", {
        "1": "Tidak pernah merokok",
        "2": "Perokok pasif dari lingkungan rumah/tempat kerja",
        "3": "Perokok/bekas perokok berhenti <10 tahun lalu",
        "4": "Perokok aktif (dalam 1 tahun ini masih merokok)",
    })
    _kp("riwayat_bekerja", {
        "1": "Tidak tempat kerja mengandung zat karsinogenik",
        "2": "Tidak yakin tempat kerja mengandung zat karsinogenik",
        "3": "Ya, memiliki tempat kerja mengandung zat karsinogenik",
    })
    _kp("tempat_tinggal_berpolusi", {
        "1": "Tidak memiliki tempat tinggal berpotensi tinggi",
        "2": "Tidak yakin memiliki tempat tinggal berpotensi tinggi",
        "3": "Memiliki tempat tinggal berpotensi tinggi",
    })
    _kp("rumah_tidak_sehat", {
        "1": "Memiliki lingkungan dalam rumah yang sehat",
        "2": "Tidak yakin memiliki lingkungan dalam rumah yang tidak sehat",
        "3": "Memiliki lingkungan dalam rumah yang tidak sehat",
    })
    _kp("diagnosis_paru_kronik", {
        "1": "Tidak pernah didiagnosis penyakit paru kronik",
        "2": "Pernah didiagnosis penyakit kronis lain (PPOK, ILD, dll)",
        "3": "Pernah didiagnosis tuberkulosis (TBC)",
    })

    return out


def _map_penapisan_kanker_paru(
    epus: dict, flags: dict[str, dict[str, bool]], *, skr: dict | None = None
) -> dict[str, Any]:
    """ASIK Penapisan Risiko Kanker Paru (FRM000138).

    5 binary Y/N. Q1, Q3, Q4, Q5 derivable from EPUS; Q2 (paparan asap rokok
    orang lain) has no EPUS source.
    """
    fr = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get("Faktor Risiko")
        or {}
    )
    keluarga = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {})
        .get("Riwayat PTM pada Keluarga") or {}
    )
    out: dict[str, Any] = {}

    # Q1 merokok setahun terakhir
    smoke = fr.get("Merokok")
    if smoke is not None:
        s = str(smoke).strip().lower()
        if "tidak" in s or "bukan" in s or s.startswith("non"):
            out["Apakah Anda merokok dalam setahun terakhir ini?"] = "Tidak"
            out["Apakah Anda pernah memiliki riwayat merokok dalam 15 tahun terakhir?"] = "Tidak"
        elif "aktif" in s or "merokok" in s or "perokok" in s:
            out["Apakah Anda merokok dalam setahun terakhir ini?"] = "Ya"
            # Q1b: any nonzero smoking duration → Ya; otherwise null
            lama = _num(fr.get("Lama Merokok dalam Tahun"))
            if lama is not None:
                out["Apakah Anda pernah memiliki riwayat merokok dalam 15 tahun terakhir?"] = (
                    "Ya" if lama > 0 else "Tidak"
                )

    # Q3 keluarga kanker paru — EPUS only knows generic kanker; defensive Ya
    fam = _yatidak(keluarga.get("Penyakit Kanker"))
    if fam in ("Ya", "Tidak"):
        out["Apakah memiliki riwayat kanker paru pada keluarga (ayah/ibu/saudara kandung)?"] = fam

    # Q4 gejala batuk lama / nyeri dada / leher bengkak — TB ICDX implies cough
    if flags["clinical"].get("tb"):
        out[
            "Apakah Anda sedang mengalami salah satu atau lebih gejala berikut dan telah "
            "diobati tetapi tidak sembuh-sembuh : batuk dalam jangka waktu yang lama / "
            "batuk berdarah/ sesak napas/ nyeri dada/ leher bengkak/ terdapat benjolan "
            "pada leher?"
        ] = "Ya"

    # Q5 riwayat TBC atau PPOK
    if flags["clinical"].get("tb") or flags["clinical"].get("paru_kronis"):
        out["Apakah Anda pernah memiliki riwayat penyakit TBC atau PPOK?"] = "Ya"

    # ── Skrining-klaster primary (PKM 2026-08) — derive the Penapisan Y/N from
    #    the same Skrining Kanker Paru coded screening; OVERRIDES the module
    #    answers above when the screening captured the field.
    screen = (skr or {}).get("skriningkankerparu") or {}
    merokok_code = (_clean_text(screen.get("riwayat_merokok")) or "").strip()
    if merokok_code in ("1", "2", "3", "4"):
        # 1=Tidak / 2=pasif / 3=bekas<15th / 4=aktif
        out["Apakah Anda merokok dalam setahun terakhir ini?"] = (
            "Ya" if merokok_code == "4" else "Tidak"
        )
        out["Apakah Anda pernah memiliki riwayat merokok dalam 15 tahun terakhir?"] = (
            "Ya" if merokok_code in ("3", "4") else "Tidak"
        )
        if merokok_code == "2":  # perokok pasif ⇒ terpapar asap rokok orang lain
            out[
                "Apakah Anda terpapar atau menghirup asap rokok dari orang lain di "
                "rumah, lingkungan atau tempat kerja dalam 1 bulan terakhir?"
            ] = "Ya"
    keluarga_code = (_clean_text(screen.get("keluarga_kanker")) or "").strip()
    if keluarga_code in ("1", "2", "3"):
        # only 3=kanker paru counts as lung-cancer family history
        out["Apakah memiliki riwayat kanker paru pada keluarga (ayah/ibu/saudara kandung)?"] = (
            "Ya" if keluarga_code == "3" else "Tidak"
        )
    paru_code = (_clean_text(screen.get("diagnosis_paru_kronik")) or "").strip()
    if paru_code in ("1", "2", "3"):  # 2=PPOK / 3=TBC ⇒ Ya
        out["Apakah Anda pernah memiliki riwayat penyakit TBC atau PPOK?"] = (
            "Ya" if paru_code in ("2", "3") else "Tidak"
        )

    return out


def _map_faktor_risiko_kanker_usus(epus: dict) -> dict[str, Any]:
    """ASIK ``Faktor Risiko Kanker Usus`` (live, 2 Q — audit 2026-04-29).

    Live fields:
    - ``Apakah ada anggota keluarga Anda, yang pernah dinyatakan menderita
      kanker kolorektal atau kanker usus?`` (Ya/Tidak)
    - ``Apakah Anda merokok?`` (Ya/Tidak)

    APCS demographic + score fields from prior CSV spec are not on live
    form — drop them.
    """
    out: dict[str, Any] = {}
    keluarga = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {})
        .get("Riwayat PTM pada Keluarga") or {}
    )
    fr = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get("Faktor Risiko")
        or {}
    )

    fam = _yatidak(keluarga.get("Penyakit Kanker"))
    if fam in ("Ya", "Tidak"):
        out[
            "Apakah ada anggota keluarga Anda, yang pernah dinyatakan menderita "
            "kanker kolorektal atau kanker usus?"
        ] = fam

    smoke = fr.get("Merokok")
    if smoke is not None:
        s = str(smoke).strip().lower()
        if "aktif" in s or "merokok" in s or "perokok" in s:
            out["Apakah Anda merokok?"] = "Ya"
        elif "tidak" in s or "bukan" in s or s.startswith("non"):
            out["Apakah Anda merokok?"] = "Tidak"

    return out


def _map_tingkat_aktivitas_fisik(epus: dict) -> dict[str, Any]:
    """ASIK ``Tingkat Aktivitas Fisik (sedang dan berat)`` (live, 6 Q).

    Live labels (audit 2026-04-29). EPUS only carries ``Kurang Aktivitas
    Fisik`` binary — emit Q4 (olahraga intensitas sedang) and Q6 (olahraga
    intensitas berat) as inverted derivations. Q1/Q2/Q3/Q5 (domestic/work/
    travel sedang + work berat) have no EPUS source.
    """
    fr = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get("Faktor Risiko")
        or {}
    )
    raw = fr.get("Kurang Aktivitas Fisik") or ""
    sl = str(raw).strip().lower()
    if sl.startswith("ya"):
        kurang = "Ya"
    elif sl.startswith("tidak") or sl.startswith("tdk"):
        kurang = "Tidak"
    else:
        return {}

    olahraga_sedang_q = (
        "Apakah Anda melakukan olahraga intensitas sedang seperti latihan beban "
        "< 20 kg, senam aerobic, yoga, bermain bola, bersepeda dan berenang (santai)?"
    )
    olahraga_berat_q = (
        "Apakah Anda melakukan olahraga intensitas berat seperti bersepeda cepat "
        "(>16 km/jam), jalan cepat (>7 km/jam), lari, sepak bola, futsal, "
        "bulutangkis, tenis, basket dan lompat tali?"
    )
    if kurang == "Ya":
        return {olahraga_sedang_q: "Tidak", olahraga_berat_q: "Tidak"}
    # ``Kurang Aktivitas Fisik`` = Tidak → patient is active. EPUS does not
    # distinguish sedang vs berat — emit sedang Ya only (IPAQ default).
    return {olahraga_sedang_q: "Ya"}


def _map_pemeriksaan_tuberkulosis(
    epus: dict, flags: dict[str, dict[str, bool]]
) -> dict[str, Any]:
    """ASIK ``Pemeriksaan Tuberkulosis (Dewasa & Lansia)`` (live, 2 Q only).

    Live fields (audit 2026-04-29):
    - ``Apakah anda ada kontak dengan pasien Tuberkulosis (TBC)?``
    - ``Metode Pemeriksaan (untuk terduga TB)``

    TCM / BTA result fields from prior CSV xlsx are **not** on the live
    form — drop those emissions.
    """
    out: dict[str, Any] = {}
    tb_tab = (epus.get("tabs") or {}).get("TB Paru", {}).get("fields", {}) or {}
    klasifikasi = tb_tab.get("Tipe Diagnosis dan Klasifikasi Pasien TB") or {}
    register = tb_tab.get("Data Register Terduga TB") or {}

    kriteria = register.get("Kriteria Terduga TB")
    if kriteria not in (None, "", "-"):
        out["Apakah anda ada kontak dengan pasien Tuberkulosis (TBC)?"] = "Ya"

    # Derive Metode from which lab result is filled — without emitting the
    # result values themselves (no live field for them).
    tcm = klasifikasi.get("Sebelum pengobatan hasil tes cepat")
    bta = klasifikasi.get("Sebelum pengobatan hasil mikroskopis")
    if tcm and bta:
        out["Metode Pemeriksaan (untuk terduga TB)"] = "TCM dan Mikroskopis"
    elif tcm:
        out["Metode Pemeriksaan (untuk terduga TB)"] = "TCM"
    elif bta:
        out["Metode Pemeriksaan (untuk terduga TB)"] = "Mikroskopis"

    return out


def _map_pemeriksaan_kadar_co(epus: dict) -> dict[str, Any]:
    """ASIK ``Perilaku Merokok - Pemeriksaan Kadar CO`` (CSV PROD).

    Q ``Kadar CO Pernapasan`` — EPUS PTM Form UBM has ``CAR`` field
    (Carbon-monoxide reading). Numeric; emit if present.
    """
    fr_ubm = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get("Form UBM")
        or {}
    )
    car = _num(fr_ubm.get("CAR"))
    if car is None:
        return {}
    return {"Kadar CO Pernapasan": car}


def _map_skrining_jantung_ekg(epus: dict) -> dict[str, Any]:
    """ASIK ``Skrining Jantung (Pemeriksaan EKG - hanya penyandang HIPERTENSI)``.

    EPUS PTM > Kardiovaskular > Hasil EKG (``Ptm[ekg_v2]`` select rendered
    via the _NAME_HINTS fallback). Map common EPUS option text → ASIK enum.
    """
    kardio = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get("Kardiovaskular")
        or {}
    )
    raw = kardio.get("Hasil EKG")
    if raw is None or raw == "":
        return {}
    s = str(raw).strip().lower()
    if "normal" in s:
        return {"Hasil Pemeriksaan EKG": "Normal"}
    if "abnormal" in s or "kelainan" in s or "tidak normal" in s:
        return {"Hasil Pemeriksaan EKG": "Abnormal"}
    return {}


def _map_dental(epus: dict) -> dict[str, dict[str, Any]]:
    """EPUS ``Anamnesa > Pemeriksaan Dasar Gigi`` → ASIK dental screening forms.

    Live ASIK forms (audit 2026-05-29), all radio Ya/Tidak:
    - ``Skrining Karies dan Gigi Hilang``: ``Gigi karies`` / ``Gigi hilang/dicabut``
    - ``Skrining Penyakit Periodontal``:   ``Penyakit Periodontal`` / ``Gigi Goyang``

    EPUS source: ``Anamnesa > Pemeriksaan Dasar Gigi`` (flat sign dict; only ~5%
    of patients have a basic-dental exam). The EPUS Odontogram block is **not**
    used — its ``Diastema`` / ``Gigi Anomali`` fields are constant ``"Ada"``
    defaults (123/123 in the live DB) i.e. noise, and it has no caries/missing
    signal.

    Mapping (zero-hallucination; degrade to None when the sign is absent):
    - ``Gigi Goyang``          ← ``Goyang`` (Ya/Tidak), 1:1.
    - ``Gigi karies``          ← ``Status Karies`` (``+``→Ya / ``-``→Tidak); else
                                 ``Karies Gigi`` (a tooth-surface location like
                                 ``"Oklusal"``) present → Ya.
    - ``Penyakit Periodontal`` ← gum inflammation: ``Warna Gusi`` != Normal (e.g.
                                 ``"Kemerahan"``) or ``Pem-bengkakan`` == ``"Ada"``
                                 → Ya; gum Normal and no swelling → Tidak.
    - ``Gigi hilang/dicabut``  → None (EPUS has no extracted/missing-tooth field).
    """
    gigi = (
        ((epus.get("tabs") or {}).get("Anamnesa") or {}).get("fields", {}).get(
            "Pemeriksaan Dasar Gigi"
        )
        or {}
    )
    if not gigi:
        return {}
    karies: dict[str, Any] = {}
    perio: dict[str, Any] = {}

    # Gigi karies — Status Karies primary; Karies Gigi (lesion location) corroborates.
    status_karies = _clean_text(gigi.get("Status Karies"))
    karies_lokasi = _clean_text(gigi.get("Karies Gigi"))
    if status_karies == "+" or (karies_lokasi and karies_lokasi != "-"):
        karies["Gigi karies"] = "Ya"
    elif status_karies == "-":
        karies["Gigi karies"] = "Tidak"
    # Gigi hilang/dicabut — no EPUS source; left for ASIK clerk.

    # Gigi Goyang ← Goyang (1:1).
    goyang = _yatidak(gigi.get("Goyang"))
    if goyang is not None:
        perio["Gigi Goyang"] = goyang

    # Penyakit Periodontal ← gum-inflammation signs (redness / swelling).
    wg = (_clean_text(gigi.get("Warna Gusi")) or "").lower()
    pb = (_clean_text(gigi.get("Pem-bengkakan")) or "").lower()
    if wg or pb:
        if (wg and wg != "normal") or pb in ("ada", "ya"):
            perio["Penyakit Periodontal"] = "Ya"
        elif wg == "normal" and pb in ("tidak", ""):
            perio["Penyakit Periodontal"] = "Tidak"

    out: dict[str, dict[str, Any]] = {}
    if karies:
        out["Skrining Karies dan Gigi Hilang"] = karies
    if perio:
        out["Skrining Penyakit Periodontal"] = perio
    return out


def _map_identitas(epus: dict) -> dict[str, Any]:
    """Pull identitas (NIK / Nama / Tanggal Lahir / etc.) from data_pasien
    and normalise values to ASIK form format.

    Normalisation rules (verified live 2026-05-11 against ASIK
    `data_individu`):
    - ``Tanggal Lahir`` : ``DD-MM-YYYY`` → ``DD Bulan YYYY`` (e.g.
      ``15 Maret 2002``).
    - ``Jenis Kelamin`` : ``P`` / ``L`` → ``Perempuan`` / ``Laki-Laki``.

    Skips keys whose source is missing/blank. Merge logic in
    ``app.tasks.merge._gender_from_converted`` already accepts the
    normalised values.
    """
    pasien = epus.get("data_pasien") or {}
    out: dict[str, Any] = {}

    nik = pasien.get("NIK")
    if nik not in (None, ""):
        out["NIK"] = nik

    nama = pasien.get("Nama Pasien") or pasien.get("Nama")
    if nama not in (None, ""):
        out["Nama"] = nama

    # Birthplace/DOB: most EPUS regions key this "Tempat/Tgl Lahir"; jaksel
    # renames it "Tempat & Tgl Lahir" (and separates place/date with a comma,
    # not a slash). Read either key.
    ttl = pasien.get("Tempat/Tgl Lahir") or pasien.get("Tempat & Tgl Lahir")
    if ttl not in (None, ""):
        # Value is "<place><sep><dd-mm-yyyy>" where sep is "/" (most regions) or
        # "," (jaksel), with arbitrary whitespace/newlines (e.g.
        # "BEKASI/\n  08-06-1974", "JAKARTA, 07-10-1978"). Some have an empty
        # place ("/16-07-1962"). Anchor on the trailing dd-mm-yyyy so the
        # separator/region doesn't matter, then convert to ASIK Indonesian.
        s = re.sub(r"\s+", " ", str(ttl)).strip()
        m = re.search(r"(\d{1,2}-\d{1,2}-\d{4})\s*$", s)
        if m:
            tempat = s[:m.start()].strip(" ,/").strip()
            if tempat:
                out["Tempat Lahir"] = tempat
            out["Tanggal Lahir"] = _dmy_to_indo(m.group(1)) or m.group(1)
        else:
            # No trailing date — slash-split fallback (place-only / odd shapes).
            tempat, sep, tgl = s.partition("/")
            if sep and tempat.strip():
                out["Tempat Lahir"] = tempat.strip()
            if sep and tgl.strip():
                out["Tanggal Lahir"] = _dmy_to_indo(tgl.strip()) or tgl.strip()

    jk = pasien.get("Jenis Kelamin")
    jk_norm = _gender_norm(jk)
    if jk_norm is not None:
        out["Jenis Kelamin"] = jk_norm
    elif jk not in (None, ""):
        out["Jenis Kelamin"] = jk

    alamat = pasien.get("Alamat")
    if alamat not in (None, ""):
        # Alamat from EPUS often has table-cell whitespace. Collapse to a
        # single line so the UI cell renders cleanly; keep all words.
        out["Alamat Domisili"] = re.sub(r"\s+", " ", str(alamat)).strip()

    return out


# ─── pediatric (under-18) mappers ─────────────────────────────────────────


def _talasemia_curiga(thal: dict) -> str | None:
    """EPUS ``Skrining Thalasemia`` conclusion → ASIK ``Curiga Talasemia``.

    EPUS ``kesimpulan`` is e.g. ``"Tidak dicurigai thalasemia"`` (verified live
    jaksel 2026-06-25). Maps the negated/affirmed conclusion to ``Tidak``/``Ya``.
    """
    k = _clean_text(thal.get("kesimpulan"))
    if not k:
        return None
    s = k.lower()
    if "tidak" in s:  # "Tidak dicurigai thalasemia"
        return "Tidak"
    if "curig" in s or "dicurigai" in s:
        return "Ya"
    return None


def _kmpe_ya_count(kmpe: dict) -> int | None:
    """Count of "Ya" (value ``1``) among the 14 KMPE items ``q1``..``q14`` in the
    EPUS SDIDTK-KMPE screening detail (``skrining_klaster.skrining_sdidtk``).
    Returns ``None`` unless all 14 items are present (the KMPE signature — the
    SDIDTK route may also hold other DDTK sub-tests with a different item set).
    Verified live jaksel 2026-06-25 (pid 1984042: q1=q5=1 → 2 ⇒ "Ada 2 …").
    """
    vals = [kmpe.get(f"q{i}") for i in range(1, 15)]
    if not all(v is not None for v in vals):
        return None
    return sum(1 for v in vals if str(v).strip() == "1")


# M-CHAT-1 question label (byte-exact vs the live ASIK form / committed schema).
_MCHAT_Q = (
    "Apakah anak Anda memiliki satu atau lebih kondisi berikut ini: 1) Masalah "
    "interaksi dengan orang lain seperti kontak mata tidak adekuat; 2) Masalah "
    "bahasa dan bicara seperti kosakata bermakna kurang dari 50 dan anak belum "
    "mampu merangkai kata, belum bisa menunjuk sesuatu, belum paham instruksi "
    "sederhana, atau bicara bahasa planet; 3) Memiliki perilaku berulang tanpa "
    "tujuan atau perilaku aneh seperti senang melihat benda berputar, "
    "menjejerkan mainan, gerakan stereotipik (flapping, clapping, body rocking), "
    "preokupasi terhadap suatu benda, masalah sensoris"
)


def _sdidtk_dev_forms(sdidtk: dict) -> ASIK_Result:
    """Map the single EPUS ``Skrining SDIDTK`` screening → its ASIK development
    form (KPSP / KMPE / GPPH / M-CHAT).

    Verified live (jaksel 2026-06-25, getlist on 110 young patients): EPUS holds
    ALL DDTK sub-tests under the ONE getlist key ``skrining_sdidtk`` (route
    /skriningsdidtkkmpe) — there is no separate kpsp/gpph/mchat key. Which
    sub-test the saved record represents is detected from its content, and only
    that one ASIK form is emitted (one screening = one sub-test per visit).
    Done-rate is ~1/110, so almost always the record is absent → ``{}`` and the
    form is filled manually in ASIK.

    - **KMPE** (verified): 14 items q1..q14 (1=Ya) → option keyed off count of Ya.
    - **KPSP / GPPH / M-CHAT**: use the standardised national SDIDTK
      interpretation vocabulary (``interpretasi``) → byte-exact ASIK option. No
      live record for these exists yet (done-rate ~0); the vocab is the fixed
      Kemenkes SDIDTK wording, and each degrades to ``{}`` on no match, so a
      future real record fills correctly without a code change.
    """
    out: ASIK_Result = {}
    if not sdidtk:
        return out
    # KMPE — the only sub-test observed live; result = count of "Ya" in q1..q14.
    ya = _kmpe_ya_count(sdidtk)
    if ya is not None:
        out[
            "Kuesioner Masalah Perilaku dan Emosional (KMPE) - "
            "Jika terindikasi memiliki masalah perilaku dan emosi"
        ] = {
            "Hasil pemeriksaan KMPE": (
                "Tidak ada jawaban ‘Ya’" if ya == 0
                else "Ada 1 jawaban ‘Ya’" if ya == 1
                else "Ada 2 jawaban ‘Ya’"
            )
        }
        return out
    interp = (_clean_text(sdidtk.get("interpretasi")) or "").lower()
    if not interp:
        return out
    # KPSP — Sesuai / Meragukan / Penyimpangan (standard SDIDTK).
    if "penyimpangan" in interp or "sesuai" in interp or "meragukan" in interp:
        out["Kuesioner Pra Skrining Perkembangan (KPSP)"] = {
            "Hasil pemeriksaan KPSP": (
                "Perkembangan curiga adanya penyimpangan" if "penyimpangan" in interp
                else "Perkembangan meragukan" if "meragukan" in interp
                else "Perkembangan sesuai usia"
            )
        }
    # GPPH — total score, abnormal at ≥13.
    elif "gpph" in interp or "pemusatan" in interp or "hiperaktif" in interp:
        out[
            "Kuesioner Gangguan Pemusatan Perhatian dan Hiperaktivitas (GPPH) - "
            "bila ada indikasi"
        ] = {
            "Hasil Pemeriksaan Kuesioner GPPH": (
                "Nilai total ≧ 13" if ("kemungkinan" in interp or "≥" in interp or "≧" in interp)
                else "Nilai total <13, namun pemeriksa merasa ragu" if "ragu" in interp
                else "Nilai total <13"
            )
        }
    # M-CHAT — autism-risk penapisan; any flagged risk → "Ya".
    elif "m-chat" in interp or "mchat" in interp or "autis" in interp or "risiko" in interp:
        low = "rendah" in interp or "negatif" in interp or "tidak" in interp or "normal" in interp
        out["M-CHAT - 1. Penapisan"] = {_MCHAT_Q: "Tidak" if low else "Ya"}
    return out


def _telinga_mata_balita(pend: dict, peng: dict) -> dict[str, Any]:
    """ASIK ``Skrining Telinga dan Mata - Balita dan Anak Prasekolah`` from the
    EPUS ``Skrining Indra Pendengaran`` + ``Skrining Kesehatan Penglihatan``
    screenings (the balita ear/eye source — NOT ``PTM > Gangguan Penglihatan``,
    which is 0% for under-18). Each field is emitted only when its EPUS source is
    present; an abnormal finding ⇒ the penyimpangan option, all-normal ⇒ the
    normal option (option text byte-exact vs the live form, verified 2026-06-25).
    """
    out: dict[str, Any] = {}
    # Tes Daya Dengar — any positive finding or non-"Tidak Rujuk" ⇒ penyimpangan.
    if pend:
        findings = [pend.get(k) for k in (
            "curiga_telinga_kiri", "curiga_telinga_kanan",
            "pemeriksaan_telinga_kiri", "pemeriksaan_telinga_kanan",
            "omsk_telinga_kiri", "omsk_telinga_kanan",
            "presbikusis_telinga_kiri", "presbikusis_telinga_kanan",
        )]
        rujuk = [pend.get(k) for k in ("curiga_rujuk", "pemeriksaan_rujuk", "omsk_rujuk")]
        abnormal = (
            any((_clean_text(v) or "").lower() == "ya" for v in findings)
            or any((_clean_text(v) or "tidak").lower().replace("tidak rujuk", "tidak") not in ("tidak", "")
                   for v in rujuk if _clean_text(v))
        )
        out["Hasil Tes Daya Dengar"] = (
            "Ada kemungkinan penyimpangan" if abnormal else "Sesuai Umur"
        )
    # Tes Daya Lihat + selaput/kornea from penglihatan.
    if peng:
        tk = _clean_text(peng.get("tajam_kiri"))
        tn = _clean_text(peng.get("tajam_kanan"))
        if tk or tn:
            normal = all("normal" in (x or "").lower() for x in (tk, tn) if x)
            out["Hasil pemeriksaan Tes Daya Lihat"] = (
                "Daya lihat anak baik (visus >6/12 atau >6/60)" if normal
                else "Daya lihat anak kurang (visus <6/12 atau <6/60)"
            )
        ml = _clean_text(peng.get("mata_luar"))
        if ml:
            out[
                "Apakah ditemukan selaput mata merah atau kornea keruh atau "
                "kelopak mata ada benjolan atau susah berkedip atau posisi bola "
                "mata juling atau pupil putih?"
            ] = "Normal" if "normal" in ml.lower() else "Curiga kelainan mata"
    return out


def _pediatric_forms(
    epus: dict, gender: str, years: int, flags: dict[str, dict[str, bool]]
) -> ASIK_Result:
    """Under-18 ASIK form battery — kids have a DISTINCT set of forms from adults.

    Form + field names are byte-exact against the live ASIK forms that matched
    under-18 patients actually carry (600 matched kids, ``scraped_asik_data``
    audit 2026-06-02); age bands are the empirically-observed ranges per form.
    EPUS only sources the general clinical battery shared with adults —
    anthropometry/vitals (``Anamnesa > Periksa Fisik``), glucose
    (``PTM > Pemeriksaan``), cough (``Anamnesa``), and basic dental. The
    pediatric-specific EPUS tabs (``Imunisasi``, ``Tumbuh Kembang Anak``) are
    empty shells, so newborn-screening / immunization / development forms have
    no source and are not emitted (see the skill's RESEARCH_STATUS → Pediatric).
    """
    fisik = (
        ((epus.get("tabs") or {}).get("Anamnesa") or {}).get("fields", {}).get(
            "Periksa Fisik"
        )
        or {}
    )
    pem = (
        ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}).get("Pemeriksaan")
        or {}
    )
    gigi = (
        ((epus.get("tabs") or {}).get("Anamnesa") or {}).get("fields", {}).get(
            "Pemeriksaan Dasar Gigi"
        )
        or {}
    )
    # Kartu Bayi "Identitas Bayi" — birth measurements (Berat/Panjang Badan at
    # birth) persist on the bayi's record. Laboratorium result grid — hematology
    # (Hb/MCV/MCH/RBC/RDW). Klaster/Siklus-Hidup screening battery — ear/eye/
    # thalasemia results. All three are scraped today (verified 2026-06-25).
    kartubayi = (
        ((epus.get("tabs") or {}).get("Kartubayi") or {}).get("fields", {}).get(
            "Identitas Bayi"
        )
        or {}
    )
    lab = _lab_results(epus)
    skr = _skrining_index(epus)
    bb = _num(fisik.get("Berat Badan"))
    tb = _num(fisik.get("Tinggi Badan"))
    posisi = _clean_text(fisik.get("Cara Ukur Tinggi Badan"))
    out: ASIK_Result = {}

    # ── Bayi (<1 thn): "Berat Lahir" form. Berat Lahir (birth weight) IS in
    #    EPUS — ``Kartu Bayi > Identitas Bayi > Berat Badan`` (verified live
    #    jaksel 2026-06-25; the old "not in EPUS → manual" note looked at the
    #    wrong tab, Periksa Fisik). "Berat Badan Saat Ini" = the current-visit
    #    weight from Periksa Fisik. "Berat Lahir" is a near-universal bayi form. ──
    if years < 1:
        bl: dict[str, Any] = {}
        berat_lahir = _num(kartubayi.get("Berat Badan"))
        if berat_lahir is not None:
            bl["Berat Lahir"] = berat_lahir
        if bb is not None:
            bl["Berat Badan Saat Ini (usia >24 jam)"] = bb
        out["Berat Lahir"] = bl

        # ── Pemeriksaan PJB (Jantung Bawaan) — the feedback's MTBM source is now
        #    scraped (mtbm module), but the EPUS newborn exam records only a
        #    SINGLE Saturasi oksigen, never the pre/post-ductal pair (tangan kanan
        #    + kaki) this form needs — so the values can't be filled from EPUS.
        #    Emitted as a shell (present for bayi, like the skin shells) so it is
        #    wired into the merge/sync; nakes fills the two readings in ASIK. ──
        out["Pemeriksaan PJB"] = {}

    # ── Riwayat Imunisasi Rutin Balita — the Hepatitis-B birth dose IS in EPUS:
    #    Kartu Bayi > Pencegahan > "Hep. B0" checkbox (live-verified kotabekasi
    #    2026-06-25). Only this dose is derivable; the rest of the schedule
    #    (BCG/Polio/DPT/…) has no EPUS source and stays nakes-filled. Emitted
    #    whenever the bayi's Pencegahan group is present. ──
    penceg = kartubayi.get("Pencegahan")
    if not isinstance(penceg, dict):
        penceg = (
            ((epus.get("tabs") or {}).get("Kartubayi") or {})
            .get("fields", {})
            .get("Pencegahan")
        )
    if isinstance(penceg, dict) and "Hep. B0" in penceg:
        hepb = penceg.get("Hep. B0")
        sudah = hepb is True or (_clean_text(hepb) or "").lower() in (
            "ya", "sudah", "true", "1",
        )
        out["Riwayat Imunisasi Rutin Balita"] = {
            "Apakah anak anda sudah pernah menerima imunisasi Hepatitis B "
            "pada usia <24 jam?": "Sudah" if sudah else "Belum"
        }

    # ── Growth / anthropometry (BB · TB · posisi from Periksa Fisik) ──
    if 1 <= years <= 4:
        g: dict[str, Any] = {}
        if bb is not None:
            g["Berat Badan Balita"] = bb
        if tb is not None:
            g["Pengukuran Tinggi Badan (cm)"] = tb
        if posisi in ("Berdiri", "Telentang"):
            g["Posisi Pengukuran"] = posisi
        out["Skrining Pertumbuhan - Balita dan Anak Prasekolah 1-5 Tahun"] = g
    elif 5 <= years <= 6:
        g = {}
        if tb is not None:
            g["Pengukuran Tinggi Badan (cm)"] = tb
        # NOTE: "Pilih hasil IMT/U" IS in EPUS (Anamnesa > Periksa Fisik >
        # Hasil IMT, e.g. "BERISIKO GIZI LEBIH") and is already scraped, but the
        # live ASIK dropdown options for IMT/U are not captured in the mapping
        # yet — we don't emit a category until those options are confirmed
        # (sending a non-matching option would fail the ASIK sync).
        out["Skrining Pertumbuhan - Balita dan Anak Prasekolah 5-6 Tahun"] = g
    elif 7 <= years <= 17:
        g = {}
        if bb is not None:
            g["Berat Badan"] = bb
        if tb is not None:
            g["Tinggi Badan"] = tb
        out["Gizi Anak Sekolah"] = g

    # ── Tekanan Darah Anak dan Remaja (vitals from Periksa Fisik) ──
    if 7 <= years <= 17:
        td: dict[str, Any] = {}
        sistole = _num(fisik.get("Sistole"))
        diastole = _num(fisik.get("Diastole"))
        if sistole is not None:
            td["Tekanan Darah Sistol"] = sistole
        if diastole is not None:
            td["Tekanan Darah Diastol"] = diastole
        out["Tekanan Darah Anak dan Remaja"] = td

    # ── Gula Darah (DM self-report radio + GDS) — anak 2-14 / remaja 15-17 ──
    gd_q = "Apakah Anak Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?"
    dm_parent = "Ya" if flags["self_report"]["diabetes"] else "Tidak"
    gds = _num(pem.get("Pemeriksaan Gula"))
    if 15 <= years <= 17:
        gd: dict[str, Any] = {gd_q: dm_parent}
        if gds is not None:
            gd["Gula Darah Sewaktu (GDS)"] = gds
        out["Pemeriksaan Gula Darah Remaja"] = gd
    elif 2 <= years <= 14:
        gd = {gd_q: dm_parent}
        if gds is not None:
            gd["Gula Darah Sewaktu (GDS)"] = gds
        out["Pemeriksaan Gula Darah Anak"] = gd

    # ── Pemeriksaan Gigi - Anak — only the "no caries" case is derivable from
    #    EPUS ``Status Karies`` "-" (EPUS has no caries COUNT, so a positive
    #    count stays None for the nakes to fill). ──
    if 1 <= years <= 17:
        gigi_out: dict[str, Any] = {}
        if _clean_text(gigi.get("Status Karies")) == "-":
            gigi_out["Berapa jumlah gigi karies?"] = "Tidak ada"
        out["Pemeriksaan Gigi - Anak"] = gigi_out

    # ── Faktor Risiko TB X-Ray (Anak 1-9 tahun) — cough Q reuses adult logic ──
    if 1 <= years <= 9:
        tb_out: dict[str, Any] = {}
        cough = _cough_duration(epus, flags)
        if cough is not None:
            tb_out[
                "Apakah anak Anda pernah atau sedang mengalami batuk yang tidak sembuh-sembuh?"
            ] = cough
        # BB turun + demam ← Skrining Gejala TBC (live-verified /skrining/tbc
        # 2026-06-26: bb_turun / demam are saved 1/0 radios the scraper captures
        # via _extract_js_answers under skr["gejala_tbc"]). Radiografi-done ←
        # the form's "abnormalitas_tbc" chest-X-ray reading being present.
        # lesu/malaise + kelenjar getah bening are NOT on the EPUS form, and the
        # ASIK X-Ray TB Anak form has no "Hasil rontgen" question → nakes-filled.
        gt = skr.get("gejala_tbc") or {}
        bb_turun = _clean_text(gt.get("bb_turun"))
        if bb_turun in ("0", "1"):
            tb_out[
                "Apakah berat badan anak Anda turun tanpa penyebab jelas/ "
                "BB tidak naik dalam 2 bulan sebelumnya/ nafsu makan turun?"
            ] = "Ya" if bb_turun == "1" else "Tidak"
        demam = _clean_text(gt.get("demam"))
        if demam in ("0", "1"):
            tb_out[
                "Apakah anak anda mengalami demam hilang timbul tanpa sebab "
                "yang jelas lebih dari 2 minggu?"
            ] = "Ya" if demam == "1" else "Tidak"
        if _clean_text(gt.get("abnormalitas_tbc")):
            tb_out["Apakah dilakukan pemeriksaan radiografi toraks?"] = "Ya"
        out["Faktor Risiko dan Skrining X-Ray TB (Anak 1-9 tahun)"] = tb_out

        # Pemeriksaan Tuberkulosis (Anak) — the kontak-TB question reuses the
        # same TB Paru "Data Register Terduga TB" signal the adult
        # _map_pemeriksaan_tuberkulosis uses. Near-universal nakes form for
        # anak; emitted within the same empirical 1-9 band as the X-Ray form.
        tbc_out: dict[str, Any] = {}
        tb_register = (
            (epus.get("tabs") or {}).get("TB Paru", {}).get("fields", {}).get(
                "Data Register Terduga TB"
            )
            or {}
        )
        if tb_register.get("Kriteria Terduga TB") not in (None, "", "-"):
            tbc_out["Apakah anda ada kontak dengan pasien Tuberkulosis (TBC)?"] = "Ya"
        out["Pemeriksaan Tuberkulosis Anak"] = tbc_out

    # ── Skrining Lanjutan Talasemia - Balita dan Anak Prasekolah ──
    #    Hematology (Hb/MCV/MCH/RBC/RDW) from the Laboratorium result grid
    #    (verified live jaksel 2026-06-25: leaf labels ``hemoglobin (hgb)`` /
    #    ``mcv`` / ``mch`` / ``eritrosit (rbc)`` / ``rdw-sd``). "Curiga Talasemia"
    #    from the Skrining Thalasemia conclusion. Emitted only when a CBC (Hb) was
    #    actually run — the "lanjutan" form is the post-rapid-test follow-up. ──
    if 1 <= years <= 6:
        hb = _lab_num(lab, _LAB_HEMOGLOBIN)
        if hb is not None:
            tal: dict[str, Any] = {"Hasil Pemeriksaan Hemoglobin (Hb) dalam g/dL": hb}
            mcv = _lab_num(lab, ("mcv",))
            mch = _lab_num(lab, ("mch",))
            rbc = _lab_num(lab, ("eritrosit (rbc)", "eritrosit", "rbc"))
            rdw = _lab_num(lab, ("rdw-cv", "rdw-sd", "rdw"))
            if mcv is not None:
                tal["Hasil Pemeriksaan MCV"] = mcv
            if mch is not None:
                tal["Hasil Pemeriksaan MCH"] = mch
            if rbc is not None:
                tal["Hasil Pemeriksaan Eritrosit / RBC Count"] = rbc
            if rdw is not None:
                tal["Hasil Pemeriksaan Red cell distribution width (RDW)"] = rdw
            curiga = _talasemia_curiga(skr.get("thalasemia") or {})
            if curiga is not None:
                tal["Curiga Talasemia"] = curiga
            out["Skrining Lanjutan Talasemia - Balita dan Anak Prasekolah"] = tal

    # ── Skrining Telinga dan Mata - Balita dan Anak Prasekolah ──
    #    Ear (Tes Daya Dengar) ← Skrining Indra Pendengaran; eye (Tes Daya Lihat
    #    + selaput/kornea) ← Skrining Kesehatan Penglihatan. Both screenings'
    #    per-side results are JS-applied and captured by the scraper's
    #    _extract_js_answers (verified live jaksel 2026-06-25). ──
    if 1 <= years <= 6:
        tm = _telinga_mata_balita(
            skr.get("skrining_indra_pendengaran") or {},
            skr.get("penglihatan") or {},
        )
        # Serumen impaksi + infeksi telinga ← PTM > Gangguan Pendengaran
        # (live-verified kotabekasi 2026-06-25: scraped as the per-side
        # "Serumen Telinga …" / "Congek Telinga …" Ya/Tidak radios). These two
        # otoscopy findings are NOT in the SDIDTK indra screen — they come from
        # the PTM ear block the feedback flagged.
        gp = (
            ((epus.get("tabs") or {}).get("PTM") or {})
            .get("fields", {})
            .get("Gangguan Pendengaran")
            or {}
        )
        ser = [_yatidak(gp.get(k)) for k in ("Serumen Telinga Kanan", "Serumen Telinga Kiri")]
        if any(v is not None for v in ser):
            tm["Apakah ditemukan serumen impaksi?"] = (
                "Ada serumen impaksi" if "Ya" in ser else "Tidak ada serumen impaksi"
            )
        con = [_yatidak(gp.get(k)) for k in ("Congek Telinga Kanan", "Congek Telinga Kiri")]
        if any(v is not None for v in con):
            tm["Apakah ditemukan infeksi telinga?"] = (
                "Ada infeksi telinga" if "Ya" in con else "Tidak ada infeksi telinga"
            )
        if tm:
            out["Skrining Telinga dan Mata - Balita dan Anak Prasekolah"] = tm

    # ── Skrining SDIDTK development forms (KPSP / KMPE / GPPH / M-CHAT) ──
    #    All share the ONE EPUS key skrining_sdidtk; _sdidtk_dev_forms detects the
    #    done sub-test and emits the matching ASIK form. KMPE is verified live;
    #    KPSP/GPPH/M-CHAT use the standard SDIDTK vocab (done-rate ~0 today). ──
    out.update(_sdidtk_dev_forms(skr.get("skrining_sdidtk") or {}))

    # ── Always-emit skin-screen shells (live for kids; no EPUS source) ──
    for shell in (
        "Pemeriksaan Penyakit Frambusia (untuk daerah endemis atau berisiko frambusia)",
        "Pemeriksaan Penyakit Kusta",
        "Pemeriksaan Penyakit Skabies",
    ):
        out[shell] = {}

    # ── Penapisan & Pemeriksaan Sifilis Anak — the result reuses the adult ICD
    #    logic (penyakit_khusus.ICDX ∪ PTM Diagnosa A50-A53 → Reaktif). It is a
    #    conditional form (only sifilis-exposed infants carry it), so gating on
    #    the rare syphilis flag avoids over-projecting it onto typical kids. ──
    if flags["clinical"].get("syphilis"):
        out["Penapisan dan Pemeriksaan Sifilis Anak"] = {
            "Hasil Pemeriksaan Rapid Test Sifilis": "Reaktif"
        }

    return out


# ─── Klaster & Siklus Hidup screening battery → ASIK ──────────────────────
#
# The scraper now captures EPUS's own CKG "Formulir Skrining" forms under
# ``epus["skrining_klaster"]`` (scrapers/epus: getlist hub + per-screening
# /edit/ detail). Each entry: ``{nama, route, records:[getlist record],
# detail:{input_name: value}}``. These hold the questionnaire data the ASIK
# "CKG vs ePus" sheet marked "Belum ada di ePus" (PHQ-4 Kesehatan Jiwa, SADANIS,
# PPOK PUMA, …). ``_skrining_index`` flattens each screening to a {field:value}
# lookup (detail wins over record — detail carries human labels "Ya"/"Tidak",
# the record may carry raw codes).
#
# Source-wins still holds: where a screening AND a clinical tab both answer an
# ASIK field, the screening is the MORE DIRECT CKG source and takes precedence;
# the tab-derived value stays the fallback when the screening is absent (only
# ~20-42% of patients per region have completed screenings). Every mapper
# degrades to {} when its screening is absent — never crashes.


def _skrining_index(epus: dict) -> dict[str, dict[str, Any]]:
    """Flatten ``epus['skrining_klaster']`` → ``{screening_key: {field: value}}``,
    merging the latest getlist record + edit-page detail (detail wins). Empty
    when the patient has no completed screenings."""
    out: dict[str, dict[str, Any]] = {}
    for key, v in (epus.get("skrining_klaster") or {}).items():
        if not isinstance(v, dict):
            continue
        flat: dict[str, Any] = {}
        recs = v.get("records") or []
        if recs and isinstance(recs[0], dict):
            for k, x in recs[0].items():
                if x not in (None, ""):
                    flat[k] = x
        for k, x in (v.get("detail") or {}).items():
            if x not in (None, ""):
                flat[k] = x
        out[key] = flat
    return out


# ── Kesehatan Jiwa (PHQ-4) ────────────────────────────────────────────────
# The live ASIK "Kesehatan Jiwa" form is the 4 PHQ-4 frequency questions
# (verified 2026-06-05). EPUS's PHQ-4 form holds the SAME 4 questions + the SAME
# 0-3 frequency scale; the per-item answers render via JS (Vue ``viewData``), so
# the scraper now extracts them as ``q::<normalized question>`` → skor 0-3
# (patient_scraper._extract_js_answers). We map each EPUS question to its ASIK
# label (matched by normalized text) and the score to the ASIK frequency option.
#   skor 0,1 → "Tidak sama sekali" / "Kurang dari 1 minggu"  (byte-exact, live ASIK)
#   skor 2,3 → "Lebih dari 1 minggu" / "Hampir setiap hari"  (EPUS labels minus
#              "(satu)"; rare — most answers are 0/1 — confirm if ASIK ever rejects).
_PHQ_FREQ = {"0": "Tidak sama sekali", "1": "Kurang dari 1 minggu",
             "2": "Lebih dari 1 minggu", "3": "Hampir setiap hari"}
_JIWA_Q: tuple[tuple[str, str], ...] = (
    ("dalam 2 minggu terakhir seberapa sering anda kurang tidak bersemangat dalam melakukan kegiatan sehari hari",
     "Dalam 2 minggu terakhir, seberapa sering anda kurang/ tidak bersemangat dalam melakukan kegiatan sehari-hari?"),
    ("dalam 2 minggu terakhir seberapa sering anda merasa murung tertekan atau putus asa",
     "Dalam 2 minggu terakhir, seberapa sering anda merasa murung, tertekan, atau putus asa?"),
    ("dalam 2 minggu terakhir seberapa sering anda merasa gugup cemas atau gelisah",
     "Dalam 2 minggu terakhir, seberapa sering anda merasa gugup, cemas, atau gelisah?"),
    ("dalam 2 minggu terakhir seberapa sering anda tidak mampu mengendalikan rasa khawatir",
     "Dalam 2 minggu terakhir, seberapa sering anda tidak mampu mengendalikan rasa khawatir?"),
)


def _map_kesehatan_jiwa(skr: dict) -> dict[str, Any]:
    """ASIK Kesehatan Jiwa ← EPUS PHQ-4 per-item answers (4 questions, score→
    frequency). Empty when the screening / JS-extracted answers are absent."""
    phq = skr.get("skrining_phq_4") or {}
    out: dict[str, Any] = {}
    for norm, asik_label in _JIWA_Q:
        v = phq.get("q::" + norm)
        if v is None:
            continue
        lbl = _PHQ_FREQ.get(str(v).strip())
        if lbl:
            out[asik_label] = lbl
    return out


def _enrich_payudara(skr: dict) -> dict[str, Any]:
    """Skrining Kanker Payudara from the EPUS payudara screening. The getlist
    record's ``kesimpulan`` carries the SADANIS result as a plain label
    ("Normal" / "Ditemukan benjolan" / "Curiga kanker") that maps 1:1 to the ASIK
    SADANIS options. The edit-page ``hasil_usg`` (Normal / Simple cyst / Non
    simple cyst — the ASIK USG options) is captured by the scraper only when USG
    was actually performed; verified live 2026-06-05."""
    p = skr.get("payudara") or {}
    # SADANIS ← record `kesimpulan` (plain label). NOT the edit-page `hasil_sadanis`,
    # which is a SNOMED code (e.g. "290084006"), not an ASIK option.
    sad = _clean_text(p.get("kesimpulan"))
    usg = _clean_text(p.get("hasil_usg"))
    out: dict[str, Any] = {}
    if sad:
        out["Pemeriksaan yang dilakukan"] = "SADANIS"
        out["Hasil pemeriksaan SADANIS"] = sad
    if usg:
        out.setdefault("Pemeriksaan yang dilakukan", "USG Payudara")
        out["Hasil pemeriksaan USG Payudara"] = usg
    return out


def _skrining_ekg(skr: dict) -> str | None:
    """EPUS ``resiko_penyakit_jantung`` EKG result → ASIK 'Hasil Pemeriksaan
    EKG' (Normal / Abnormal). The value is the edit-page ``SkriningJantung[ekg_v2]``
    control (verified live, jaksel + kotatangerang 2026-06-05: value 1 =
    "Normal"); the getlist record carries no EKG field. A fallback for the EKG
    result alongside PTM > Kardiovaskular."""
    j = skr.get("resiko_penyakit_jantung") or {}
    raw = (_clean_text(j.get("SkriningJantung[ekg_v2]"))
           or _clean_text(j.get("ekg_v2")) or _clean_text(j.get("ekg")))
    if not raw:
        return None
    s = raw.lower()
    if "abnormal" in s or "tidak normal" in s or "kelainan" in s:
        return "Abnormal"
    if "normal" in s:
        return "Normal"
    return None


# EPUS PUMA screening per-item answers (pernah_merokok / napas_pendek / dahak /
# batuk / pemeriksaan_fungsi_paru, applied via JS → captured by
# patient_scraper._extract_js_answers) → the 5 ASIK PPOK questions. A direct CKG
# source that fills the questions when PTM > Faktor Risiko (the primary source in
# _map_ppok_puma) left them blank. The "Hasil Skor Kuesioner PUMA" score field is
# NOT on the live ASIK form (see _map_ppok_puma) — never emitted.
_PUMA_PPOK: tuple[tuple[str, str, bool], ...] = (
    ("pernah_merokok", "Apakah anda sedang/mempunyai riwayat merokok?", True),
    ("napas_pendek",
     "Apakah Anda pernah merasa napas pendek ketika berjalan lebih cepat pada jalan yang datar atau pada jalan yang sedikit menanjak?", False),
    ("dahak",
     "Apakah Anda biasanya mempunyai dahak yang berasal dari paru atau kesulitan mengeluarkan dahak saat Anda sedang tidak menderita selesma/flu?", False),
    ("batuk",
     "Apakah Anda biasanya batuk saat sedang tidak menderita selesma/flu?", False),
    ("pemeriksaan_fungsi_paru",
     "Apakah Dokter atau tenaga medis lainnya pernah meminta Anda untuk melakukan pemeriksaan spirometri atau peak flow meter (meniup ke dalam suatu alat) untuk mengetahui fungsi paru?", False),
)


def _puma_screening_answers(skr: dict) -> dict[str, Any]:
    """EPUS PUMA screening (0/1 per item) → ASIK PPOK question answers. merokok
    uses 'Iya' (matching _smoking_to_asik); the rest 'Ya'/'Tidak' (_yatidak)."""
    p = skr.get("puma") or {}
    out: dict[str, Any] = {}
    for fld, label, is_merokok in _PUMA_PPOK:
        s = str(p.get(fld)).strip() if p.get(fld) is not None else None
        if s == "1":
            out[label] = "Iya" if is_merokok else "Ya"
        elif s == "0":
            out[label] = "Tidak"
    return out


def _skilas_yn(skilas: dict, field: str) -> str | None:
    """EPUS skilas item → 'Ya'/'Tidak'. `_skrining_index` gives the edit-page
    label ('Ya'/'Tidak') when present, else the getlist record code ('1'/'0')."""
    v = skilas.get(field)
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("ya", "iya", "1", "true"):
        return "Ya"
    if s in ("tidak", "0", "false"):
        return "Tidak"
    return None


def _mobilisasi_answer(v: Any) -> str | None:
    """EPUS skilas ``mobilisasi_tidak`` → ASIK "dapat berdiri 5x?" answer.
    The EPUS form question is POSITIVE (verified live, jaksel + kotatangerang
    2026-06-05): radio value 0 = "Ya"/dapat, value 1 = "Tidak"/tidak-dapat — so
    the raw code is INVERTED relative to the symptom-style skilas fields, and a
    plain `_skilas_yn` would mis-map a code-only value (code "1" -> "Ya"). Accept
    either the edit-page label ("Ya"/"Tidak") or the getlist record code ("0"/"1")."""
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("ya", "iya", "true"):
        return "Ya"
    if s in ("tidak", "false"):
        return "Tidak"
    if s == "0":          # value 0 = dapat berdiri
        return "Ya"
    if s == "1":          # value 1 = tidak dapat berdiri
        return "Tidak"
    return None


# ASIK SKILAS labels are byte-exact from live ASIK data (15+ lansia patients,
# 2026-06-04 — see RESEARCH_STATUS). ALL SKILAS sub-forms are mapped from the
# EPUS `skilas` screening:
#   - Gejala Depresi     ← depresi_terganggu / depresi_minat
#   - Malnutrisi         ← malnutrisi_badanberkurang / _makan / _lila
#   - Mobilisasi         ← mobilisasi_tidak via _mobilisasi_answer (EPUS question is
#                          POSITIVE "dapat berdiri 5x?": value 0="Ya", 1="Tidak",
#                          verified live jaksel+kotatangerang 2026-06-05 — code is
#                          inverted vs the symptom-style fields, handled explicitly)
#   - Penurunan Kognitif ← the 4 EPUS checkboxes (verified from the live EPUS form
#     labels, /skriningskilas/edit): the recall pair
#       harus_diingat           = "Dapat mengulang kata yang harus diingat"  (recall PASS)
#       kognitif_tidakmengulang = "Tidak dapat mengulang ketiga kata"        (recall FAIL)
#     answers ASIK's two recall questions (EPUS does not split immediate vs
#     delayed recall, so the single recall outcome fills both Q1 + Q3), and the
#     orientation pair
#       dijawab_tepat      = "Semua pertanyaan dijawab tepat"  → "Benar semua"
#       kognitif_salahsatu = "Salah pada salah satu pertanyaan"→ "Salah satu/Dua"
#     fills the 3-option orientation question. ASIK's "Tidak Tahu" has no EPUS
#     source. Conditional-fill: a value is emitted ONLY when a box is ticked, so
#     a blank/un-ticked EPUS screening leaves the ASIK field blank.
_SKILAS_DEPRESI = "SKILAS Pemeriksaan Gejala Depresi - Lansia"
_SKILAS_MALNUTRISI = "SKILAS Malnutrisi"
_SKILAS_KOGNITIF = "SKILAS Penurunan Kognitif - Lansia"
_KOG_Q1 = "Apakah dapat mengingat tiga kata: bunga, pintu, nasi (contoh)?"
_KOG_Q2 = ("Tanggal berapakah hari ini secara lengkap (tanggal/bulan/tahun)? "
           "atau- Dimanakah Anda saat ini (Puskesmas, rumah, klinik, dll)?")
_KOG_Q3 = "Apakah peserta dapat mengingat tiga kata sebelumnya?"


def _map_skilas(skr: dict) -> dict[str, dict[str, Any]]:
    s = skr.get("skilas") or {}
    out: dict[str, dict[str, Any]] = {}
    dep = {}
    q = _skilas_yn(s, "depresi_terganggu")
    if q is not None:
        dep["Apakah dalam 2 minggu terakhir Anda merasa sedih, tertekan, atau putus asa?"] = q
    q = _skilas_yn(s, "depresi_minat")
    if q is not None:
        dep["Apakah dalam 2 minggu terakhir Anda sedikit minat atau kesenangan dalam melakukan sesuatu?"] = q
    if dep:
        out[_SKILAS_DEPRESI] = dep
    mal = {}
    for fld, label in (
        ("malnutrisi_badanberkurang",
         "Apakah berat badan Anda berkurang >3 kg dalam 3 bulan terakhir atau pakaian menjadi lebih longgar?"),
        ("malnutrisi_makan",
         "Apakah Anda hilang nafsu makan Atau mengalami kesulitan makan (misal batuk atau tersedak saat makan, menggunakan selang makan/sonde)?"),
        ("malnutrisi_lila", "Apakah ukuran lingkar lengan atas (LiLA) <21 cm?"),
    ):
        q = _skilas_yn(s, fld)
        if q is not None:
            mal[label] = q
    if mal:
        out[_SKILAS_MALNUTRISI] = mal
    # Mobilisasi — see _mobilisasi_answer: the EPUS question is POSITIVE
    # ("dapat berdiri 5x?", value 0="Ya" / 1="Tidak"), so its code is inverted
    # vs the symptom-style skilas fields and must NOT go through _skilas_yn.
    mob = _mobilisasi_answer(s.get("mobilisasi_tidak"))
    if mob is not None:
        out["SKILAS Mobilisasi - Lansia"] = {
            "Tes Berdiri di kursi: Berdiri dari kursi lima kali tanpa bantuan tangan. "
            "Apakah orang tersebut dapat berdiri dari kursi utuh sebanyak lima kali dalam 14 detik ?": mob
        }
    # Penurunan Kognitif — EPUS records 4 checkboxes (see note above). Map each
    # ticked box per its label; emit nothing for un-ticked boxes (blank stays blank).
    kog: dict[str, Any] = {}
    if _skilas_yn(s, "harus_diingat") == "Ya":              # "Dapat mengulang kata…"
        kog[_KOG_Q1] = "Ya"
        kog[_KOG_Q3] = "Ya"
    elif _skilas_yn(s, "kognitif_tidakmengulang") == "Ya":  # "Tidak dapat mengulang ketiga kata"
        kog[_KOG_Q1] = "Tidak"
        kog[_KOG_Q3] = "Tidak"
    if _skilas_yn(s, "dijawab_tepat") == "Ya":              # "Semua pertanyaan dijawab tepat"
        kog[_KOG_Q2] = "Benar semua"
    elif _skilas_yn(s, "kognitif_salahsatu") == "Ya":       # "Salah pada salah satu pertanyaan"
        kog[_KOG_Q2] = "Salah satu/Dua"
    if kog:
        out[_SKILAS_KOGNITIF] = kog
    return out


# EPUS ADL (Indeks Barthel Modifikasi) → ASIK "Pemeriksaan Gangguan
# Fungsional/Barthel Index - Lansia". EPUS's getlist record carries the 10
# items as standard 0/1/2/3 scores (verified: all-max → total_skor 20). The
# per-score ASIK option labels below are byte-exact from live ASIK data (1401
# lansia, incl. impaired patients, 2026-06-04 — RESEARCH_STATUS); the rare
# 0-score labels not seen in that scan use the canonical Kemenkes Barthel
# wording. EPUS field name → (ASIK question label, {score: ASIK option}).
_BARTHEL: dict[str, tuple[str, dict[str, str]]] = {
    "mengendalikan_rangsang_bab": (
        "Dapat mengendalikan rangsang buang air besar (BAB)?",
        {"0": "Tidak terkendali/tak teratur (perlu pencahar)",
         "1": "Kadang-kadang tak terkendali (1 x / minggu)",
         "2": "Terkendali teratur"}),
    "mengendalikan_rangsang_bak": (
        "Dapat mengendalikan rangsang berkemih/buar air kecil (BAK)?",
        {"0": "Tak terkendali atau pakai kateter",
         "1": "Kadang-kadang tak terkendali (hanya 1 x / 24 jam)",
         "2": "Mandiri"}),
    "membersihkan_diri": (
        "Membersihkan diri (seka wajah, sisir rambut, sikat gigi)?",
        {"0": "Butuh pertolongan orang lain", "1": "Mandiri"}),
    "penggunaan_wc": (
        "Penggunaan jamban (keluar masuk jamban, melepas/memakai celana, membersihkan, menyiram)?",
        {"0": "Tergantung pertolongan orang lain",
         "1": "Perlu pertolongan pada beberapa kegiatan tetapi dapat mengerjakan sendiri beberapa kegiatan yang lain",
         "2": "Mandiri"}),
    "makan_minum": (
        "Makan dan Minum (jika makan harus berupa potongan, dianggap dibantu)",
        {"0": "Tidak mampu", "1": "Perlu ditolong memotong makanan", "2": "Mandiri"}),
    "bergerak_ke_dari_tempat_tidur": (
        "Berubah sikap dari berbaring ke duduk",
        {"0": "Tidak mampu", "1": "Perlu banyak bantuan untuk bisa duduk (2 orang)",
         "2": "Bantuan minimal 1 orang", "3": "Mandiri"}),
    "berjalan_tempat_rata": (
        "Berpindah/berjalan",
        {"0": "Tidak mampu", "1": "Bisa (pindah) dengan kursi roda",
         "2": "Bantuan minimal 1 orang", "3": "Mandiri"}),
    "berpakaian": (
        "Memakai baju",
        {"0": "Tergantung orang lain", "1": "Sebagian dibantu (misalnya: mengancing baju)",
         "2": "Mandiri"}),
    "naik_turun_tangga": (
        "Naik turun tangga",
        {"0": "Tidak mampu", "1": "Butuh pertolongan", "2": "Mandiri"}),
    "mandi": ("Mandi", {"0": "Tergantung orang lain", "1": "Mandiri"}),
}


# EPUS ``mini_cog`` screening → live "Penurunan Kognitif - Tindak Lanjut (Mini
# Cog-Clock Draw)". Only the clock-draw and delayed-recall questions have live
# inputs with fully-captured option strings; the 3-word registration Q is a
# "SUDAH DITANYAKAN" marker (no source) and Interpretasi is computed. The two
# labels are byte-exact from asik_form_mapping.json (curly quotes via “/
# ”). 0-data in PKM Tebet — unit-mapped for when the instrument fills.
_MINICOG_CLOCK_Q = (
    "Katakan seluruh frase berikut sesuai urutannya:  "
    "“Tolong gambar sebuah jam pada lembar ini. Mulailah dengan menggambar "
    "sebuah lingkaran besar. Kemudian, tuliskan angka-angka pada lingkaran dan "
    "atur jarum jam mengarah pukul 11:10 (11 lewat 10 menit).”Bila subjek "
    "tidak dapat menyelesaikan gambar jam dalam waktu 3 menit, hentikan "
    "pemeriksaan langkah ini dan lanjut ke langkah ke-3.\""
)
_MINICOG_RECALL_Q = (
    "Mintalah pasien untuk MENGULANG 3 kata yang disebutkan pada pertanyaan no 1"
)
_MINICOG_RECALL = {
    "tidak tepat": "Tidak dapat mengingat/mengulang kata",
    "tepat 1 kata": "Benar 1 kata",
    "tepat 2 kata": "Benar 2 Kata",
    "tepat 3 kata": "Benar semua kata",
}


def _norm_opt(v: Any) -> str:
    """Fold an option label for tolerant matching: en/em-dash→'-', decimal
    comma→'.', drop all whitespace, lowercase. Bridges the punctuation/spacing/
    case drift between EPUS option text and our lookup keys ONLY — genuine
    wording differences are mapped explicitly in the spec dicts, not fuzzed."""
    t = _clean_text(v) or ""
    t = t.replace("–", "-").replace("—", "-").replace(",", ".")
    return "".join(t.split()).lower()


def _screen_pick(screen: dict, *keys: str) -> Any:
    """First non-empty value among `keys` in a flattened screening dict."""
    for k in keys:
        val = screen.get(k)
        if val not in (None, ""):
            return val
    return None


# EPUS `sppb` screening (Short Physical Performance Battery) → ASIK "Mobilisasi -
# Pemeriksaan Lanjutan (SPPB)". EPUS stores each item's SELECTED OPTION TEXT in
# the edit-page detail, keyed by the raw input name `SkriningSppb[<field>]` (the
# getlist record may carry a stripped `<field>` code — plain-key fallback, but a
# code never matches a label so it degrades to blank). EPUS labels vs ASIK
# options differ in punctuation (en-dash/comma vs hyphen/dot, "<3" vs "< 3"), so
# each EPUS label is matched tolerantly (_norm_opt) and mapped to the BYTE-EXACT
# ASIK option from asik_form_mapping.json.
# ⚠️ These ASIK option strings are Padanan-Excel/mapping-JSON sourced, NOT
# verified against the live ASIK <select> DOM (SurveyJS renders options lazily;
# the scraper reads only the selected value). A byte-check vs the live DOM is a
# pending finishing step. 0-data in PKM Tebet — SAFE-FAIL: an unmatched value
# emits nothing (nakes fills), a byte-mismatch just means no sync, never
# corruption. EPUS field → (ASIK question label, {EPUS option: ASIK option}).
_SPPB: dict[str, tuple[str, dict[str, str]]] = {
    "berdampingan": (
        "Tes keseimbangan: berdiri selama 10 detik dengan kaki di masing-masing : Berdiri berdampingan",
        {"Bertahan 10 detik": "Bertahan 10 detik",
         "Tidak bertahan 10 detik": "Tidak bertahan 10 detik"}),
        # ASIK has no "Tidak dilakukan" option for berdampingan → left blank.
    "semitandem": (
        "Tes keseimbangan: berdiri selama 10 detik dengan kaki di masing-masing : Berdiri semi tandem",
        {"Bertahan 10 detik": "Bertahan 10 detik",
         "Tidak bertahan 10 detik": "Tidak bertahan 10 detik",
         "Tidak dilakukan": "Tidak dilakukan"}),
    "tandem": (
        "Tes keseimbangan: berdiri selama 10 detik dengan kaki di masing-masing : Berdiri Tandem",
        {"Bertahan 10 detik": "Bertahan 10 detik",
         "Bertahan 3 – 9,99 detik": "Bertahan 3 - 9.99 detik",
         "Bertahan <3 detik": "Bertahan < 3 detik"}),
        # ASIK has no "Tidak dilakukan" option for tandem → left blank.
    "kecepatan": (
        "tes kecepatan berjalan: Waktu untuk berjalan sejauh empat meter",
        {"<4,82 detik": "4,82 detik",
         "4,82 detik – 6,20 detik": "4.83 - 6.20 detik",
         "6,21 detik – 8,70 detik": "6.21 - 8.70 detik",
         ">8,70 detik": ">8,70 detik"}),
    "berdiri": (
        "Tes berdiri dari kursi: Waktu untuk bangkit dari kursi lima kali",
        {"<11,19 detik": "<11.19 detik",
         "11,2 – 13,69 detik": "11.2 - 13,69 detik",
         "13,7 – 16,69 detik": "13.7 - 16.69 detik",
         "16,7 – 59,9 detik": "16.7 - 59.9 detik"}),
}


# EPUS `pengkajian_nutrisi` screening (Short-Form MNA) → ASIK "Skrining
# Malnutrisi - Pemeriksaan Lanjutan (MNA-SF)". Same mechanism as _SPPB (detail
# carries the selected option TEXT, keyed by the PLAIN input name here). EPUS vs
# ASIK wording diverges for several items (mobilitas / neuropsikologis / IMT top
# band), so every option is mapped explicitly.
# ⚠️ TWO ASIK params are INCOMPLETE in the mapping JSON — their top-scoring
# "normal / no-reduction" option is genuinely absent from the repo (never
# DOM-captured): asupan makanan (PPM00000131, no "nafsu makan biasa/normal") and
# penurunan BB (PPM00000134, no "tidak ada penurunan BB"). For those the EPUS
# "normal" value is intentionally left UNMAPPED → blank (nakes fills). Every
# other option is byte-exact from asik_form_mapping.json but likewise NOT
# live-DOM-verified. EPUS captures no lingkar-betis (IMT-only), so that ASIK item
# is never emitted. 0-data; SAFE-FAIL (see _SPPB note).
_MNA: dict[str, tuple[str, dict[str, str]]] = {
    "penurunan_asupan_makanan": (
        "Apakah anda mengalami penurunan asupan makanan dalam 3 bulan terakhir "
        "disebabkan kehilangan nafsu makan, gangguan saluran cerna, kesulitan "
        "mengunyah atau menelan?",
        {"Nafsu makan yang sangat berkurang": "Nafsu Makan Yang Sangat Berkurang",
         "Nafsu makan sedikit berkurang (sedang)": "Nafsu Makan Sedikit Berkurang"}),
        # "Nafsu makan biasa saja" (normal) → no ASIK option (missing top score) → blank.
    "penurunan_berat_badan": (
        "Penurunan berat badan dalam tiga bulan terakhir ?",
        {"Penurunan berat badan lebih dari 3 kg": "Penurunan BB > 3 Kg",
         "Tidak tahu": "Tidak Tahu",
         "Penurunan berat badan 1-3 kg": "Penurunan BB antara 1 - 3 Kg"}),
        # "Tidak ada penurunan berat badan" → no ASIK option (missing top score) → blank.
    "mobilitas": (
        "Kemampuan melakukan mobilitas ?",
        {"Harus berbaring di tempat tidur atau menggunakan kursi roda":
            "Harus berbaring di tempat tidur atau menggunakan kursi roda",
         "Bisa keluar dari tempat tidur atau kursi roda, tetapi tidak bisa keluar rumah":
            "Bisa bangun dari tempat tidur atau kursi roda, tetapi tidak bisa keluar rumah",
         "Bisa keluar rumah": "Bisa bepergian keluar rumah"}),
    "stres_psikologis_penyakit": (
        "Menderita stress psikologis atau penyakit akut dalam tiga bulan terakhir ?",
        {"Ya": "Ya", "Tidak": "Tidak"}),
    "masalah_neuropsikologi": (
        "Mengalami masalah neuropsikologis?",
        {"Demensia berat atau depresi berat": "Dementia atau depresi berat",
         "Demensia ringan": "Demensia/kepikunan ringan",
         "Tidak ada masalah psikologis": "Tidak ada masalah psikologis"}),
    "imt": (
        "Berapa Nilai IMT (Indeks Massa Tubuh)?",
        {"IMT < 19": "IMT <19",
         "IMT 19 - < 21": "IMT 19 - <21",
         "IMT 21 - < 23": "IMT 21 - <23",
         "IMT 23 atau lebih": "IMT >= 23"}),
}


def _map_dropdown_form(
    screen: dict, spec: dict[str, tuple[str, dict[str, str]]], *, wrap: str | None = None
) -> dict[str, Any]:
    """Map an EPUS screening's selected-option-text detail → an ASIK dropdown
    form. Each EPUS option is matched tolerantly (_norm_opt) to its byte-exact
    ASIK option. `wrap` is the input-name model wrapper (e.g. 'SkriningSppb')
    when the form brackets its field names; the plain name is a fallback."""
    out: dict[str, Any] = {}
    for base, (label, options) in spec.items():
        keys = (f"{wrap}[{base}]", base) if wrap else (base,)
        raw = _screen_pick(screen, *keys)
        if raw is None:
            continue
        n = _norm_opt(raw)
        for epus_opt, asik_opt in options.items():
            if _norm_opt(epus_opt) == n:
                out[label] = asik_opt
                break
    return out


def _map_barthel(skr: dict) -> dict[str, Any]:
    """EPUS adl screening (10 Barthel scores in the getlist record) → the ASIK
    Barthel form, coercing each score to its exact ASIK option label."""
    a = skr.get("adl") or {}
    out: dict[str, Any] = {}
    for fld, (label, score_map) in _BARTHEL.items():
        v = a.get(fld)
        if v is None:
            continue
        opt = score_map.get(str(v).strip())
        if opt:
            out[label] = opt
    return out


# ─── public entry point ───────────────────────────────────────────────────


def epus_to_asik(epus: dict) -> ASIK_Result:
    """Convert one decrypted EPUS patient blob to ASIK form-shaped dict.

    Returned dict only contains forms the patient is eligible for given
    age/gender/chronic-disease flags. Each form's value is the ASIK
    field-name → value mapping; ``None`` means the field is left blank
    (legal — ASIK accepts partial submissions).
    """
    pasien = epus.get("data_pasien") or {}
    gender = _gender_norm(pasien.get("Jenis Kelamin"))
    years = _years_from_umur(pasien.get("Umur"))
    flags = _detect_chronic_flags(epus)
    skr = _skrining_index(epus)  # EPUS Formulir Skrining battery (may be {})

    out: ASIK_Result = {}

    # Identitas survives even if klaster is undecidable — it's a synthetic
    # form for the merge prompt's identitas_pasien comparison, gated only
    # on data_pasien availability.
    identitas = _map_identitas(epus)
    if identitas:
        out["identitas_pasien"] = identitas

    if gender is None or years is None:
        # Cannot decide klaster without these — return identitas-only result.
        return out

    # ── Pediatric (under-18): a DISTINCT ASIK form battery. Emit the pediatric
    #    forms and RETURN — never fall through to the adult/lansia cluster below.
    #    (Before 2026-06-02 a child with valid age+gender was mis-emitted as
    #    "Demografi Dewasa" + the full adult battery; ~9% of matched patients
    #    are under-18.)
    if years < 18:
        out.update(_pediatric_forms(epus, gender, years, flags))
        return out

    # Laboratorium tab results (test-leaf → Hasil) — feeds the lab-sourced
    # adult/female forms below. Read once; degrades to {} when absent.
    lab_results = _lab_results(epus)

    # ── Dewasa cluster — 3 live forms per the "Skrining Gizi, Tekanan
    # Darah, dan Gula Darah" paket grouping. Each form gets its own EPUS
    # slice; one EPUS source can flow into multiple forms when applicable.
    out["Tekanan Darah Dewasa Lansia"] = _map_tekanan_darah_dewasa_lansia(epus, flags)
    out["Pemeriksaan Gula Darah Dewasa Lansia"] = (
        _map_pemeriksaan_gula_darah_dewasa_lansia(epus, flags)
    )
    gizi_form, gizi_fields = _map_gizi_bb_tb_lp(epus, gender)
    out[gizi_form] = gizi_fields

    # ── Skrining Klaster = primary source (PKM decision 2026-08) ─────────
    # The puskesmas now defaults every ASIK answer to the CKG "Formulir
    # Skrining Klaster" page and only falls back to the Pelayanan modules
    # when the screening did not capture it. So a screening value OVERRIDES
    # the module-derived value assembled above. Field keys verified live
    # against the getlist record + /edit detail (tools/skrining_inventory.py,
    # jaksel 2026-08-12): hipertensi.riwayat_pribadi / diabetes_melitus
    # anamnesis[...] + hasil_gd{s,p,2pp} arrive as edit-page `detail`.
    ht_riwayat = _clean_text((skr.get("hipertensi") or {}).get("riwayat_pribadi"))
    if ht_riwayat in ("Ya", "Tidak"):
        out["Tekanan Darah Dewasa Lansia"][
            "Apakah Anda pernah dinyatakan tekanan darah tinggi?"
        ] = ht_riwayat

    dm = skr.get("diabetes_melitus") or {}
    dm_riwayat = _clean_text(dm.get("anamnesis[Riwayat Pribadi Diabetes Melitus]"))
    if dm_riwayat in ("Ya", "Tidak"):
        out["Pemeriksaan Gula Darah Dewasa Lansia"][
            "Apakah Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?"
        ] = dm_riwayat
    for _asik_field, _skr_field in (
        ("Gula Darah Sewaktu (GDS) (mg/dl)", "hasil_gds"),
        ("Gula Darah Puasa (GDP) (mg/dl)", "hasil_gdp"),
        ("Gula Darah 2 Jam PP (mg/dl)", "hasil_gd2pp"),
    ):
        _gd = _num(dm.get(_skr_field))
        if _gd is not None:
            out["Pemeriksaan Gula Darah Dewasa Lansia"][_asik_field] = _gd

    # PPOK (Skrining PUMA) — live form, 5-6 Q (Q6 conditional on smoking).
    # Verification §4 shows 0/8 patients <40 fill this form. Gate >= 40.
    if years >= 40:
        ppok = _map_ppok_puma(epus, years)
        # Skrining-klaster primary (PKM 2026-08): the EPUS PUMA screening's
        # per-item answers OVERRIDE the PTM Faktor-Risiko values for the 5 PPOK
        # questions when the screening captured them (PTM remains the fallback
        # for whatever the screening left blank).
        for label, val in _puma_screening_answers(skr).items():
            ppok[label] = val
        out["Pemeriksaan PPOK (Skrining PUMA)"] = ppok

    demografi_form, demografi_fields = _map_demografi(epus, gender, years)
    out[demografi_form] = demografi_fields

    # Skrining Telinga & Mata — live forms split by age band.
    telmat_form = _map_telinga_mata(years)
    out[telmat_form] = _map_telinga_mata_fields(epus, include_pupil=(years >= 40))

    # TB risk forms — same cough Q lives on TWO live forms; populate both.
    out.update(_map_faktor_risiko_tb(epus, flags))
    out["Pemeriksaan Tuberkulosis (Dewasa & Lansia)"] = (
        _map_pemeriksaan_tuberkulosis(epus, flags)
    )

    out["Pemeriksaan HIV"] = _map_hiv(flags, epus)
    out["Pemeriksaan Sifilis"] = _map_sifilis(flags)
    out["Pemeriksaan Hepatitis"] = _map_hepatitis(flags)
    out["Perilaku Merokok"] = _map_perilaku_merokok(epus)
    out["Pemeriksaan Kadar CO (Hanya Diisi Apabila Merokok atau Terpapar Asap Rokok)"] = (
        _map_pemeriksaan_kadar_co(epus)
    )
    out["Tingkat Aktivitas Fisik (sedang dan berat)"] = _map_tingkat_aktivitas_fisik(epus)

    # ── Always-emit shells (no EPUS source, but live ASIK runs them) ────
    # Live form names per audit 2026-04-29.
    for shell in (
        "Pemeriksaan Penyakit Frambusia (untuk daerah endemis atau berisiko frambusia)",
        "Pemeriksaan Penyakit Kusta",
        "Pemeriksaan Penyakit Skabies",
        "Hati",
    ):
        out[shell] = {}

    # Kesehatan Jiwa — the live ASIK form is the 4 PHQ-4 frequency questions
    # (verified 2026-06-05); EPUS's PHQ-4 form holds the same 4 + the 0-3 scale.
    # The scraper now extracts the JS-rendered per-item answers, so we fill all 4.
    out["Kesehatan Jiwa"] = _map_kesehatan_jiwa(skr)

    # Dental — always emitted (live ASIK runs them for everyone); pre-filled
    # from Anamnesa > Pemeriksaan Dasar Gigi when present, else empty shell.
    dental = _map_dental(epus)
    out["Skrining Karies dan Gigi Hilang"] = dental.get("Skrining Karies dan Gigi Hilang", {})
    out["Skrining Penyakit Periodontal"] = dental.get("Skrining Penyakit Periodontal", {})

    # ── Age-gated lab forms (live names, audit 2026-04-29) ──────────────
    has_ht_or_dm = flags["clinical"]["hipertensi"] or flags["clinical"]["diabetes"]
    if years >= 40:
        ptm_fields = ((epus.get("tabs") or {}).get("PTM") or {}).get("fields", {}) or {}
        hati = ptm_fields.get("Fungsi Hati") or {}
        ginjal = ptm_fields.get("Ginjal") or {}
        lipid = ptm_fields.get("Profil Lipid") or {}

        # POCT Lipid Panel — 4 Q live.
        lipid_form: dict[str, Any] = {}
        chol_total = _num(lipid.get("Cholesterol Total"))
        if chol_total is not None:
            lipid_form["Kolesterol Total"] = chol_total
        hdl = _num(lipid.get("HDL"))
        if hdl is not None:
            lipid_form["HDL"] = hdl
        ldl = _num(lipid.get("LDL"))
        if ldl is not None:
            lipid_form["LDL"] = ldl
        trig = _num(lipid.get("Trigliserida"))
        if trig is not None:
            lipid_form["Trigliserida"] = trig
        out[
            "POCT Lipid Panel (Khusus usia >=40 thn dan penyandang HT dan/atau DM)"
        ] = lipid_form

        # Skrining Fungsi Ginjal <g> — 4 Q live: Kreatinin / Ureum / Usia /
        # e-LFG. Gendered variants in live ASIK.
        ginjal_form: dict[str, Any] = {
            "Hasil Pemeriksaan Kreatinin": _num(ginjal.get("Kreatinin")),
            "Hasil Pemeriksaan Ureum": _num(ginjal.get("Ureum")),
            "Nilai Hasil pemeriksaan (e-LFG (CKD-EPI))": _num(ginjal.get("eGFR")),
            "Usia": years,
        }
        ginjal_form_name = (
            "Skrining Fungsi Ginjal "
            + ("Perempuan" if gender == "Perempuan" else "Laki-Laki")
            + " (hanya untuk =>40 tahun dengan risiko HT DM)"
        )
        out[ginjal_form_name] = ginjal_form

        # Skrining Kerusakan Ginjal — 2 Q live. Konsentrasi Albumin Urin ←
        # Laboratorium tab Microalbuminuria result; Konsentrasi Kreatinin Urin
        # has no EPUS source (EPUS carries only serum Kreatinin, mapped above).
        kerusakan_ginjal_form: dict[str, Any] = {}
        albumin_urin = _lab_num(lab_results, _LAB_ALBUMIN_URIN)
        if albumin_urin is not None:
            kerusakan_ginjal_form["Konsentrasi Albumin Urin"] = albumin_urin
        out[
            "Skrining Kerusakan Ginjal (hanya untuk =>40 tahun dengan risiko HT DM)"
        ] = kerusakan_ginjal_form

        # Pemeriksaan Fibrosis/Sirosis Hati — 2 Q live: SGOT (PTM) + Trombosit
        # (Laboratorium tab hematology result).
        sgot = _num(hati.get("SGOT"))
        fibrosis_form: dict[str, Any] = {}
        if sgot is not None:
            fibrosis_form["Nilai SGOT"] = sgot
        trombosit = _lab_num(lab_results, _LAB_TROMBOSIT)
        if trombosit is not None:
            fibrosis_form["Pemeriksaan Trombosit"] = trombosit
        out["Pemeriksaan Fibrosis/Sirosis Hati"] = fibrosis_form

    if years >= 45:
        # Skrining Kanker Paru forms — live form is gender-agnostic
        # (audit 2026-04-29 title "Skrining Kanker Paru (Usia =>45 thn)").
        out["Skrining Kanker Paru (Usia =>45 thn)"] = _map_skrining_kanker_paru(
            epus, flags, skr=skr, gender=gender, years=years
        )
        out["Penapisan Risiko Kanker Paru"] = _map_penapisan_kanker_paru(epus, flags, skr=skr)
        # Kanker Usus — split: risk form (2 Q populated) + tindak lanjut
        # form (3 Q, no EPUS source).
        out["Faktor Risiko Kanker Usus"] = _map_faktor_risiko_kanker_usus(epus)
        out["Pemeriksaan Lanjutan Kanker Usus"] = {}
        # Skrining Jantung gate: live ASIK runs for all >= 45 regardless
        # of HT/DM.
        out["Hasil Pemeriksaan - Skrining Jantung"] = _map_skrining_jantung_ekg(epus)
    elif has_ht_or_dm:
        out["Hasil Pemeriksaan - Skrining Jantung"] = _map_skrining_jantung_ekg(epus)
    # EKG also recorded in the resiko_penyakit_jantung screening — the primary
    # source for "Hasil Pemeriksaan EKG" per the PKM klaster-first decision
    # (2026-08); overrides the PTM Kardiovaskular result on the live Jantung form
    # when the screening captured it.
    jantung_ekg = _skrining_ekg(skr)
    if jantung_ekg and "Hasil Pemeriksaan - Skrining Jantung" in out:
        out["Hasil Pemeriksaan - Skrining Jantung"]["Hasil Pemeriksaan EKG"] = jantung_ekg

    if years >= 60:
        # Live Lansia battery — each instrument is its own form per audit
        # 2026-04-29. EPUS does not capture these today; shells only.
        # Names verified byte-for-byte against the live ASIK DOM
        # (Pekayon Jaya, 2026-05-29 dump) — the parens / slash / "SKILAS"
        # spellings are what the live forms use; the prior CSV-spec names
        # drifted and broke paket grouping + ASIK sync-back.
        for lansia_shell in (
            "SKILAS Mobilisasi - Lansia",
            "SKILAS Penurunan Kognitif - Lansia",
            "SKILAS Pemeriksaan Gejala Depresi - Lansia",
            "SKILAS Malnutrisi",
            "Pemeriksaan Gangguan Fungsional/Barthel Index - Lansia",
            "Mobilisasi - Pemeriksaan Lanjutan (SPPB)",
            "Skrining Malnutrisi - Pemeriksaan Lanjutan (MNA-SF)",
            "Penurunan Kognitif - Tindak Lanjut (AD-8 INA)",
            "Penurunan Kognitif - Tindak Lanjut (Mini Cog-Clock Draw)",
            "Pemeriksaan Gejala Depresi - Pemeriksaan Lanjutan",
        ):
            out[lansia_shell] = {}

        # Fill the SKILAS shells (Gejala Depresi, Malnutrisi, Mobilisasi,
        # Penurunan Kognitif) from the EPUS skilas screening when present.
        for fn, fields in _map_skilas(skr).items():
            if fields:
                out[fn] = fields
        # Barthel Index ← EPUS adl screening (10 scored items → ASIK labels).
        barthel = _map_barthel(skr)
        if barthel:
            out["Pemeriksaan Gangguan Fungsional/Barthel Index - Lansia"] = barthel

        # Penurunan Kognitif (Mini-Cog) — clock-draw ← gambar_jam (Normal→Benar /
        # Abnormal→Salah), delayed recall ← kata_yang_tepat_dua. 0-data; safe-fails
        # to blank if the screening ever carries codes instead of labels.
        mini = skr.get("mini_cog") or {}
        if mini:
            minicog: dict[str, Any] = {}
            jam = (_clean_text(mini.get("gambar_jam")) or "").lower()
            if jam:
                minicog[_MINICOG_CLOCK_Q] = "Salah" if "abnormal" in jam else "Benar"
            recall = _MINICOG_RECALL.get(
                (_clean_text(mini.get("kata_yang_tepat_dua")) or "").lower()
            )
            if recall:
                minicog[_MINICOG_RECALL_Q] = recall
            if minicog:
                out["Penurunan Kognitif - Tindak Lanjut (Mini Cog-Clock Draw)"] = minicog

        # SPPB / MNA-SF — Pemeriksaan Lanjutan dropdowns (klaster-primary). EPUS
        # stores the selected option TEXT; matched tolerantly to the byte-exact
        # ASIK option (see _SPPB / _MNA notes: Excel-sourced, NOT live-DOM-verified;
        # 2 MNA params miss their top "normal" option; 0-data; safe-fail).
        sppb = _map_dropdown_form(skr.get("sppb") or {}, _SPPB, wrap="SkriningSppb")
        if sppb:
            out["Mobilisasi - Pemeriksaan Lanjutan (SPPB)"] = sppb
        mnasf = _map_dropdown_form(skr.get("pengkajian_nutrisi") or {}, _MNA)
        if mnasf:
            out["Skrining Malnutrisi - Pemeriksaan Lanjutan (MNA-SF)"] = mnasf

    # ── Skrining Klaster primary — batch 2 (faktor_risiko / fungsi_ginjal /
    # kolorektal). faktor_risiko + fungsi_ginjal answers arrive as `q::<question>`
    # detail keys via the Vue viewData extractor (patient_scraper._extract_js_answers)
    # — populated after the next re-scrape. Field keys/values verified live
    # (tools/skrining_inventory.py + Vue recon, jaksel 2026-08-12).
    fr_screen = skr.get("faktor_risiko") or {}
    if "Perilaku Merokok" in out:
        merokok = _clean_text(fr_screen.get("q::apakah anda merokok dalam setahun terakhir ini"))
        if merokok in ("Ya", "Tidak"):
            out["Perilaku Merokok"]["Apakah Anda merokok dalam setahun terakhir ini?"] = merokok
        paparan = _clean_text(fr_screen.get(
            "q::apakah anda terpapar asap rokok atau menghirup asap rokok "
            "dari orang lain dalam sebulan terakhir"
        ))
        if paparan in ("Ya", "Tidak"):
            out["Perilaku Merokok"][
                "Apakah Anda terpapar asap rokok atau menghirup asap rokok "
                "dari orang lain dalam sebulan terakhir?"
            ] = paparan

    ginjal_screen = skr.get("fungsi_ginjal") or {}
    if ginjal_screen:
        ginjal_name = (
            "Skrining Fungsi Ginjal "
            + ("Perempuan" if gender == "Perempuan" else "Laki-Laki")
            + " (hanya untuk =>40 tahun dengan risiko HT DM)"
        )
        if ginjal_name in out:
            kreat = _num(ginjal_screen.get("q::kreatinin"))
            if kreat is not None:
                out[ginjal_name]["Hasil Pemeriksaan Kreatinin"] = kreat
            ureum = _num(ginjal_screen.get("q::ureum"))
            if ureum is not None:
                out[ginjal_name]["Hasil Pemeriksaan Ureum"] = ureum

    usus_screen = skr.get("kolorektal") or {}
    if "Faktor Risiko Kanker Usus" in out and usus_screen:
        fam = _screen_yn(usus_screen.get("riwayat_kanker_kolorektal"), "memiliki")
        if fam is not None:
            out["Faktor Risiko Kanker Usus"][
                "Apakah ada anggota keluarga Anda, yang pernah dinyatakan menderita "
                "kanker kolorektal atau kanker usus?"
            ] = fam
        usus_smoke = _screen_yn(usus_screen.get("riwayat_merokok"), "merokok")
        if usus_smoke is not None:
            out["Faktor Risiko Kanker Usus"]["Apakah Anda merokok?"] = usus_smoke

    # ── Skrining Klaster primary — batch 3 (Telinga & Mata) ─────────────
    # Both live ASIK fields are 2-option; the klaster screening carries a
    # per-eye / per-ear grade, so "any side abnormal → Curiga". Overrides the
    # PTM-derived value on the same Skrining Telinga dan Mata form.
    #   tajam penglihatan  ← penglihatan.tajam_kiri/tajam_kanan
    #   tajam pendengaran  ← skrining_indra_pendengaran.bisikan_telinga_kiri/kanan
    peng_screen = skr.get("penglihatan") or {}
    deng_screen = skr.get("skrining_indra_pendengaran") or {}
    if telmat_form in out:
        tajam = [v for v in (_clean_text(peng_screen.get("tajam_kiri")),
                             _clean_text(peng_screen.get("tajam_kanan"))) if v]
        if tajam:
            out[telmat_form]["Apa hasil skrining tajam penglihatan?"] = (
                "Normal (visus 6/6 - 6/12)"
                if all(v.lower().startswith("normal") for v in tajam)
                else "Curiga gangguan penglihatan (visus <6/12)"
            )
        bisik = [v for v in (_clean_text(deng_screen.get("bisikan_telinga_kiri")),
                             _clean_text(deng_screen.get("bisikan_telinga_kanan"))) if v]
        if bisik:
            if any("gangguan" in v.lower() for v in bisik):
                out[telmat_form]["Hasil pemeriksaan tajam pendengaran"] = "Curiga gangguan pendengaran"
            elif all(v.lower().startswith("normal") for v in bisik):
                out[telmat_form]["Hasil pemeriksaan tajam pendengaran"] = "Normal"
        # Pupil (Katarak) — only on the >=40 form. penglihatan.pemeriksaan_pupil_*
        # is "Positif"/"Negatif": Positif (white-pupil / red-reflex abnormal) →
        # Curiga Katarak, both Negatif → Normal. Overrides the PTM-Katarak value.
        if years >= 40:
            pupil = [v for v in (_clean_text(peng_screen.get("pemeriksaan_pupil_kiri")),
                                 _clean_text(peng_screen.get("pemeriksaan_pupil_kanan"))) if v]
            if pupil:
                out[telmat_form]["Hasil pemeriksaan pupil"] = (
                    "Curiga Katarak"
                    if any(v.lower().startswith("positif") for v in pupil)
                    else "Normal"
                )

    # ── Female-only screening ───────────────────────────────────────────
    out.update(_map_iva_sadanis(epus, gender, years))
    # Skrining Kanker Payudara — the EPUS payudara screening is a direct CKG
    # source (SADANIS/USG results); merge over any IVA-derived emission.
    if gender == "Perempuan":
        payudara_screen = _enrich_payudara(skr)
        if payudara_screen:
            out.setdefault("Skrining Kanker Payudara", {}).update(payudara_screen)
    if gender == "Perempuan" and years >= 30:
        out["Hasil Pemeriksaan HPV-DNA"] = {}
        # Live cervical-cancer gating form (confirmed live 2026-05-29, female
        # 30-69). Single Q `Apakah pernah melakukan hubungan intim/seksual?` —
        # no EPUS source, emit as shell so eligibility shows in the Convert tab.
        out["Kanker Leher Rahim"] = {}
        # ── Skrining Klaster primary — Serviks. The screening stores coded radio
        #    values (recon 2026-08-12): inspekulo 0=Normal/1=Curiga Kanker;
        #    hasil_iva 0=Positif/1=Negatif/2=Curiga Kanker; seksual 1=Ya/0=Tidak.
        #    Overrides the PTM-derived Inspekulo/IVA and fills the Kanker Leher
        #    Rahim gating Q (which had no EPUS source before).
        serviks = skr.get("skrining_resiko_kanker_serviks") or {}
        if serviks:
            _INSP = {"0": "Normal", "normal": "Normal", "1": "Curiga kanker",
                     "curiga kanker": "Curiga kanker", "curiga": "Curiga kanker"}
            _IVA = {"1": "Negatif", "negatif": "Negatif", "0": "Positif", "2": "Positif",
                    "positif": "Positif", "curiga kanker": "Positif", "curiga": "Positif"}
            insp = _INSP.get((_clean_text(serviks.get("inspekulo")) or "").lower())
            iva = _IVA.get((_clean_text(serviks.get("hasil_iva")) or "").lower())
            if insp or iva:
                iva_form = out.setdefault("Pemeriksaan Inspekulo dan IVA", {})
                if insp:
                    iva_form["Pemeriksaan Inspekulo"] = insp
                if iva:
                    iva_form["Pemeriksaan Inspeksi Visual Asam Asetat (IVA)"] = iva
            seks = {"1": "Ya", "ya": "Ya", "0": "Tidak", "tidak": "Tidak"}.get(
                (_clean_text(serviks.get("seksual")) or "").lower())
            if seks:
                out["Kanker Leher Rahim"]["Apakah pernah melakukan hubungan intim/seksual?"] = seks
    if gender == "Perempuan":
        # Pemeriksaan Calon Pengantin Perempuan — live form has 1 Q
        # (Kadar Hemoglobin) ← Laboratorium tab Hb result when present.
        catin_form: dict[str, Any] = {}
        hb = _lab_num(lab_results, _LAB_HEMOGLOBIN)
        if hb is not None:
            catin_form["Kadar Hemoglobin"] = hb
        out["Pemeriksaan Calon Pengantin Perempuan"] = catin_form
        # Riwayat Imunisasi Tetanus — fill from the EPUS skrining_imunisasi_dewasa
        # screening (PKM 2026-08). imunisasi_tetanus is 0=Belum,1=T1,…,5=T5. Per
        # PKM decision: T2 or higher ⇒ "minimal dua kali". Below T2 (Belum or T1)
        # stays blank — ASIK's dropdown has no "Belum/Tidak pernah" line, so it is
        # left for the nakes to fill ("belum imunisasi").
        tetanus_form: dict[str, Any] = {}
        imun = skr.get("skrining_imunisasi_dewasa") or {}
        t_val = _clean_text(imun.get("imunisasi_tetanus"))
        if t_val:
            m = re.search(r"([0-5])", t_val)
            if m and int(m.group(1)) >= 2:
                tetanus_form[
                    "Apakah anda pernah mendapatkan imunisasi tetanus minimal 2 kali? "
                    "(imunisasi tetanus biasanya didapatkan pada vaksin DPT saat bayi, "
                    "vaksin TT/Td saat usia sekolah dasar)"
                ] = "Pernah imunisasi tetanus minimal dua kali"
        out["Riwayat Imunisasi Tetanus(Status T) - Hanya untuk Catin"] = tetanus_form

    return out


# ─── EPUS-side breadcrumb table ───────────────────────────────────────────
#
# Static metadata: maps each ASIK form/field to the original EPUS path the
# value came from. Used by the merge task post-processor to overwrite the
# LLM's epus_question (which by default mirrors the ASIK slug since input 1
# is already in ASIK shape). Entry of None marks values that are computed
# from multiple EPUS sources (clinical-union flags, smoking pack-year
# bucket, etc.) where no single EPUS path applies.
#
# Must stay in sync with the per-form mappers above — adding a field to
# a mapper without an entry here means epus_question falls back to the
# ASIK slug.

EPUS_BREADCRUMBS: dict[str, dict[str, str | None]] = {
    "identitas_pasien": {
        "NIK": "Data Pasien > NIK",
        "Nama": "Data Pasien > Nama Pasien",
        "Tanggal Lahir": "Data Pasien > Tempat/Tgl Lahir",
        "Tempat Lahir": "Data Pasien > Tempat/Tgl Lahir",
        "Jenis Kelamin": "Data Pasien > Jenis Kelamin",
        "Alamat Domisili": "Data Pasien > Alamat",
    },
    # ── Klaster & Siklus Hidup screening battery (CKG forms, added 2026-06-04).
    #    Source path convention: `skrining_klaster > <key> > <field>`.
    "Kesehatan Jiwa": {
        # LIVE ASIK form = 4 PHQ-4 frequency questions (verified 2026-06-05).
        # EPUS's PHQ-4 form holds the same 4 (Vue viewData) → the scraper extracts
        # the per-item answers; score 0-3 → frequency label.
        "Dalam 2 minggu terakhir, seberapa sering anda kurang/ tidak bersemangat dalam melakukan kegiatan sehari-hari?":
            "skrining_klaster > skrining_phq_4 > PHQ-2 item 1 (skor→frekuensi)",
        "Dalam 2 minggu terakhir, seberapa sering anda merasa murung, tertekan, atau putus asa?":
            "skrining_klaster > skrining_phq_4 > PHQ-2 item 2 (skor→frekuensi)",
        "Dalam 2 minggu terakhir, seberapa sering anda merasa gugup, cemas, atau gelisah?":
            "skrining_klaster > skrining_phq_4 > GAD-2 item 1 (skor→frekuensi)",
        "Dalam 2 minggu terakhir, seberapa sering anda tidak mampu mengendalikan rasa khawatir?":
            "skrining_klaster > skrining_phq_4 > GAD-2 item 2 (skor→frekuensi)",
    },
    "SKILAS Pemeriksaan Gejala Depresi - Lansia": {
        "Apakah dalam 2 minggu terakhir Anda merasa sedih, tertekan, atau putus asa?":
            "skrining_klaster > skilas > depresi_terganggu",
        "Apakah dalam 2 minggu terakhir Anda sedikit minat atau kesenangan dalam melakukan sesuatu?":
            "skrining_klaster > skilas > depresi_minat",
    },
    "SKILAS Malnutrisi": {
        "Apakah berat badan Anda berkurang >3 kg dalam 3 bulan terakhir atau pakaian menjadi lebih longgar?":
            "skrining_klaster > skilas > malnutrisi_badanberkurang",
        "Apakah Anda hilang nafsu makan Atau mengalami kesulitan makan (misal batuk atau tersedak saat makan, menggunakan selang makan/sonde)?":
            "skrining_klaster > skilas > malnutrisi_makan",
        "Apakah ukuran lingkar lengan atas (LiLA) <21 cm?": "skrining_klaster > skilas > malnutrisi_lila",
    },
    "SKILAS Mobilisasi - Lansia": {
        "Tes Berdiri di kursi: Berdiri dari kursi lima kali tanpa bantuan tangan. "
        "Apakah orang tersebut dapat berdiri dari kursi utuh sebanyak lima kali dalam 14 detik ?":
            "skrining_klaster > skilas > mobilisasi_tidak",
    },
    "SKILAS Penurunan Kognitif - Lansia": {
        "Apakah dapat mengingat tiga kata: bunga, pintu, nasi (contoh)?":
            "skrining_klaster > skilas > harus_diingat / kognitif_tidakmengulang (recall pair)",
        "Tanggal berapakah hari ini secara lengkap (tanggal/bulan/tahun)? "
        "atau- Dimanakah Anda saat ini (Puskesmas, rumah, klinik, dll)?":
            "skrining_klaster > skilas > dijawab_tepat / kognitif_salahsatu (orientation pair)",
        "Apakah peserta dapat mengingat tiga kata sebelumnya?":
            "skrining_klaster > skilas > harus_diingat / kognitif_tidakmengulang (recall pair)",
    },
    "Pemeriksaan Gangguan Fungsional/Barthel Index - Lansia": {
        "Dapat mengendalikan rangsang buang air besar (BAB)?": "skrining_klaster > adl > mengendalikan_rangsang_bab",
        "Dapat mengendalikan rangsang berkemih/buar air kecil (BAK)?": "skrining_klaster > adl > mengendalikan_rangsang_bak",
        "Membersihkan diri (seka wajah, sisir rambut, sikat gigi)?": "skrining_klaster > adl > membersihkan_diri",
        "Penggunaan jamban (keluar masuk jamban, melepas/memakai celana, membersihkan, menyiram)?": "skrining_klaster > adl > penggunaan_wc",
        "Makan dan Minum (jika makan harus berupa potongan, dianggap dibantu)": "skrining_klaster > adl > makan_minum",
        "Berubah sikap dari berbaring ke duduk": "skrining_klaster > adl > bergerak_ke_dari_tempat_tidur",
        "Berpindah/berjalan": "skrining_klaster > adl > berjalan_tempat_rata",
        "Memakai baju": "skrining_klaster > adl > berpakaian",
        "Naik turun tangga": "skrining_klaster > adl > naik_turun_tangga",
        "Mandi": "skrining_klaster > adl > mandi",
    },
    # ── Pediatric (under-18) — see _pediatric_forms. Field labels are byte-exact
    #    against the live ASIK forms matched kids carry (audit 2026-06-02).
    "Skrining Pertumbuhan - Balita dan Anak Prasekolah 1-5 Tahun": {
        "Berat Badan Balita": "Anamnesa > Periksa Fisik > Berat Badan",
        "Pengukuran Tinggi Badan (cm)": "Anamnesa > Periksa Fisik > Tinggi Badan",
        "Posisi Pengukuran": "Anamnesa > Periksa Fisik > Cara Ukur Tinggi Badan",
    },
    "Skrining Pertumbuhan - Balita dan Anak Prasekolah 5-6 Tahun": {
        "Pengukuran Tinggi Badan (cm)": "Anamnesa > Periksa Fisik > Tinggi Badan",
    },
    "Gizi Anak Sekolah": {
        "Berat Badan": "Anamnesa > Periksa Fisik > Berat Badan",
        "Tinggi Badan": "Anamnesa > Periksa Fisik > Tinggi Badan",
    },
    "Tekanan Darah Anak dan Remaja": {
        "Tekanan Darah Sistol": "Anamnesa > Periksa Fisik > Sistole",
        "Tekanan Darah Diastol": "Anamnesa > Periksa Fisik > Diastole",
    },
    "Pemeriksaan Gula Darah Anak": {
        "Apakah Anak Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?":
            "PTM > Riwayat PTM pada Diri Sendiri > Penyakit Diabetes",
        "Gula Darah Sewaktu (GDS)": "PTM > Pemeriksaan > Pemeriksaan Gula",
    },
    "Pemeriksaan Gula Darah Remaja": {
        "Apakah Anak Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?":
            "PTM > Riwayat PTM pada Diri Sendiri > Penyakit Diabetes",
        "Gula Darah Sewaktu (GDS)": "PTM > Pemeriksaan > Pemeriksaan Gula",
    },
    "Pemeriksaan Gigi - Anak": {
        "Berapa jumlah gigi karies?":
            'Anamnesa > Pemeriksaan Dasar Gigi > Status Karies ("-" → "Tidak ada"; '
            "EPUS has no caries count)",
    },
    "Faktor Risiko dan Skrining X-Ray TB (Anak 1-9 tahun)": {
        "Apakah anak Anda pernah atau sedang mengalami batuk yang tidak sembuh-sembuh?":
            "Anamnesa > Anamnesa > Keluhan Utama + Lama Sakit (TB ICDX → >2 minggu)",
        "Apakah berat badan anak Anda turun tanpa penyebab jelas/ "
        "BB tidak naik dalam 2 bulan sebelumnya/ nafsu makan turun?":
            "skrining_klaster > gejala_tbc > bb_turun (1/0 → Ya/Tidak)",
        "Apakah anak anda mengalami demam hilang timbul tanpa sebab "
        "yang jelas lebih dari 2 minggu?":
            "skrining_klaster > gejala_tbc > demam (1/0 → Ya/Tidak)",
        "Apakah dilakukan pemeriksaan radiografi toraks?":
            "skrining_klaster > gejala_tbc > abnormalitas_tbc (present → Ya)",
    },
    "Pemeriksaan Tuberkulosis Anak": {
        "Apakah anda ada kontak dengan pasien Tuberkulosis (TBC)?":
            "TB Paru > Data Register Terduga TB > Kriteria Terduga TB (any non-empty → Ya)",
    },
    "Berat Lahir": {
        "Berat Lahir": "Kartubayi > Identitas Bayi > Berat Badan (birth weight)",
        "Berat Badan Saat Ini (usia >24 jam)": "Anamnesa > Periksa Fisik > Berat Badan",
    },
    "Riwayat Imunisasi Rutin Balita": {
        "Apakah anak anda sudah pernah menerima imunisasi Hepatitis B pada usia <24 jam?":
            "Kartubayi > Pencegahan > Hep. B0 (checkbox → Sudah/Belum)",
    },
    "Skrining Lanjutan Talasemia - Balita dan Anak Prasekolah": {
        "Hasil Pemeriksaan Hemoglobin (Hb) dalam g/dL":
            "Laboratorium > Ubah Data Laboratorium > Hemoglobin (HGB)",
        "Hasil Pemeriksaan MCV": "Laboratorium > Ubah Data Laboratorium > MCV",
        "Hasil Pemeriksaan MCH": "Laboratorium > Ubah Data Laboratorium > MCH",
        "Hasil Pemeriksaan Eritrosit / RBC Count":
            "Laboratorium > Ubah Data Laboratorium > Eritrosit (RBC)",
        "Hasil Pemeriksaan Red cell distribution width (RDW)":
            "Laboratorium > Ubah Data Laboratorium > RDW-CV/RDW-SD",
        "Curiga Talasemia": "skrining_klaster > thalasemia > kesimpulan",
    },
    "Skrining Telinga dan Mata - Balita dan Anak Prasekolah": {
        "Hasil Tes Daya Dengar":
            "skrining_klaster > skrining_indra_pendengaran > curiga/pemeriksaan/omsk + rujuk",
        "Hasil pemeriksaan Tes Daya Lihat":
            "skrining_klaster > penglihatan > tajam_kiri/tajam_kanan",
        "Apakah ditemukan selaput mata merah atau kornea keruh atau "
        "kelopak mata ada benjolan atau susah berkedip atau posisi bola "
        "mata juling atau pupil putih?":
            "skrining_klaster > penglihatan > mata_luar",
        "Apakah ditemukan serumen impaksi?":
            "PTM > Gangguan Pendengaran > Serumen Telinga Kanan/Kiri",
        "Apakah ditemukan infeksi telinga?":
            "PTM > Gangguan Pendengaran > Congek Telinga Kanan/Kiri",
    },
    "Kuesioner Masalah Perilaku dan Emosional (KMPE) - "
    "Jika terindikasi memiliki masalah perilaku dan emosi": {
        "Hasil pemeriksaan KMPE":
            "skrining_klaster > skrining_sdidtk > q1..q14 (count of 'Ya')",
    },
    "Kuesioner Pra Skrining Perkembangan (KPSP)": {
        "Hasil pemeriksaan KPSP":
            "skrining_klaster > skrining_sdidtk > interpretasi (Sesuai/Meragukan/Penyimpangan)",
    },
    "Kuesioner Gangguan Pemusatan Perhatian dan Hiperaktivitas (GPPH) - "
    "bila ada indikasi": {
        "Hasil Pemeriksaan Kuesioner GPPH":
            "skrining_klaster > skrining_sdidtk > interpretasi (total <13 / ≧13)",
    },
    "M-CHAT - 1. Penapisan": {
        _MCHAT_Q: "skrining_klaster > skrining_sdidtk > interpretasi (risiko autisme → Ya/Tidak)",
    },
    "Penapisan dan Pemeriksaan Sifilis Anak": {
        "Hasil Pemeriksaan Rapid Test Sifilis":
            "(penyakit_khusus.ICDX ∪ PTM > Diagnosa 1/2/3) A50-A53 → Reaktif",
    },
    "Tekanan Darah Dewasa Lansia": {
        "Apakah Anda pernah dinyatakan tekanan darah tinggi?":
            "skrining_klaster > hipertensi > riwayat_pribadi "
            "(fallback PTM > Riwayat PTM pada Diri Sendiri > Penyakit Hipertensi)",
        "Tekanan Darah Sistolik":
            "Anamnesa > Periksa Fisik > Sistole (fallback PTM > Tekanan Darah & IMT > Sistole)",
        "Tekanan darah diastolik":
            "Anamnesa > Periksa Fisik > Diastole (fallback PTM > Tekanan Darah & IMT > Diastole)",
        "Tekanan Darah Sistolik Ke-2": None,
        "Tekanan darah diastolik ke-2": None,
        "Sudah Berapa Bulan Anda Didiagnosis Hipertensi Oleh Dokter? "
        "Isi Total Bulan Sejak didiagnosis dokter hingga saat ini, "
        "misal didiagnosis 1 tahun yang lalu = 12, dst": None,
    },
    "Pemeriksaan Gula Darah Dewasa Lansia": {
        "Apakah Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?":
            "skrining_klaster > diabetes_melitus > anamnesis[Riwayat Pribadi Diabetes Melitus] "
            "(fallback PTM > Riwayat PTM pada Diri Sendiri > Penyakit Diabetes)",
        "Gula Darah Sewaktu (GDS) (mg/dl)":
            "skrining_klaster > diabetes_melitus > hasil_gds "
            "(fallback PTM > Pemeriksaan > Pemeriksaan Gula when GDP empty)",
        "Gula Darah Sewaktu Kedua (GDS 2). Lakukan jika hasil GDS 1 Prediabetes (≥140-199mg/dl) atau Hiperglikemia (≥200mg/dl) dan BELUM PERNAH didiagnosis Diabetes": None,
        "Gula Darah Puasa (GDP) (mg/dl)":
            "skrining_klaster > diabetes_melitus > hasil_gdp "
            "(fallback PTM > Pemeriksaan > Pemeriksaan Gula Darah Puasa)",
        "Gula Darah 2 Jam PP (mg/dl)":
            "skrining_klaster > diabetes_melitus > hasil_gd2pp "
            "(fallback PTM > Pemeriksaan > Pemeriksaan Gula Darah 2 Jam PP)",
        "Sudah Berapa Bulan Anda Didiagnosis Diabetes Melitus Oleh Dokter? "
        "Isi Total Bulan Sejak didiagnosis dokter hingga saat ini, "
        "misal didiagnosis 1 tahun yang lalu = 12, dst": None,
    },
    "Gizi (BB - TB - Lingkar Perut) Laki-laki": {
        "Berat Badan (Kg)":
            "Anamnesa > Periksa Fisik > Berat Badan (fallback PTM > Tekanan Darah & IMT > Berat Badan)",
        "Pengukuran Tinggi Badan (cm)":
            "Anamnesa > Periksa Fisik > Tinggi Badan (fallback PTM > Tekanan Darah & IMT > Tinggi Badan)",
        "Pengukuran Lingkar Perut":
            "Anamnesa > Periksa Fisik > Lingkar Perut (fallback PTM > Pemeriksaan > Lingkar Perut)",
    },
    "Gizi (BB - TB - Lingkar Perut) Perempuan": {
        "Berat Badan (Kg)":
            "Anamnesa > Periksa Fisik > Berat Badan (fallback PTM > Tekanan Darah & IMT > Berat Badan)",
        "Pengukuran Tinggi Badan (cm)":
            "Anamnesa > Periksa Fisik > Tinggi Badan (fallback PTM > Tekanan Darah & IMT > Tinggi Badan)",
        "Pengukuran Lingkar Perut":
            "Anamnesa > Periksa Fisik > Lingkar Perut (fallback PTM > Pemeriksaan > Lingkar Perut)",
    },
    "Pemeriksaan PPOK (Skrining PUMA)": {
        "Apakah anda sedang/mempunyai riwayat merokok?":
            "skrining_klaster > puma > pernah_merokok (fallback PTM > Faktor Risiko > Merokok)",
        "Apakah Anda pernah merasa napas pendek ketika berjalan lebih cepat pada jalan yang datar atau pada jalan yang sedikit menanjak?":
            "skrining_klaster > puma > napas_pendek (fallback PTM > Faktor Risiko > napas pendek)",
        "Apakah Anda biasanya mempunyai dahak yang berasal dari paru atau kesulitan mengeluarkan dahak saat Anda sedang tidak menderita selesma/flu?":
            "skrining_klaster > puma > dahak (fallback PTM > Faktor Risiko > dahak)",
        "Apakah Anda biasanya batuk saat sedang tidak menderita selesma/flu?":
            "skrining_klaster > puma > batuk (fallback PTM > Faktor Risiko > batuk)",
        "Apakah Dokter atau tenaga medis lainnya pernah meminta Anda untuk melakukan pemeriksaan spirometri atau peak flow meter (meniup ke dalam suatu alat) untuk mengetahui fungsi paru?":
            "skrining_klaster > puma > pemeriksaan_fungsi_paru (fallback PTM > Faktor Risiko > spirometri)",
        "Jika Perokok Aktif, berapa bungkus per tahun?":
            "PTM > Faktor Risiko > Pack Year (or Rata-rata Jumlah Rokok × Lama Merokok)",
    },
    "Demografi Dewasa Perempuan": {
        "Status Perkawinan":
            "Data Pasien > Status Perkawinan (fallback PKPR > Status Perkawinan)",
        "Apakah Anda sedang hamil?": "Anamnesa > Periksa Fisik > Status Hamil",
        "Apakah Anda penyandang disabilitas?":
            "PKPR > (Buat Baru ∪ Ubah Data) > 15. Disabilitas Mental + 18. Disabilitas Fisik (OR-union)",
    },
    "Demografi Dewasa Laki-Laki": {
        "Status Perkawinan":
            "Data Pasien > Status Perkawinan (fallback PKPR > Status Perkawinan)",
        "Apakah Anda penyandang disabilitas?":
            "PKPR > (Buat Baru ∪ Ubah Data) > 15. Disabilitas Mental + 18. Disabilitas Fisik (OR-union)",
    },
    "Demografi Lansia": {
        "Status Perkawinan":
            "Data Pasien > Status Perkawinan (fallback PKPR > Status Perkawinan)",
        "Apakah Anda penyandang disabilitas?":
            "PKPR > (Buat Baru ∪ Ubah Data) > 15. Disabilitas Mental + 18. Disabilitas Fisik (OR-union)",
    },
    "Pemeriksaan Inspekulo dan IVA": {
        "Pemeriksaan Inspekulo":
            "skrining_klaster > skrining_resiko_kanker_serviks > inspekulo "
            "(fallback PTM > Pemeriksaan IVA dan Sadanis > Hasil IVA)",
        "Pemeriksaan Inspeksi Visual Asam Asetat (IVA)":
            "skrining_klaster > skrining_resiko_kanker_serviks > hasil_iva "
            "(fallback PTM > Pemeriksaan IVA dan Sadanis > Hasil IVA)",
    },
    "Kanker Leher Rahim": {
        "Apakah pernah melakukan hubungan intim/seksual?":
            "skrining_klaster > skrining_resiko_kanker_serviks > seksual",
    },
    "Skrining Kanker Payudara": {
        "Pemeriksaan yang dilakukan":
            "skrining_klaster > payudara (SADANIS when present) else PTM IVA-Sadanis",
        "Hasil pemeriksaan SADANIS":
            "skrining_klaster > payudara > kesimpulan",
        "Hasil pemeriksaan USG Payudara":
            "skrining_klaster > payudara > hasil_usg (only when USG performed)",
    },
    "Skrining Telinga dan Mata (=>40 tahun)": {
        "Apa hasil skrining tajam penglihatan?":
            "skrining_klaster > penglihatan > tajam_kiri/tajam_kanan "
            "(fallback PTM > Gangguan Penglihatan > Refraksi Mata Kanan/Kiri)",
        "Hasil pemeriksaan tajam pendengaran":
            "skrining_klaster > skrining_indra_pendengaran > bisikan_telinga_kiri/kanan "
            "(fallback PTM > Gangguan Pendengaran > Congek + Tuli Kongenital Telinga Kanan/Kiri)",
        "Apa Hasil Pemeriksaan Telinga Luar (serumen impaksi)?":
            "PTM > Gangguan Pendengaran > Serumen Telinga Kanan/Kiri (OR-union)",
        "Apa Hasil Pemeriksaan Telinga Luar (infeksi telinga)?":
            "PTM > Gangguan Pendengaran > Congek Telinga Kanan/Kiri (OR-union)",
        "Hasil pemeriksaan pupil":
            "skrining_klaster > penglihatan > pemeriksaan_pupil_kiri/kanan "
            "(fallback PTM > Gangguan Penglihatan > Katarak Mata Kanan/Kiri)",
    },
    "Skrining Telinga dan Mata (18-39 tahun)": {
        "Apa hasil skrining tajam penglihatan?":
            "skrining_klaster > penglihatan > tajam_kiri/tajam_kanan "
            "(fallback PTM > Gangguan Penglihatan > Refraksi Mata Kanan/Kiri)",
        "Hasil pemeriksaan tajam pendengaran":
            "skrining_klaster > skrining_indra_pendengaran > bisikan_telinga_kiri/kanan "
            "(fallback PTM > Gangguan Pendengaran > Congek + Tuli Kongenital Telinga Kanan/Kiri)",
        "Apa Hasil Pemeriksaan Telinga Luar (serumen impaksi)?":
            "PTM > Gangguan Pendengaran > Serumen Telinga Kanan/Kiri (OR-union)",
        "Apa Hasil Pemeriksaan Telinga Luar (infeksi telinga)?":
            "PTM > Gangguan Pendengaran > Congek Telinga Kanan/Kiri (OR-union)",
    },
    "Faktor Risiko TB - Dewasa & Lansia": {
        "Apakah Anda pernah atau sedang mengalami batuk yang tidak sembuh-sembuh?":
            "(penyakit_khusus.ICDX ∪ PTM > Diagnosa 1/2/3) A15-A19 (TB) / "
            "Anamnesa > Keluhan Utama + Lama Sakit (cough rule)",
    },
    "Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)": {
        "Apakah Anda pernah atau sedang mengalami batuk yang tidak sembuh-sembuh?":
            "(penyakit_khusus.ICDX ∪ PTM > Diagnosa 1/2/3) A15-A19 (TB) / "
            "Anamnesa > Keluhan Utama + Lama Sakit (cough rule)",
    },
    "Pemeriksaan Tuberkulosis (Dewasa & Lansia)": {
        "Apakah anda ada kontak dengan pasien Tuberkulosis (TBC)?":
            "TB Paru > Data Register Terduga TB > Kriteria Terduga TB (any non-empty → Ya)",
        "Metode Pemeriksaan (untuk terduga TB)": None,  # derived from which TCM/BTA result is filled
    },
    "Hasil Pemeriksaan - Skrining Jantung": {
        "Hasil Pemeriksaan EKG":
            "skrining_klaster > resiko_penyakit_jantung > SkriningJantung[ekg_v2] "
            "(fallback PTM > Kardiovaskular > Hasil EKG)",
    },
    "Pemeriksaan HIV": {
        "Hasil Pemeriksaan Rapid Test HIV":
            "(penyakit_khusus.ICDX ∪ PTM > Diagnosa 1/2/3) B20-B24 → Reaktif; "
            "else Konseling HIV > Konseling Pra Tes > Hasil",
    },
    "Pemeriksaan Sifilis": {
        "Hasil Pemeriksaan Rapid Test Sifilis":
            "(penyakit_khusus.ICDX ∪ PTM > Diagnosa 1/2/3) A50-A53 → Reaktif",
    },
    "Pemeriksaan Hepatitis": {
        "Hasil Rapid Test Hepatitis B":
            "(penyakit_khusus.ICDX ∪ PTM > Diagnosa 1/2/3) B16 / B18.0 / B18.1 → Reaktif",
        "Hasil Rapid Test Hepatitis C":
            "(penyakit_khusus.ICDX ∪ PTM > Diagnosa 1/2/3) B17.1 / B18.2 → Reaktif",
    },
    "Perilaku Merokok": {
        "Apakah Anda merokok dalam setahun terakhir ini?":
            "skrining_klaster > faktor_risiko > q::(merokok dalam setahun terakhir) "
            "(fallback PTM > Faktor Risiko > Merokok)",
        "Apakah Anda terpapar asap rokok atau menghirup asap rokok "
        "dari orang lain dalam sebulan terakhir?":
            "skrining_klaster > faktor_risiko > q::(terpapar asap rokok dari orang lain sebulan terakhir)",
    },
    "Pemeriksaan Kadar CO (Hanya Diisi Apabila Merokok atau Terpapar Asap Rokok)": {
        "Kadar CO Pernapasan": "PTM > Form UBM > CAR",
    },
    "Tingkat Aktivitas Fisik (sedang dan berat)": {
        "Apakah Anda melakukan olahraga intensitas sedang seperti latihan beban < 20 kg, senam aerobic, yoga, bermain bola, bersepeda dan berenang (santai)?":
            "PTM > Faktor Risiko > Kurang Aktivitas Fisik (inverted)",
        "Apakah Anda melakukan olahraga intensitas berat seperti bersepeda cepat (>16 km/jam), jalan cepat (>7 km/jam), lari, sepak bola, futsal, bulutangkis, tenis, basket dan lompat tali?":
            "PTM > Faktor Risiko > Kurang Aktivitas Fisik (inverted)",
    },
    "POCT Lipid Panel (Khusus usia >=40 thn dan penyandang HT dan/atau DM)": {
        "Kolesterol Total": "PTM > Profil Lipid > Cholesterol Total",
        "HDL": "PTM > Profil Lipid > HDL",
        "LDL": "PTM > Profil Lipid > LDL",
        "Trigliserida": "PTM > Profil Lipid > Trigliserida",
    },
    "Skrining Fungsi Ginjal Laki-Laki (hanya untuk =>40 tahun dengan risiko HT DM)": {
        "Hasil Pemeriksaan Kreatinin":
            "skrining_klaster > fungsi_ginjal > q::kreatinin (fallback PTM > Ginjal > Kreatinin)",
        "Hasil Pemeriksaan Ureum":
            "skrining_klaster > fungsi_ginjal > q::ureum (fallback PTM > Ginjal > Ureum)",
        "Nilai Hasil pemeriksaan (e-LFG (CKD-EPI))": "PTM > Ginjal > eGFR",
        "Usia": "Data Pasien > Umur (derived)",
    },
    "Skrining Fungsi Ginjal Perempuan (hanya untuk =>40 tahun dengan risiko HT DM)": {
        "Hasil Pemeriksaan Kreatinin":
            "skrining_klaster > fungsi_ginjal > q::kreatinin (fallback PTM > Ginjal > Kreatinin)",
        "Hasil Pemeriksaan Ureum":
            "skrining_klaster > fungsi_ginjal > q::ureum (fallback PTM > Ginjal > Ureum)",
        "Nilai Hasil pemeriksaan (e-LFG (CKD-EPI))": "PTM > Ginjal > eGFR",
        "Usia": "Data Pasien > Umur (derived)",
    },
    "Skrining Kerusakan Ginjal (hanya untuk =>40 tahun dengan risiko HT DM)": {
        "Konsentrasi Albumin Urin": "Laboratorium > Microalbuminuria > Hasil",
    },
    "Pemeriksaan Fibrosis/Sirosis Hati": {
        "Nilai SGOT": "PTM > Fungsi Hati > SGOT",
        "Pemeriksaan Trombosit": "Laboratorium > Trombosit > Hasil",
    },
    "Pemeriksaan Calon Pengantin Perempuan": {
        "Kadar Hemoglobin": "Laboratorium > Hb (Hemoglobin) > Hasil",
    },
    "Skrining Kanker Paru (Usia =>45 thn)": {
        "Apakah pernah didiagnosis/menderita kanker?":
            "skrining_klaster > skriningkankerparu > diagnosis_kanker "
            "(fallback penyakit_khusus kanker flag)",
        "Apakah ada keluarga (ayah/ibu/saudara kandung) didiagnosis/menderita kanker sebelumnya?":
            "skrining_klaster > skriningkankerparu > keluarga_kanker "
            "(fallback PTM > Riwayat PTM pada Keluarga > Penyakit Kanker)",
        "Riwayat merokok/paparan asap rokok":
            "skrining_klaster > skriningkankerparu > riwayat_merokok "
            "(fallback PTM > Faktor Risiko > Merokok)",
        "Riwayat tempat kerja mengandung zat karsinogenik (Pertambangan/ pabrik/ bengkel/ garmen/ bangunan/ laboratorium/ sopir/ galangan kapal, dll)?":
            "skrining_klaster > skriningkankerparu > riwayat_bekerja",
        "Lingkungan tempat tinggal berpotensi tinggi (lingkungan dekat pabrik/pertambangan/buangan sampah, dll)?":
            "skrining_klaster > skriningkankerparu > tempat_tinggal_berpolusi",
        "Lingkungan dalam rumah yang tidak sehat (ventilasi buruk/atap dari asbes/lantai tanah, dapur tungku, dll)?":
            "skrining_klaster > skriningkankerparu > rumah_tidak_sehat",
        "Pernah didiagnosis penyakit paru kronik?":
            "skrining_klaster > skriningkankerparu > diagnosis_paru_kronik "
            "(fallback penyakit_khusus TB/paru-kronis flag)",
    },
    "Penapisan Risiko Kanker Paru": {
        "Apakah Anda merokok dalam setahun terakhir ini?":
            "skrining_klaster > skriningkankerparu > riwayat_merokok (aktif→Ya) "
            "(fallback PTM > Faktor Risiko > Merokok)",
        "Apakah Anda pernah memiliki riwayat merokok dalam 15 tahun terakhir?":
            "skrining_klaster > skriningkankerparu > riwayat_merokok (aktif/bekas<15th→Ya) "
            "(fallback PTM > Faktor Risiko > Lama Merokok dalam Tahun)",
        "Apakah Anda terpapar atau menghirup asap rokok dari orang lain di rumah, lingkungan atau tempat kerja dalam 1 bulan terakhir?":
            "skrining_klaster > skriningkankerparu > riwayat_merokok (perokok pasif→Ya)",
        "Apakah memiliki riwayat kanker paru pada keluarga (ayah/ibu/saudara kandung)?":
            "skrining_klaster > skriningkankerparu > keluarga_kanker (kanker paru→Ya) "
            "(fallback PTM > Riwayat PTM pada Keluarga > Penyakit Kanker)",
        "Apakah Anda sedang mengalami salah satu atau lebih gejala berikut dan telah diobati tetapi tidak sembuh-sembuh : batuk dalam jangka waktu yang lama / batuk berdarah/ sesak napas/ nyeri dada/ leher bengkak/ terdapat benjolan pada leher?":
            "(penyakit_khusus.ICDX ∪ PTM > Diagnosa 1/2/3) A15-A19 (TB) → Ya",
        "Apakah Anda pernah memiliki riwayat penyakit TBC atau PPOK?":
            "skrining_klaster > skriningkankerparu > diagnosis_paru_kronik (PPOK/TBC→Ya) "
            "(fallback TB-union ∪ paru-kronis-union)",
    },
    "Penurunan Kognitif - Tindak Lanjut (Mini Cog-Clock Draw)": {
        _MINICOG_CLOCK_Q: "skrining_klaster > mini_cog > gambar_jam",
        _MINICOG_RECALL_Q: "skrining_klaster > mini_cog > kata_yang_tepat_dua",
    },
    "Mobilisasi - Pemeriksaan Lanjutan (SPPB)": {
        label: f"skrining_klaster > sppb > {base}"
        for base, (label, _opts) in _SPPB.items()
    },
    "Skrining Malnutrisi - Pemeriksaan Lanjutan (MNA-SF)": {
        label: f"skrining_klaster > pengkajian_nutrisi > {base}"
        for base, (label, _opts) in _MNA.items()
    },
    "Riwayat Imunisasi Tetanus(Status T) - Hanya untuk Catin": {
        "Apakah anda pernah mendapatkan imunisasi tetanus minimal 2 kali? "
        "(imunisasi tetanus biasanya didapatkan pada vaksin DPT saat bayi, "
        "vaksin TT/Td saat usia sekolah dasar)":
            "skrining_klaster > skrining_imunisasi_dewasa > imunisasi_tetanus (T2+→minimal dua kali)",
    },
    "Faktor Risiko Kanker Usus": {
        "Apakah ada anggota keluarga Anda, yang pernah dinyatakan menderita kanker kolorektal atau kanker usus?":
            "skrining_klaster > kolorektal > riwayat_kanker_kolorektal "
            "(fallback PTM > Riwayat PTM pada Keluarga > Penyakit Kanker)",
        "Apakah Anda merokok?":
            "skrining_klaster > kolorektal > riwayat_merokok (fallback PTM > Faktor Risiko > Merokok)",
    },
    "Skrining Karies dan Gigi Hilang": {
        "Gigi karies":
            "Anamnesa > Pemeriksaan Dasar Gigi > Status Karies (+→Ya) / Karies Gigi (lesion location→Ya)",
        "Gigi hilang/dicabut": None,  # no EPUS source
    },
    "Skrining Penyakit Periodontal": {
        "Gigi Goyang": "Anamnesa > Pemeriksaan Dasar Gigi > Goyang",
        "Penyakit Periodontal":
            "Anamnesa > Pemeriksaan Dasar Gigi > Warna Gusi (≠Normal) / Pem-bengkakan (Ada) → Ya",
    },
}
