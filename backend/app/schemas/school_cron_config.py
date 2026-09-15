import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SchoolCronConfigCreate(BaseModel):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    enabled: bool = True


class SchoolCronConfigUpdate(BaseModel):
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    enabled: bool | None = None


class SchoolCronConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    puskesmas_id: uuid.UUID
    hour: int
    minute: int
    enabled: bool
    next_run_at: datetime
    last_fired_at: datetime | None
    created_at: datetime
    updated_at: datetime
