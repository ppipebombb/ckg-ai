import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import case, cast, func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import decrypt_json, encrypt_json
from app.models.patient import MatchStatus, Patient
from app.models.scrape_job import ScrapeKind
from app.services.birthdate import birth_date_from_asik, birth_date_from_epus


def _extract_tandai_ckg(epus_entry: Any) -> bool | None:
    """ckg.sudah_ckg from one EPUS patient entry. None when no ckg key."""
    if not isinstance(epus_entry, dict):
        return None
    ckg = epus_entry.get("ckg")
    if not isinstance(ckg, dict) or "sudah_ckg" not in ckg:
        return None
    return bool(ckg.get("sudah_ckg"))


def _extract_epus_ruangan(epus_entry: Any) -> str:
    if not isinstance(epus_entry, dict):
        return ""
    dp = epus_entry.get("data_pasien") or {}
    val = dp.get("Poli/Ruangan")
    return (val or "").strip()


def _mandiri_complete(asik_entry: Any) -> bool:
    """True only when a scrape ATTEMPTED Mandiri AND captured it fully (no form
    errored). Drives the denormalized Patient.has_mandiri flag.

    Gating on completeness (not just "non-empty") is what makes the Mandiri-only
    backfill self-converge: a patient whose capture is missing OR partial (a tab
    open/read failure tags the form with `error` → mandiri_complete=False) stays
    in the backfill's target set and is retried next run, instead of being
    silently marked "done" with a hole that needs a manual re-scrape. The
    scraper sets mandiri_complete=True for an empty screening_forms too (no
    Mandiri applies to that patient → nothing to miss). A Nakes-only / list-only
    scrape never sets the flag, so has_mandiri stays False (will be backfilled).
    """
    if not isinstance(asik_entry, dict):
        return False
    return bool(asik_entry.get("mandiri_complete"))


def upsert_from_scrape(
    db: Session,
    puskesmas_id: uuid.UUID,
    kind: ScrapeKind,
    nik: str,
    nama: str,
    raw_data: Any,
    date_filter: str,
) -> str:  # "inserted" or "updated" — caller commits.
    parsed_date = date.fromisoformat(date_filter)
    encrypted = encrypt_json(raw_data)
    if kind == ScrapeKind.ASIK:
        birth_date = birth_date_from_asik(raw_data)
        return _upsert_asik(
            db, puskesmas_id, nik, nama, encrypted, parsed_date, birth_date,
            has_mandiri=_mandiri_complete(raw_data),
        )
    birth_date = birth_date_from_epus(raw_data)
    return _upsert_epus(
        db, puskesmas_id, nik, nama, raw_data, encrypted, parsed_date, birth_date
    )


def _find_cross_date_twin(
    db: Session,
    puskesmas_id: uuid.UUID,
    nik: str,
    parsed_date: date,
    *,
    need_blob: str,  # "epus" or "asik" — twin must have this blob set
) -> Any | None:
    """Find the unique closest live row in ±MATCH_WINDOW_DAYS for the same
    (puskesmas, nik) that is a single-source orphan on the opposite side
    (epus_only when we want an EPUS twin; asik_only otherwise).

    Returns the row (id, filter_date, scraped_*_data, match_group_id) when a
    single unambiguous twin exists. Returns None if zero candidates, if the
    nearest is ambiguous (two rows equidistant), or the window is disabled.

    Already-matched rows are skipped on purpose — a same-NIK row that is
    already paired (whether same-day-matched or cross-date-paired via
    match_group_id) is treated as a distinct earlier visit, and the new
    arrival becomes a new visit instead of being re-merged into the old one.
    Same-date rows are also skipped — they go through the exact-date branch
    of the upsert.
    """
    window_days = settings.MATCH_WINDOW_DAYS
    if window_days <= 0:
        return None
    require_status = (
        MatchStatus.EPUS_ONLY if need_blob == "epus" else MatchStatus.ASIK_ONLY
    )
    rows = db.execute(
        select(
            Patient.id,
            Patient.filter_date,
            Patient.scraped_asik_data,
            Patient.scraped_epus_data,
            Patient.match_group_id,
            Patient.birth_date,
        ).where(
            Patient.puskesmas_id == puskesmas_id,
            Patient.nik == nik,
            Patient.match_status == require_status,
            Patient.match_group_id.is_(None),
            Patient.filter_date != parsed_date,
            Patient.filter_date.between(
                parsed_date - timedelta(days=window_days),
                parsed_date + timedelta(days=window_days),
            ),
        ).order_by(
            func.abs(Patient.filter_date - parsed_date).asc(),
            Patient.filter_date.asc(),
        ).limit(2)
    ).all()
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    nearest, second = rows[0], rows[1]
    if abs((nearest.filter_date - parsed_date).days) == abs(
        (second.filter_date - parsed_date).days
    ):
        # Two candidates equidistant — ambiguous, leave as un-grouped.
        return None
    return nearest


def _upsert_epus(
    db: Session,
    puskesmas_id: uuid.UUID,
    nik: str,
    nama: str,
    raw_data: Any,
    encrypted: bytes,
    parsed_date: date,
    birth_date: date | None,
) -> str:
    ruangan = _extract_epus_ruangan(raw_data)
    # CKG "sudah CKG" flag — denormalized as plain Boolean so the Visit
    # Summary can COUNT it without decrypting blobs.
    tandai_ckg = _extract_tandai_ckg(raw_data)
    # Snapshot live siblings for (puskesmas, nik, filter_date). Tiny set
    # (≤ one per distinct ruangan). Skip the encrypted blob — just need a
    # has_asik flag here; fetch the bytes only if we actually need to copy.
    siblings = db.execute(
        select(
            Patient.id,
            Patient.ruangan,
            Patient.scraped_asik_data.isnot(None).label("has_asik"),
        ).where(
            Patient.puskesmas_id == puskesmas_id,
            Patient.nik == nik,
            Patient.filter_date == parsed_date,
        )
    ).all()
    exact = next((r for r in siblings if r.ruangan == ruangan), None)
    empty_twin = (
        next((r for r in siblings if r.ruangan == ""), None) if ruangan != "" else None
    )
    target = exact or empty_twin
    if target is not None:
        # Step 1: exact (puskesmas, nik, date, ruangan) match → update in place.
        # Step 2: no exact match but a ruangan="" sibling exists (ASIK-seeded
        #         orphan) → promote it to this EPUS ruangan instead of forking
        #         a new row.
        values: dict[str, Any] = {
            "scraped_epus_data": encrypted,
            "epus_tandai_ckg": tandai_ckg,
            "match_status": case(
                (
                    Patient.scraped_asik_data.isnot(None),
                    cast(MatchStatus.MATCHED, Patient.match_status.type),
                ),
                else_=cast(MatchStatus.EPUS_ONLY, Patient.match_status.type),
            ),
            "deleted_at": None,
            "updated_at": func.now(),
        }
        if target is empty_twin:
            values["ruangan"] = ruangan
        if nama:
            values["nama"] = nama
        if birth_date is not None:
            # EPUS-wins: an EPUS birth date overrides whatever ASIK seeded.
            values["birth_date"] = birth_date
        db.execute(
            update(Patient)
            .where(Patient.id == target.id, Patient.deleted_at.is_(None))
            .values(**values)
        )
        db.flush()
        return "updated"
    # Step 3: no exact ruangan row and no empty-twin to promote. Insert a new
    # row for this ruangan and copy scraped_asik_data from any live sibling on
    # the same (puskesmas, nik, filter_date) so MATCHED is preserved.
    sibling_asik: bytes | None = None
    sibling_with_asik = next((r for r in siblings if r.has_asik), None)
    if sibling_with_asik is not None:
        sibling_asik = db.scalar(
            select(Patient.scraped_asik_data).where(Patient.id == sibling_with_asik.id)
        )
    # Step 3b: if there is no same-date sibling AT ALL, fall back to a
    # cross-date twin lookup. A live ASIK_ONLY row for the same (puskesmas,
    # nik) within ±MATCH_WINDOW_DAYS (and not already grouped) becomes our
    # twin: both rows get a shared match_group_id, both flip to MATCHED,
    # and each carries both blobs so the merge can run from either side.
    cross_twin = (
        None
        if siblings
        else _find_cross_date_twin(
            db, puskesmas_id, nik, parsed_date, need_blob="asik",
        )
    )
    if cross_twin is not None:
        gid = uuid.uuid4()
        # NOTE: epus_tandai_ckg is set ONLY on the EPUS-side row (the new
        # insert below). The ASIK-side twin keeps it NULL; the Visit Summary
        # count collapses cross-date twins by match_group_id anyway, so the
        # same visit is never double-counted.
        twin_values: dict[str, Any] = {
            "scraped_epus_data": encrypted,
            "match_status": MatchStatus.MATCHED,
            "match_group_id": gid,
            "updated_at": func.now(),
        }
        if birth_date is not None:
            # EPUS-wins: arriving EPUS birth date overrides the ASIK twin's.
            twin_values["birth_date"] = birth_date
        db.execute(
            update(Patient)
            .where(Patient.id == cross_twin.id, Patient.deleted_at.is_(None))
            .values(**twin_values)
        )
        insert_values: dict[str, Any] = {
            "puskesmas_id": puskesmas_id,
            "nik": nik,
            "nama": nama,
            "match_status": MatchStatus.MATCHED,
            "filter_date": parsed_date,
            "ruangan": ruangan,
            "scraped_epus_data": encrypted,
            "epus_tandai_ckg": tandai_ckg,
            "scraped_asik_data": cross_twin.scraped_asik_data,
            "birth_date": birth_date if birth_date is not None else cross_twin.birth_date,
            "match_group_id": gid,
        }
        stmt = pg_insert(Patient).values(**insert_values)
        excluded = stmt.excluded
        set_dict: dict[str, Any] = {
            "scraped_epus_data": excluded.scraped_epus_data,
            "epus_tandai_ckg": excluded.epus_tandai_ckg,
            "scraped_asik_data": case(
                (Patient.scraped_asik_data.is_(None), excluded.scraped_asik_data),
                else_=Patient.scraped_asik_data,
            ),
            "nama": case((excluded.nama != "", excluded.nama), else_=Patient.nama),
            "match_status": cast(MatchStatus.MATCHED, Patient.match_status.type),
            "match_group_id": case(
                (Patient.match_group_id.is_(None), excluded.match_group_id),
                else_=Patient.match_group_id,
            ),
            "birth_date": case(
                (excluded.birth_date.isnot(None), excluded.birth_date),
                else_=Patient.birth_date,
            ),
            "deleted_at": None,
            "updated_at": func.now(),
        }
        result = db.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    Patient.puskesmas_id, Patient.nik, Patient.filter_date, Patient.ruangan,
                ],
                set_=set_dict,
            ).returning(literal_column("xmax = 0").label("inserted"))
        )
        db.flush()
        row = result.one()
        return "inserted" if row.inserted else "updated"
    insert_values: dict[str, Any] = {
        "puskesmas_id": puskesmas_id,
        "nik": nik,
        "nama": nama,
        "match_status": (
            MatchStatus.MATCHED if sibling_asik is not None else MatchStatus.EPUS_ONLY
        ),
        "filter_date": parsed_date,
        "ruangan": ruangan,
        "scraped_epus_data": encrypted,
        "epus_tandai_ckg": tandai_ckg,
        "scraped_asik_data": sibling_asik,
        "birth_date": birth_date,
    }
    stmt = pg_insert(Patient).values(**insert_values)
    excluded = stmt.excluded
    # on_conflict guard for the rare race / soft-deleted twin with the same
    # ruangan: preserve any already-set scraped_asik_data on the existing row,
    # otherwise fall back to the copy we computed above.
    set_dict: dict[str, Any] = {
        "scraped_epus_data": excluded.scraped_epus_data,
        "epus_tandai_ckg": excluded.epus_tandai_ckg,
        "nama": case((excluded.nama != "", excluded.nama), else_=Patient.nama),
        "scraped_asik_data": case(
            (Patient.scraped_asik_data.is_(None), excluded.scraped_asik_data),
            else_=Patient.scraped_asik_data,
        ),
        "match_status": case(
            (
                Patient.scraped_asik_data.isnot(None),
                cast(MatchStatus.MATCHED, Patient.match_status.type),
            ),
            (
                excluded.scraped_asik_data.isnot(None),
                cast(MatchStatus.MATCHED, Patient.match_status.type),
            ),
            else_=cast(MatchStatus.EPUS_ONLY, Patient.match_status.type),
        ),
        "birth_date": case(
            (excluded.birth_date.isnot(None), excluded.birth_date),
            else_=Patient.birth_date,
        ),
        "deleted_at": None,
        "updated_at": func.now(),
    }
    result = db.execute(
        stmt.on_conflict_do_update(
            index_elements=[
                Patient.puskesmas_id, Patient.nik, Patient.filter_date, Patient.ruangan,
            ],
            set_=set_dict,
        ).returning(literal_column("xmax = 0").label("inserted"))
    )
    db.flush()
    row = result.one()
    return "inserted" if row.inserted else "updated"


def _upsert_asik(
    db: Session,
    puskesmas_id: uuid.UUID,
    nik: str,
    nama: str,
    encrypted: bytes,
    parsed_date: date,
    birth_date: date | None,
    has_mandiri: bool = False,
) -> str:
    # ASIK ignores ruangan: one NIK on one filter_date may map to multiple live
    # rows (one per EPUS Poli/Ruangan). Write scraped_asik_data to ALL of them.
    # Soft-delete auto-filter (CLAUDE.md §6) excludes deleted rows from the SELECT.
    existing_ids = list(
        db.scalars(
            select(Patient.id).where(
                Patient.puskesmas_id == puskesmas_id,
                Patient.nik == nik,
                Patient.filter_date == parsed_date,
            )
        )
    )
    if existing_ids:
        values: dict[str, Any] = {
            "scraped_asik_data": encrypted,
            "match_status": case(
                (
                    Patient.scraped_epus_data.isnot(None),
                    cast(MatchStatus.MATCHED, Patient.match_status.type),
                ),
                else_=cast(MatchStatus.ASIK_ONLY, Patient.match_status.type),
            ),
            "updated_at": func.now(),
        }
        if nama:
            values["nama"] = nama
        if birth_date is not None:
            # ASIK fills only when empty — never clobber an EPUS-derived value.
            values["birth_date"] = func.coalesce(Patient.birth_date, birth_date)
        if has_mandiri:
            # Only ever flip to True — a later list-only/Nakes-only scrape must
            # not reset a row that already captured Mandiri.
            values["has_mandiri"] = True
        db.execute(
            update(Patient)
            .where(
                Patient.id.in_(existing_ids),
                Patient.deleted_at.is_(None),
            )
            .values(**values)
        )
        db.flush()
        return "updated"
    # Cross-date twin lookup: ASIK lags EPUS by days–weeks for the same
    # visit. If a live EPUS_ONLY row exists for this (puskesmas, nik) within
    # ±MATCH_WINDOW_DAYS and is not already paired, link the two rows under
    # a shared match_group_id and flip both to MATCHED. The two rows keep
    # their own filter_date for audit / lag reporting.
    twin = _find_cross_date_twin(
        db, puskesmas_id, nik, parsed_date, need_blob="epus",
    )
    if twin is not None:
        gid = uuid.uuid4()
        twin_values: dict[str, Any] = {
            "scraped_asik_data": encrypted,
            "match_status": MatchStatus.MATCHED,
            "match_group_id": gid,
            "updated_at": func.now(),
        }
        if birth_date is not None:
            # ASIK fills only when empty — keep the EPUS twin's birth date.
            twin_values["birth_date"] = func.coalesce(Patient.birth_date, birth_date)
        db.execute(
            update(Patient)
            .where(Patient.id == twin.id, Patient.deleted_at.is_(None))
            .values(**twin_values)
        )
        insert_values: dict[str, Any] = {
            "puskesmas_id": puskesmas_id,
            "nik": nik,
            "nama": nama,
            "match_status": MatchStatus.MATCHED,
            "filter_date": parsed_date,
            "ruangan": "",
            "scraped_asik_data": encrypted,
            "scraped_epus_data": twin.scraped_epus_data,
            "birth_date": twin.birth_date if twin.birth_date is not None else birth_date,
            "match_group_id": gid,
            "has_mandiri": has_mandiri,
        }
        stmt = pg_insert(Patient).values(**insert_values)
        excluded = stmt.excluded
        set_dict: dict[str, Any] = {
            "scraped_asik_data": excluded.scraped_asik_data,
            "scraped_epus_data": case(
                (Patient.scraped_epus_data.is_(None), excluded.scraped_epus_data),
                else_=Patient.scraped_epus_data,
            ),
            "nama": case((excluded.nama != "", excluded.nama), else_=Patient.nama),
            "match_status": cast(MatchStatus.MATCHED, Patient.match_status.type),
            "match_group_id": case(
                (Patient.match_group_id.is_(None), excluded.match_group_id),
                else_=Patient.match_group_id,
            ),
            "birth_date": case(
                (Patient.birth_date.is_(None), excluded.birth_date),
                else_=Patient.birth_date,
            ),
            # Never downgrade an already-Mandiri row.
            "has_mandiri": case(
                (Patient.has_mandiri.is_(True), True), else_=has_mandiri
            ),
            "deleted_at": None,
            "updated_at": func.now(),
        }
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    Patient.puskesmas_id, Patient.nik, Patient.filter_date, Patient.ruangan,
                ],
                set_=set_dict,
            )
        )
        db.flush()
        return "inserted"
    # No live row for this (puskesmas, nik, filter_date) — insert a fresh
    # ASIK_ONLY row with ruangan="". on_conflict handles the case where a
    # soft-deleted ruangan="" twin already occupies the unique slot.
    insert_values: dict[str, Any] = {
        "puskesmas_id": puskesmas_id,
        "nik": nik,
        "nama": nama,
        "match_status": MatchStatus.ASIK_ONLY,
        "filter_date": parsed_date,
        "ruangan": "",
        "scraped_asik_data": encrypted,
        "birth_date": birth_date,
        "has_mandiri": has_mandiri,
    }
    stmt = pg_insert(Patient).values(**insert_values)
    excluded = stmt.excluded
    set_dict: dict[str, Any] = {
        "scraped_asik_data": excluded.scraped_asik_data,
        "nama": case((excluded.nama != "", excluded.nama), else_=Patient.nama),
        "match_status": case(
            (
                Patient.scraped_epus_data.isnot(None),
                cast(MatchStatus.MATCHED, Patient.match_status.type),
            ),
            else_=cast(MatchStatus.ASIK_ONLY, Patient.match_status.type),
        ),
        "birth_date": case(
            (Patient.birth_date.is_(None), excluded.birth_date),
            else_=Patient.birth_date,
        ),
        # Never downgrade an already-Mandiri row.
        "has_mandiri": case(
            (Patient.has_mandiri.is_(True), True), else_=has_mandiri
        ),
        "deleted_at": None,
        "updated_at": func.now(),
    }
    result = db.execute(
        stmt.on_conflict_do_update(
            index_elements=[
                Patient.puskesmas_id, Patient.nik, Patient.filter_date, Patient.ruangan,
            ],
            set_=set_dict,
        ).returning(literal_column("xmax = 0").label("inserted"))
    )
    db.flush()
    row = result.one()
    return "inserted" if row.inserted else "updated"


def patch_mandiri_from_scrape(
    db: Session,
    puskesmas_id: uuid.UUID,
    nik: str,
    raw_entry: Any,
    date_filter: str,
) -> str:  # "updated" or "skipped" — caller commits.
    """Patch the `pemeriksaan_mandiri` key into existing ASIK blobs WITHOUT
    replacing them (preserves already-scraped Nakes/Tatalaksana).

    Used by the Mandiri-only backfill: a mandiri-only scrape produces an entry
    with only `pemeriksaan_mandiri` populated, so the normal whole-blob upsert
    (`_upsert_asik`) would wipe Nakes. Here we decrypt each live ASIK row for
    (puskesmas, nik, filter_date), splice in the new Mandiri list, re-encrypt,
    and set has_mandiri. Rows without an existing ASIK blob are skipped — the
    backfill only targets patients already in our DB.
    """
    parsed_date = date.fromisoformat(date_filter)
    mandiri = (
        raw_entry.get("pemeriksaan_mandiri") or []
        if isinstance(raw_entry, dict) else []
    )
    # Only mark the patient "done" (has_mandiri=True) when the capture was
    # COMPLETE. If a form errored this run, leave has_mandiri=False so the next
    # backfill re-targets the patient — the partial data we just wrote is
    # overwritten on the successful retry. This is what lets repeated backfills
    # converge without ever needing a manual re-run.
    complete = _mandiri_complete(raw_entry)
    rows = db.execute(
        select(Patient.id, Patient.scraped_asik_data).where(
            Patient.puskesmas_id == puskesmas_id,
            Patient.nik == nik,
            Patient.filter_date == parsed_date,
            Patient.scraped_asik_data.isnot(None),
        )
    ).all()
    if not rows:
        return "skipped"
    for row in rows:
        blob = decrypt_json(row.scraped_asik_data)
        if not isinstance(blob, dict):
            continue
        blob["pemeriksaan_mandiri"] = mandiri
        db.execute(
            update(Patient)
            .where(Patient.id == row.id, Patient.deleted_at.is_(None))
            .values(
                scraped_asik_data=encrypt_json(blob),
                has_mandiri=complete,
                updated_at=func.now(),
            )
        )
    db.flush()
    return "updated"


def decrypt_field(obj: Patient, kind: ScrapeKind) -> Any | None:
    blob = obj.scraped_asik_data if kind == ScrapeKind.ASIK else obj.scraped_epus_data
    if blob is None:
        return None
    return decrypt_json(blob)


def soft_delete(db: Session, obj: Patient) -> None:
    obj.deleted_at = datetime.now(UTC)
    db.commit()


def apply_merge(
    db: Session,
    patient_id: uuid.UUID,
    merged_blob: bytes,
    merged_at: datetime,
) -> None:
    # Targeted update: only the two merge cols. Soft-delete auto-filter does not
    # apply to UPDATEs, so the .where guard is explicit (CLAUDE.md §6).
    db.execute(
        update(Patient)
        .where(Patient.id == patient_id, Patient.deleted_at.is_(None))
        .values(merged_data=merged_blob, merged_at=merged_at, updated_at=func.now())
    )


def decrypt_merged(obj: Patient) -> Any | None:
    if obj.merged_data is None:
        return None
    return decrypt_json(obj.merged_data)


def set_asik_default_fills(
    db: Session,
    patient_id: uuid.UUID,
    fills: list[dict] | None,
    *,
    mark_synced: bool = False,
) -> None:
    """Record the default values the sync pushed to ASIK for this patient.

    Overwrites (each sync recomputes the full set). When `mark_synced` is True
    (a successful sync) also stamp asik_synced_at=now, so the cron sync step in
    NORMAL mode skips this patient next time (FORCE_RESYNC ignores it). Does not
    commit — the caller's mark_success commit persists it. Soft-delete auto-filter
    does not apply to UPDATEs, so the guard is explicit (CLAUDE.md §6).
    """
    values: dict = {"asik_default_fills": fills, "updated_at": func.now()}
    if mark_synced:
        values["asik_synced_at"] = func.now()
    db.execute(
        update(Patient)
        .where(Patient.id == patient_id, Patient.deleted_at.is_(None))
        .values(**values)
    )
