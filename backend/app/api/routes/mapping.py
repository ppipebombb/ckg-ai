"""ASIK form metadata mapping reference.

Static reference data combining Padanan Paket Odoo (Excel) + live ASIK
audit (52-form schema dump) + converter ``EPUS_BREADCRUMBS``. Built once
via ``backend/app/data/build_mapping.py`` and committed as
``asik_form_mapping.json``. Auth-gated via admin token.
"""

from __future__ import annotations

import json
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_admin_id

router = APIRouter(tags=["mapping"], prefix="/admin/mapping")

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "asik_form_mapping.json"


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    if not _DATA_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "asik_form_mapping.json not found; run "
                "`python backend/app/data/build_mapping.py` to generate it"
            ),
        )
    with open(_DATA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _form_summary(
    f: dict[str, Any], matched_questions: list[str] | None = None
) -> dict[str, Any]:
    return {
        "frm_code": f.get("frm_code"),
        "paket_name": f.get("paket_name"),
        "modul": f.get("modul"),
        "layanan_name": f.get("layanan_name"),
        "layanan_code": f.get("layanan_code"),
        "question_count": f.get("question_count"),
        "covered_question_count": f.get("covered_question_count"),
        "in_converter_breadcrumbs": f.get("in_converter_breadcrumbs"),
        "in_audit": f.get("in_audit"),
        "demos_union": f.get("demos_union") or [],
        "matched_questions": matched_questions or [],
    }


def _question_matches(q: dict[str, Any], needle: str) -> bool:
    """True when the search term hits any searchable field on this question."""
    if needle in str(q.get("label") or "").lower():
        return True
    for c in q.get("parameter_codes") or []:
        if needle in str(c).lower():
            return True
    for ch in q.get("choices") or []:
        if needle in str(ch.get("line") or "").lower():
            return True
        if needle in str(ch.get("code") or "").lower():
            return True
    for opt in q.get("live_options") or []:
        if needle in str(opt).lower():
            return True
    if needle in str(q.get("epus_source") or "").lower():
        return True
    if needle in str(q.get("live_name") or "").lower():
        return True
    return False


def _matching_question_labels(f: dict[str, Any], needle: str) -> list[str]:
    return [
        q.get("label") or ""
        for q in (f.get("questions") or [])
        if _question_matches(q, needle)
    ]


@router.get("/overview")
def mapping_overview(
    _: uuid.UUID = Depends(get_current_admin_id),
) -> dict[str, Any]:
    """Top-level stats for the dashboard header card."""
    doc = _load()
    forms: list[dict[str, Any]] = doc.get("forms", [])
    total_q = sum(int(f.get("question_count") or 0) for f in forms)
    covered_q = sum(int(f.get("covered_question_count") or 0) for f in forms)
    converter_forms = sum(1 for f in forms if f.get("in_converter_breadcrumbs"))
    audit_forms = sum(1 for f in forms if f.get("in_audit"))
    return {
        "form_count": len(forms),
        "question_count": total_q,
        "covered_question_count": covered_q,
        "converter_form_count": converter_forms,
        "audit_form_count": audit_forms,
        "epus_path_count": len(doc.get("epus_paths_index") or []),
        "source_xlsx": doc.get("source_xlsx"),
        "audit_dir": doc.get("audit_dir"),
    }


@router.get("/forms")
def list_forms(
    q: str | None = Query(default=None, description="search across paket name, FRM, modul, layanan"),
    coverage: str | None = Query(
        default=None,
        description="filter by converter coverage: covered | partial | none",
    ),
    has_audit: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> dict[str, Any]:
    doc = _load()
    forms = list(doc.get("forms", []))

    needle = (q or "").strip().lower()
    if needle:
        def matches(f: dict[str, Any]) -> bool:
            for key in ("paket_name", "frm_code", "modul", "layanan_name", "layanan_code"):
                v = f.get(key)
                if v and needle in str(v).lower():
                    return True
            for question in f.get("questions") or []:
                if _question_matches(question, needle):
                    return True
            return False
        forms = [f for f in forms if matches(f)]

    if coverage:
        cov = coverage.strip().lower()
        if cov == "covered":
            forms = [f for f in forms if f.get("covered_question_count") and f["covered_question_count"] >= int(f.get("question_count") or 0)]
        elif cov == "partial":
            forms = [
                f for f in forms
                if 0 < int(f.get("covered_question_count") or 0) < int(f.get("question_count") or 0)
            ]
        elif cov == "none":
            forms = [f for f in forms if int(f.get("covered_question_count") or 0) == 0]

    if has_audit is not None:
        forms = [f for f in forms if bool(f.get("in_audit")) == has_audit]

    total = len(forms)
    pages = max(1, (total + size - 1) // size)
    start = (page - 1) * size
    page_items = forms[start:start + size]
    return {
        "items": [
            _form_summary(
                f,
                _matching_question_labels(f, needle) if needle else None,
            )
            for f in page_items
        ],
        "total": total,
        "page": page,
        "pages": pages,
        "size": size,
    }


@router.get("/forms/{frm_code}")
def get_form(
    frm_code: str,
    _: uuid.UUID = Depends(get_current_admin_id),
) -> dict[str, Any]:
    """Per-FRM detail with all questions, choices, EPUS sources."""
    doc = _load()
    needle = frm_code.strip().lower()
    for f in doc.get("forms", []):
        code = (f.get("frm_code") or "").strip().lower()
        if code == needle:
            return f
    raise HTTPException(status_code=404, detail=f"form {frm_code} not found")


@router.get("/epus-paths")
def list_epus_paths(
    q: str | None = Query(default=None),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> dict[str, Any]:
    """Reverse index — EPUS path → list of ASIK destinations."""
    doc = _load()
    items = list(doc.get("epus_paths_index") or [])
    needle = (q or "").strip().lower()
    if needle:
        items = [
            it for it in items
            if needle in (it.get("path") or "").lower()
            or any(needle in (dest.get("form_name") or "").lower() for dest in it.get("destinations") or [])
            or any(needle in (dest.get("label") or "").lower() for dest in it.get("destinations") or [])
        ]
    return {"items": items, "total": len(items)}
