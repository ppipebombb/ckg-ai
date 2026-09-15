"""Single-pass EPUS decrypt + per-report dashboard aggregation.

The GD Puasa and Hipertensi dashboards derive their (puskesmas, year) aggregate
from the SAME encrypted EPUS blobs — only the extracted fields differ.
Decryption is the heavy cost, so this module decrypts each blob exactly once and
feeds every requested report's extractors from that one pass. The nightly warm
cron uses it to build both dashboards in a single scan instead of two.

Per-report logic is a `DashboardSpec`; the payload produced here is the same
aggregate (verified semantically identical against live data — same NIKs, monthly
values, daily cells, flags) as the legacy per-report ``_compute_dashboard_payload``,
so the cached aggregate and every reader stay unchanged. (Nested key *insertion
order* may differ; the cache is always ``json.loads``-ed by key, so that is moot.)
"""

import itertools
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import decrypt_json
from app.models.patient import Patient

# Decrypted rows for one (nik, month) bucket — (filter_date, epus|None), DESC.
DecRows = list[tuple[date, Any]]


class DashboardSpec(NamedTuple):
    # epus dict -> {field: Decimal|None}. Insertion order defines the daily /
    # monthly cell key order and MUST match the legacy payload.
    extract_fields: Callable[[Any], dict[str, "Decimal | None"]]
    # decrypted rows (DESC) -> (monthly_value_jsonable, chosen_date) | (None, None).
    choose_month: Callable[[DecRows], tuple[Any, "date | None"]]


class _State:
    __slots__ = ("monthly", "daily", "qualified", "first_epus")

    def __init__(self) -> None:
        self.monthly: dict[str, dict[str, Any]] = {}
        self.daily: dict[str, dict[str, dict[str, str | None]]] = {}
        self.qualified: set[str] = set()
        self.first_epus: dict[str, tuple[int, date]] = {}


def scan_dashboard_payloads(
    db: Session,
    puskesmas_id: uuid.UUID,
    year: int,
    specs: dict[str, DashboardSpec],
    *,
    extract_tertatalaksana: Callable[[Any], tuple[bool, bool]],
    progress=None,
) -> dict[str, dict]:
    """Decrypt every EPUS blob for (puskesmas, year) ONCE; return one payload per
    entry in ``specs`` (keyed identically). Each payload is
    ``{niks, monthly, daily, computed_at}`` — the shape the per-report endpoints
    cache and read.

    ``progress`` (optional): a ``make_progress_writer`` callback ticked once per
    NIK (rows are grouped by ``(nik, month)`` but ordered by nik, so a new nik is
    detected by a change in the group key) so the on-miss warm can surface a
    progress bar. ``None`` (nightly both-dashboards path) → zero overhead."""
    year_start = date(year, 1, 1)
    year_end = date(year + 1, 1, 1)
    blob_q = (
        select(Patient.nik, Patient.filter_date, Patient.scraped_epus_data)
        .where(
            Patient.puskesmas_id == puskesmas_id,
            Patient.filter_date >= year_start,
            Patient.filter_date < year_end,
            Patient.scraped_epus_data.isnot(None),
        )
        .order_by(Patient.nik, Patient.filter_date.desc())
        .execution_options(yield_per=200, stream_results=True)
    )

    total = 0
    if progress:
        total = db.scalar(
            select(func.count(func.distinct(Patient.nik))).where(
                Patient.puskesmas_id == puskesmas_id,
                Patient.filter_date >= year_start,
                Patient.filter_date < year_end,
                Patient.scraped_epus_data.isnot(None),
            )
        ) or 0
    done = 0
    last_nik = None

    state = {name: _State() for name in specs}
    tert_obat: set[str] = set()
    tert_edukasi: set[str] = set()

    for (nik, month), group in itertools.groupby(
        db.execute(blob_q), key=lambda r: (r.nik, r.filter_date.month)
    ):
        if progress and nik != last_nik:
            last_nik = nik
            done += 1
            progress(done, total)
        # Decrypt each row in the bucket exactly once — the expensive step that
        # every spec then reads from.
        dec_rows: DecRows = []
        for r in group:
            try:
                epus = decrypt_json(r.scraped_epus_data)
            except Exception:
                epus = None
            dec_rows.append((r.filter_date, epus))

        # Tertatalaksana is report-independent; any "Ya"/"Diberikan Obat" sticks.
        for _fd, epus in dec_rows:
            if epus is None:
                continue
            obat, edukasi_flag = extract_tertatalaksana(epus)
            if obat:
                tert_obat.add(nik)
            if edukasi_flag:
                tert_edukasi.add(nik)

        for name, spec in specs.items():
            st = state[name]
            # Raw per-day cells. Rows are DESC, so the first non-null seen for a
            # (nik, date) is the latest.
            for fd, epus in dec_rows:
                if epus is None:
                    continue
                fields = spec.extract_fields(epus)
                if any(v is not None for v in fields.values()):
                    cell = st.daily.setdefault(nik, {}).setdefault(
                        fd.isoformat(), {k: None for k in fields}
                    )
                    for k, v in fields.items():
                        if v is not None and cell[k] is None:
                            cell[k] = str(v)
            # Month value via the per-report rule.
            mv, chosen_date = spec.choose_month(dec_rows)
            if mv is not None:
                st.monthly.setdefault(nik, {})[str(month)] = mv
                st.qualified.add(nik)
                existing = st.first_epus.get(nik)
                if (existing is None or month < existing[0]) and chosen_date is not None:
                    st.first_epus[nik] = (month, chosen_date)

    # One nik_q over the UNION of every report's qualified NIKs. MAX(nama) /
    # bool_or(tandai) per nik are independent of which report qualified it, so a
    # single grouped query yields the same per-nik values the legacy per-report
    # query did.
    union: set[str] = set().union(*(state[n].qualified for n in specs)) if specs else set()
    nikmeta: dict[str, tuple[str, bool]] = {}
    if union:
        nik_q = (
            select(
                Patient.nik.label("nik"),
                func.max(Patient.nama).label("nama"),
                func.bool_or(Patient.epus_tandai_ckg).label("tandai_ckg"),
            )
            .where(
                Patient.puskesmas_id == puskesmas_id,
                Patient.filter_date >= year_start,
                Patient.filter_date < year_end,
                Patient.nik.in_(union),
                Patient.scraped_epus_data.isnot(None),
            )
            .group_by(Patient.nik)
        )
        for r in db.execute(nik_q).all():
            nikmeta[r.nik] = (r.nama or "", bool(r.tandai_ckg))

    computed_at = datetime.now(UTC).isoformat()
    out: dict[str, dict] = {}
    for name, st in state.items():
        niks: list[dict[str, Any]] = []
        for nik in st.qualified:
            nama, tandai = nikmeta.get(nik, ("", False))
            chosen = st.first_epus.get(nik)
            niks.append({
                "nik": nik,
                "nama": nama,
                "first_epus_date": chosen[1].isoformat() if chosen else None,
                "tertatalaksana_obat": nik in tert_obat,
                "tertatalaksana_edukasi": nik in tert_edukasi,
                "tandai_ckg": tandai,
            })
        # Pre-sort by (nama, nik) so paginate-after-search is cheap. The set
        # iteration order above is irrelevant — (nama, nik) is a total order.
        niks.sort(key=lambda x: (x["nama"].casefold(), x["nik"]))
        out[name] = {
            "niks": niks,
            "monthly": st.monthly,
            "daily": st.daily,
            "computed_at": computed_at,
        }
    return out
