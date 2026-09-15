"""Build the static EPUS↔ASIK form mapping resource.

Run manually when:
- A new ``Padanan Paket Odoo`` Excel sheet drops.
- The ``asik_audit_*`` schema dump is refreshed.
- ``epus_to_asik.EPUS_BREADCRUMBS`` is edited.

Output: ``backend/app/data/asik_form_mapping.json`` — one JSON document with
``forms[]`` (list ordered by paket_name) and an ``epus_paths[]`` index.
The dashboard route serves this file directly; the frontend renders it.

Inputs:
- ``Metadata Program Rutin.xlsx`` → sheet ``Padanan Paket Odoo 2025-2026``
  (provides FRM/PPM/PPV codes + per-question demographics).
- ``testing-epus-asik/asik_audit_*/*.json`` (provides live SurveyJS labels +
  enum options + question kind).
- ``backend/app/services/epus_to_asik.py`` ``EPUS_BREADCRUMBS`` (provides
  EPUS source path per (form, field)).

Run from repo root::

    python backend/app/data/build_mapping.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXCEL_PATH = Path(os.environ.get("PADANAN_XLSX", str(Path.home() / "Downloads" / "Metadata Program Rutin.xlsx")))
AUDIT_DIR = REPO_ROOT / "testing-epus-asik" / "asik_audit_20260429"
OUT_PATH = REPO_ROOT / "backend" / "app" / "data" / "asik_form_mapping.json"

sys.path.insert(0, str(REPO_ROOT / "backend"))
from app.services.epus_to_asik import EPUS_BREADCRUMBS  # noqa: E402


# ─── Padanan extraction ────────────────────────────────────────────────────


def _ff_columns(rows: list[tuple], max_col: int = 23) -> list[list]:
    """Forward-fill hierarchical group columns 0..max_col-1.

    When a higher-level group changes, deeper-level forward-fills reset so
    a paket's parameters don't leak into the next paket's row.
    """
    fwd: list = [None] * max_col
    out: list[list] = []
    for row in rows:
        new = list(row[:max_col])
        for i in range(max_col):
            if new[i] is None or (isinstance(new[i], str) and new[i].strip() == ""):
                new[i] = fwd[i]
            else:
                fwd[i] = new[i]
                for j in range(i + 1, max_col):
                    fwd[j] = None
        out.append(new + list(row[max_col:]))
    return out


_DEMO_COLS: dict[int, str] = {
    23: "BBL",
    25: "Balita 1 Tahun",
    27: "Balita 12-17 Bulan",
    29: "Balita 18-23 Bulan",
    31: "Balita 2 Tahun",
    33: "Balita 3-6 Tahun",
    35: "Balita 3-4 Tahun",
    37: "Anak Pra Sekolah 5-6 Tahun",
    39: "Perempuan 18-24 Tahun",
    41: "Perempuan 25-29 Tahun",
    43: "Perempuan 30-39 Tahun",
    45: "Perempuan 40-59 Tahun",
    47: "Perempuan 40-44 Tahun",
    49: "Perempuan 45-59 Tahun",
    51: "Laki-laki 18-24 Tahun",
    53: "Laki-laki 25-39 Tahun",
    55: "Laki-laki 40-44 Tahun",
    57: "Laki-laki 45-59 Tahun",
    59: "Laki-laki >=60 Tahun",
    61: "Perempuan 60-69 Tahun",
    63: "Perempuan >=70 Tahun",
}


def _load_padanan() -> dict[str, dict]:
    import openpyxl  # local import — only needed when rebuilding

    wb = openpyxl.load_workbook(EXCEL_PATH, read_only=True, data_only=True)
    ws = wb["Padanan Paket Odoo 2025-2026"]
    rows = list(ws.iter_rows(values_only=True))
    data = rows[3:]
    filled = _ff_columns(data, max_col=23)
    by_frm: dict[str, dict] = {}
    for row in filled:
        modul = (row[0] or "").strip() if isinstance(row[0], str) else None
        layanan_name = row[1]
        layanan_code = row[2]
        paket_name = row[4]
        paket_code = (row[5] or "").strip() if isinstance(row[5], str) else None
        parameter_name = row[7]
        parameter_code = row[8]
        label_pertanyaan = row[10]
        line = row[11]
        line_code = row[12]
        nilai_poin = row[13]
        rekomendasi = row[20]
        tipe = row[21]
        status_2026 = row[22]
        if not paket_code:
            continue
        rec = by_frm.setdefault(
            paket_code,
            {
                "frm_code": paket_code,
                "paket_name": paket_name,
                "modul": modul,
                "layanan_name": layanan_name,
                "layanan_code": (layanan_code or "").strip() if isinstance(layanan_code, str) else layanan_code,
                "questions": {},
            },
        )
        qkey = label_pertanyaan or parameter_name
        if not qkey:
            continue
        q = rec["questions"].setdefault(
            qkey,
            {
                "label": qkey,
                "parameter_name": parameter_name,
                "parameter_codes": set(),
                "choices": [],
                "demos": set(),
                "tipe": None,
                "status": None,
                "rekomendasi": None,
            },
        )
        if parameter_code:
            q["parameter_codes"].add(parameter_code)
        if line is not None and str(line).strip() != "":
            ch = {
                "line": str(line).strip() if not isinstance(line, (int, float)) else line,
                "code": line_code,
                "nilai_poin": nilai_poin,
            }
            if ch not in q["choices"]:
                q["choices"].append(ch)
        for col, label in _DEMO_COLS.items():
            v_stg = row[col] if col < len(row) else None
            v_prod = row[col + 1] if col + 1 < len(row) else None
            if v_stg or v_prod:
                q["demos"].add(label)
        if tipe:
            q["tipe"] = tipe
        if status_2026:
            q["status"] = status_2026
        if rekomendasi:
            q["rekomendasi"] = rekomendasi
    for rec in by_frm.values():
        for q in rec["questions"].values():
            q["parameter_codes"] = sorted(q["parameter_codes"])
            q["demos"] = sorted(q["demos"])
    return by_frm


# ─── Audit extraction ──────────────────────────────────────────────────────


def _norm_audit_title(t: str) -> str:
    return re.sub(r"^\d+[a-z]?\.\s*", "", t).strip()


def _clean_audit_label(s: str) -> str:
    s = re.sub(r"^\d+\.\s*", "", s or "").split("Clear")[0]
    s = re.sub(r"\s*\*\s*$", "", s).strip()
    return s


def _load_audit() -> dict[str, dict]:
    """Return {form_title: {questions: [{label, kind, options, name}]}}."""
    if not AUDIT_DIR.exists():
        return {}
    out: dict[str, dict] = {}
    for fn in sorted(os.listdir(AUDIT_DIR)):
        path = AUDIT_DIR / fn
        with open(path) as fh:
            d = json.load(fh)
        title = _norm_audit_title(d.get("title", ""))
        if not title:
            continue
        # Try to derive FRM from first question name
        frm = None
        lpm = None
        for q in d.get("questions") or []:
            parts = (q.get("name") or "").split("|")
            if len(parts) >= 2 and parts[1].startswith("FRM"):
                frm = parts[1]
                lpm = parts[0]
                break
        out[title] = {
            "frm_code": frm,
            "lpm_code": lpm,
            "questions": [
                {
                    "label": _clean_audit_label(q.get("label", "")),
                    "kind": q.get("kind"),
                    "options": q.get("options") or [],
                    "name": q.get("name"),
                }
                for q in d.get("questions") or []
            ],
        }
    return out


# ─── Combine ───────────────────────────────────────────────────────────────


def build() -> dict:
    padanan = _load_padanan()
    audit = _load_audit()
    audit_by_frm = {info["frm_code"]: (title, info) for title, info in audit.items() if info.get("frm_code")}

    forms: list[dict] = []
    for frm_code, rec in padanan.items():
        paket_name = rec["paket_name"] or ""
        questions = list(rec["questions"].values())
        # Match audit by FRM first, fall back to paket_name
        audit_match = audit_by_frm.get(frm_code)
        if audit_match is None and paket_name in audit:
            audit_match = (paket_name, audit[paket_name])

        # Build a label index for audit Q's so we can join per question
        audit_q_by_label = {}
        if audit_match:
            for q in audit_match[1]["questions"]:
                audit_q_by_label[q["label"]] = q

        # Lookup EPUS source path from converter breadcrumbs
        epus_field_map = EPUS_BREADCRUMBS.get(paket_name) or {}

        # Build per-question merged record
        out_questions = []
        for q in questions:
            label = q["label"]
            audit_q = audit_q_by_label.get(label)
            epus_path = epus_field_map.get(label)
            out_questions.append(
                {
                    "label": label,
                    "parameter_codes": q["parameter_codes"],
                    "tipe": q["tipe"],
                    "status_2026": q["status"],
                    "rekomendasi": q["rekomendasi"],
                    "demos": q["demos"],
                    "choices": q["choices"],
                    "live_kind": (audit_q or {}).get("kind"),
                    "live_options": (audit_q or {}).get("options") or [],
                    "live_name": (audit_q or {}).get("name"),
                    "epus_source": epus_path,
                    "covered_by_converter": label in epus_field_map,
                }
            )

        # Form-level coverage tally
        covered = sum(1 for q in out_questions if q["covered_by_converter"])
        forms.append(
            {
                "frm_code": frm_code,
                "paket_name": paket_name,
                "modul": rec["modul"],
                "layanan_name": rec["layanan_name"],
                "layanan_code": rec["layanan_code"],
                "in_converter_breadcrumbs": paket_name in EPUS_BREADCRUMBS,
                "in_audit": audit_match is not None,
                "audit_form_title": audit_match[0] if audit_match else None,
                "question_count": len(out_questions),
                "covered_question_count": covered,
                "questions": out_questions,
                "demos_union": sorted({d for q in out_questions for d in q["demos"]}),
            }
        )

    # Audit-only forms (no Padanan FRM match) — still useful to surface
    seen_frms = set(padanan.keys())
    for title, info in audit.items():
        if info.get("frm_code") in seen_frms:
            continue
        if info.get("frm_code") is None and title in {f["paket_name"] for f in forms}:
            continue
        epus_field_map = EPUS_BREADCRUMBS.get(title) or {}
        out_questions = []
        for q in info["questions"]:
            out_questions.append(
                {
                    "label": q["label"],
                    "parameter_codes": [],
                    "tipe": None,
                    "status_2026": None,
                    "rekomendasi": None,
                    "demos": [],
                    "choices": [],
                    "live_kind": q["kind"],
                    "live_options": q["options"],
                    "live_name": q["name"],
                    "epus_source": epus_field_map.get(q["label"]),
                    "covered_by_converter": q["label"] in epus_field_map,
                }
            )
        forms.append(
            {
                "frm_code": info.get("frm_code"),
                "paket_name": title,
                "modul": None,
                "layanan_name": None,
                "layanan_code": info.get("lpm_code"),
                "in_converter_breadcrumbs": title in EPUS_BREADCRUMBS,
                "in_audit": True,
                "audit_form_title": title,
                "question_count": len(out_questions),
                "covered_question_count": sum(1 for q in out_questions if q["covered_by_converter"]),
                "questions": out_questions,
                "demos_union": [],
            }
        )

    # Fall back paket_name → modul → layanan_name when paket_name is empty
    # (a couple of FRM rows in Padanan have an empty paket cell).
    for f in forms:
        if not (f.get("paket_name") or "").strip():
            f["paket_name"] = (f.get("modul") or f.get("layanan_name") or f.get("frm_code") or "").strip() or "(unnamed)"

    forms.sort(key=lambda f: (f["paket_name"] or "").lower())

    epus_paths_index: dict[str, list[dict]] = {}
    for f in forms:
        for q in f["questions"]:
            path = q.get("epus_source")
            if not path:
                continue
            epus_paths_index.setdefault(path, []).append(
                {
                    "form_name": f["paket_name"],
                    "frm_code": f["frm_code"],
                    "label": q["label"],
                }
            )

    return {
        "version": 1,
        "source_xlsx": str(EXCEL_PATH),
        "audit_dir": str(AUDIT_DIR),
        "form_count": len(forms),
        "forms": forms,
        "epus_paths_index": [
            {"path": k, "destinations": v} for k, v in sorted(epus_paths_index.items())
        ],
    }


def main() -> None:
    doc = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    print(f"wrote {OUT_PATH} — {doc['form_count']} forms")


if __name__ == "__main__":
    main()
