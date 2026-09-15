"""Birth-date extraction from patient source blobs (EPUS / ASIK).

Canonical home for parsing a `datetime.date` out of the raw scraped blobs so
the denormalized `Patient.birth_date` column (the umur/age list filter) can be
populated by both the scrape write-path (crud/patient.py) and the one-time
backfill (scripts/backfill_patient_birth_date.py).

Precedence is EPUS-wins, else ASIK — the same rule the merge uses for the
identitas section (tasks/merge.py `_rebuild_identitas`). The two parsers mirror
the (string-returning) ones in services/hipertensi_registry_scan.py; the small
overlap is intentional — that module is a chatbot-pinned source file, so we keep
a standalone copy here rather than edit it.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

_MONTHS_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]
_MONTH_NUM = {m.casefold(): i for i, m in enumerate(_MONTHS_ID) if m}


def birth_date_from_epus(epus: Any) -> date | None:
    """Birth date from EPUS ``data_pasien`` "Tempat/Tgl Lahir" (or jaksel
    "Tempat & Tgl Lahir"). Anchors on the trailing ``DD-MM-YYYY`` so the
    place / separator / whitespace don't matter."""
    if not isinstance(epus, dict):
        return None
    dp = epus.get("data_pasien") or {}
    ttl = dp.get("Tempat/Tgl Lahir") or dp.get("Tempat & Tgl Lahir")
    if ttl in (None, ""):
        return None
    s = re.sub(r"\s+", " ", str(ttl)).strip()
    m = re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})\s*$", s)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def birth_date_from_asik(asik: Any) -> date | None:
    """Birth date from raw ASIK ``detail_data.data_individu`` "Tanggal Lahir"
    ("DD NamaBulan YYYY", e.g. "25 Januari 2000")."""
    if not isinstance(asik, dict):
        return None
    di = (asik.get("detail_data") or {}).get("data_individu") or {}
    raw = di.get("Tanggal Lahir")
    if raw in (None, ""):
        return None
    s = re.sub(r"\s+", " ", str(raw)).strip()
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", s)
    if not m:
        return None
    mo = _MONTH_NUM.get(m.group(2).casefold())
    if not mo:
        return None
    try:
        return date(int(m.group(3)), mo, int(m.group(1)))
    except ValueError:
        return None


def birth_date_for_patient(epus: Any, asik: Any) -> date | None:
    """EPUS-wins: the EPUS birth date if parseable, else the ASIK one."""
    return birth_date_from_epus(epus) or birth_date_from_asik(asik)
