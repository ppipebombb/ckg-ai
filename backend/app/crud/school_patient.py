import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.security import encrypt_json
from app.models.patient import Patient
from app.models.school_patient import SchoolPatient, SchoolScreeningStatus

_STATUS_MAP = {
    "belum": SchoolScreeningStatus.BELUM,
    "sedang": SchoolScreeningStatus.SEDANG,
    "selesai": SchoolScreeningStatus.SELESAI,
}


def _parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _school_year(student: dict, now: datetime) -> int:
    """CKG year for the upsert key: the register_date's year, else current year."""
    rd = _parse_iso_date(student.get("register_date"))
    if rd is not None:
        return rd.year
    return now.year


def upsert_from_school_scrape(
    db: Session,
    puskesmas_id: uuid.UUID,
    student: dict,
    now: datetime,
) -> str:  # "inserted" or "updated" — caller commits.
    """Upsert one CKG-Sekolah student (flat keys emitted by the scraper).

    Keyed by (puskesmas_id, nik, school_year): a re-scrape of the same student
    in the same CKG year updates in place; next year's checkup is a new row.
    Also sets patients.is_ckg_sekolah on any live CKG-Umum row with this NIK
    (cheap cross-reference; school CKG itself lives only in this table).
    """
    nik = (student.get("nik") or "").strip()
    nama = (student.get("nama") or "").strip()
    status = _STATUS_MAP.get(
        (student.get("screening_status") or "").strip().lower(),
        SchoolScreeningStatus.BELUM,
    )
    school_year = _school_year(student, now)

    values: dict[str, Any] = {
        "puskesmas_id": puskesmas_id,
        "nik": nik,
        "nama": nama,
        "born_date": _parse_iso_date(student.get("born_date")),
        "gender": (student.get("gender") or "").strip() or None,
        "school_year": school_year,
        "reg_id": (student.get("reg_id") or "").strip() or None,
        "ticket_number": (student.get("ticket_number") or "").strip() or None,
        "school_code": (student.get("school_code") or "").strip() or None,
        "school_name": (student.get("school_name") or "").strip() or None,
        "category_code": (student.get("category_code") or "").strip() or None,
        "class_name": (student.get("class_name") or "").strip() or None,
        "klaster_code": (student.get("klaster_code") or "").strip() or None,
        "klaster_name": (student.get("klaster_name") or "").strip() or None,
        "screening_status": status,
        "scraped_sekolah_data": encrypt_json(student),
        "scraped_at": now,
    }

    stmt = pg_insert(SchoolPatient).values(**values)
    excluded = stmt.excluded
    set_dict = {
        k: getattr(excluded, k)
        for k in values
        if k not in ("puskesmas_id", "nik", "school_year")
    }
    set_dict["deleted_at"] = None  # re-scrape revives a soft-deleted row
    set_dict["updated_at"] = func.now()
    result = db.execute(
        stmt.on_conflict_do_update(
            index_elements=[
                SchoolPatient.puskesmas_id,
                SchoolPatient.nik,
                SchoolPatient.school_year,
            ],
            set_=set_dict,
        ).returning(literal_column("xmax = 0").label("inserted"))
    )
    row = result.one()

    # Cross-link: flag any live CKG-Umum patient row sharing this NIK. UPDATE is
    # not covered by the soft-delete auto-filter (CLAUDE.md §6) — guard here.
    if nik:
        db.execute(
            update(Patient)
            .where(
                Patient.puskesmas_id == puskesmas_id,
                Patient.nik == nik,
                Patient.deleted_at.is_(None),
                func.coalesce(Patient.is_ckg_sekolah, False).is_(False),
            )
            .values(is_ckg_sekolah=True, updated_at=func.now())
        )

    return "inserted" if row.inserted else "updated"


_LIST_COLS = (
    SchoolPatient.id, SchoolPatient.nik, SchoolPatient.nama,
    SchoolPatient.born_date, SchoolPatient.gender,
    SchoolPatient.school_name, SchoolPatient.class_name,
    SchoolPatient.klaster_name, SchoolPatient.screening_status,
    SchoolPatient.school_year, SchoolPatient.scraped_at,
    SchoolPatient.created_at, SchoolPatient.updated_at,
)


def get(db: Session, school_patient_id: uuid.UUID) -> SchoolPatient | None:
    return db.scalar(
        select(SchoolPatient).where(SchoolPatient.id == school_patient_id)
    )


def soft_delete(db: Session, obj: SchoolPatient) -> None:
    obj.deleted_at = datetime.now(UTC)
    db.commit()
