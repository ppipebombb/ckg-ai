import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.patient import MatchStatus


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    puskesmas_id: uuid.UUID
    nik: str
    nama: str
    match_status: MatchStatus
    has_asik_data: bool
    has_epus_data: bool
    has_merged_data: bool
    merged_at: datetime | None
    filter_date: date
    ruangan: str
    birth_date: date | None = None
    # CKG "Tandai-CKG" flag (epus_only + this true = a create-in-ASIK candidate).
    epus_tandai_ckg: bool | None = None
    match_group_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class PatientDecryptedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    puskesmas_id: uuid.UUID
    nik: str
    nama: str
    match_status: MatchStatus
    scraped_asik_data: Any | None = None
    scraped_epus_data: Any | None = None
    merged_data: Any | None = None
    merged_at: datetime | None = None
    filter_date: date
    match_group_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class AsikPreviewOut(BaseModel):
    id: uuid.UUID
    forms: dict[str, dict[str, Any]]
