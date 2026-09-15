import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _validate_password_bytes(value: str) -> str:
    if len(value.encode("utf-8")) > 72:
        raise ValueError("password must be at most 72 bytes when UTF-8 encoded")
    return value


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str
    puskesmas_id: uuid.UUID

    @field_validator("password")
    @classmethod
    def _check_password_bytes(cls, value: str) -> str:
        return _validate_password_bytes(value)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=72)
    full_name: str | None = None
    puskesmas_id: uuid.UUID | None = None

    @field_validator("password")
    @classmethod
    def _check_password_bytes(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_password_bytes(value)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    puskesmas_id: uuid.UUID
    puskesmas_name: str
    created_at: datetime
    updated_at: datetime


class UserMeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    puskesmas_id: uuid.UUID
    puskesmas_name: str
    created_at: datetime
    updated_at: datetime
