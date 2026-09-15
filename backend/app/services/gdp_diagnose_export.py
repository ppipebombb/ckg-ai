"""Render the GD Puasa "Full Review Diagnose" export workbook from dashboard data.

One row per visit-day reading, grouped by patient, with ``Nama Pasien`` and
``NIK`` merged vertically across each patient's rows (matching the on-screen
Diagnose table). Lab/PTM cells get the same green/red coloring the UI uses
(``gdpClass`` in ``frontend-internal/lib/gdp-format.ts``): ``80 ≤ v ≤ 130`` → green, else
red — applied per value.

The layout/render is shared with the Hipertensi diagnose export; see
``app.services.diagnose_export`` for the (fast, raw-XML) builder. This module
only supplies the value-column headers, the reading keys, the per-value fill
rule, and the lab/ptm summary tally.
"""

from __future__ import annotations

from datetime import date
from typing import TypedDict

from app.services.diagnose_export import GREEN, RED, build_diagnose_workbook


class DiagnoseReading(TypedDict):
    date: date
    lab: float | None
    ptm: float | None


class GdpDiagnoseExportRow(TypedDict):
    nama: str
    nik: str
    readings: list[DiagnoseReading]  # sorted ascending by date


def _fill_for(v: float | None):
    if v is None:
        return None
    return GREEN if 80 <= v <= 130 else RED


def build_gdp_diagnose_workbook(
    pk_name: str, year: int, rows: list[GdpDiagnoseExportRow]
) -> bytes:
    """Return the .xlsx bytes for the Full Review Diagnose view."""
    return build_diagnose_workbook(
        pk_name,
        year,
        rows,
        value_headers=("Lab", "PTM"),
        val_keys=("lab", "ptm"),
        # Lab and PTM are colored independently.
        value_fills=lambda lab, ptm: (_fill_for(lab), _fill_for(ptm)),
        summary_extra=lambda total_lab, total_ptm, total_bacaan: [
            ("Total Lab", total_lab),
            ("Total PTM", total_ptm),
            ("Total Bacaan", total_bacaan),
        ],
    )
