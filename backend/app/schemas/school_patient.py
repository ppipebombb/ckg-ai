import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.school_patient import SchoolScreeningStatus


class SchoolPatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    puskesmas_id: uuid.UUID
    nik: str
    nama: str
    born_date: date | None = None
    gender: str | None = None
    school_year: int
    school_name: str | None = None
    class_name: str | None = None
    klaster_name: str | None = None
    screening_status: SchoolScreeningStatus
    has_data: bool
    scraped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SchoolPatientDecryptedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    puskesmas_id: uuid.UUID
    nik: str
    nama: str
    school_year: int
    school_name: str | None = None
    class_name: str | None = None
    klaster_name: str | None = None
    screening_status: SchoolScreeningStatus
    scraped_sekolah_data: Any | None = None
    scraped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SchoolFacet(BaseModel):
    """One school with the distinct classes seen for it (powers the cascading
    Pilih Sekolah → Kelas dropdowns)."""

    name: str
    classes: list[str]


class SchoolFacetsOut(BaseModel):
    schools: list[SchoolFacet]
    school_years: list[int]
