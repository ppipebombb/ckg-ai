import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.cron_config import CronMergeMode, CronSyncMode


class CronConfigCreate(BaseModel):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    target_offset_days: int = Field(ge=-1, le=0)
    lookback_days: int = Field(default=3, ge=1, le=14)
    enabled: bool = True
    merge_mode: CronMergeMode = CronMergeMode.NORMAL
    sync_mode: CronSyncMode = CronSyncMode.OFF
    # ASIK create step after sync — only meaningful when sync is on.
    create_new: bool = False

    @model_validator(mode="after")
    def _create_requires_sync(self) -> "CronConfigCreate":
        if self.create_new and self.sync_mode is CronSyncMode.OFF:
            raise ValueError("create_new requires sync_mode to be enabled (not OFF)")
        return self


class CronConfigUpdate(BaseModel):
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    target_offset_days: int | None = Field(default=None, ge=-1, le=0)
    lookback_days: int | None = Field(default=None, ge=1, le=14)
    enabled: bool | None = None
    merge_mode: CronMergeMode | None = None
    sync_mode: CronSyncMode | None = None
    create_new: bool | None = None


class CronConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    puskesmas_id: uuid.UUID
    hour: int
    minute: int
    target_offset_days: int
    lookback_days: int
    enabled: bool
    merge_mode: CronMergeMode
    sync_mode: CronSyncMode
    create_new: bool
    next_run_at: datetime
    last_fired_at: datetime | None
    created_at: datetime
    updated_at: datetime
