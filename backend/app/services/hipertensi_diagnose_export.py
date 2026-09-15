"""Render the Hipertensi "Full Review Diagnose" export workbook from dashboard data.

One row per visit-day reading, grouped by patient, with ``Nama Pasien`` and
``NIK`` merged vertically across each patient's rows (matching the on-screen
Diagnose table). Sistolik/Diastolik cells get the same green/red coloring the UI
uses (``bpClass`` in ``frontend-internal/lib/hipertensi-format.ts``): green iff
``sys<140 and dia<90`` (both present), else red — applied to the pair.

The layout/render is shared with the GD Puasa diagnose export; see
``app.services.diagnose_export`` for the (fast, raw-XML) builder. This module
only supplies the value-column headers, the reading keys, the pair-fill rule,
and the summary tally.
"""

from __future__ import annotations

from datetime import date
from typing import TypedDict

from app.services.diagnose_export import GREEN, RED, build_diagnose_workbook


class DiagnoseReading(TypedDict):
    date: date
    sys: float | None
    dia: float | None


class HipertensiDiagnoseExportRow(TypedDict):
    nama: str
    nik: str
    readings: list[DiagnoseReading]  # sorted ascending by date


def _pair_fill(sys: float | None, dia: float | None):
    """Green iff both present and sys<140 and dia<90; red if any present but out
    of range; None when the pair is entirely empty."""
    if sys is None and dia is None:
        return None
    if sys is not None and dia is not None and sys < 140 and dia < 90:
        return GREEN
    return RED


def build_hipertensi_diagnose_workbook(
    pk_name: str, year: int, rows: list[HipertensiDiagnoseExportRow]
) -> bytes:
    """Return the .xlsx bytes for the Full Review Diagnose view."""
    return build_diagnose_workbook(
        pk_name,
        year,
        rows,
        value_headers=("Sistolik", "Diastolik"),
        val_keys=("sys", "dia"),
        # Both cells share one pair-based fill.
        value_fills=lambda s, d: (_pair_fill(s, d), _pair_fill(s, d)),
        summary_extra=lambda _v1, _v2, total_bacaan: [("Total Bacaan", total_bacaan)],
    )
