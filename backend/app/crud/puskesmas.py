from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.core.security import decrypt_cred, encrypt_cred
from app.models.puskesmas import Puskesmas
from app.schemas.puskesmas import CredIn, PuskesmasCreate, PuskesmasUpdate

CredKind = Literal["epus", "asik"]


def create(db: Session, data: PuskesmasCreate) -> Puskesmas:
    obj = Puskesmas(
        name=data.name,
        epus_url=data.epus_url,
        asik_url=data.asik_url,
        asik_default_alamat=(
            data.asik_default_alamat.model_dump() if data.asik_default_alamat else None
        ),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update(db: Session, obj: Puskesmas, data: PuskesmasUpdate) -> Puskesmas:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return obj


def soft_delete(db: Session, obj: Puskesmas) -> None:
    obj.deleted_at = datetime.now(UTC)
    db.commit()


def set_cred(db: Session, obj: Puskesmas, kind: CredKind, data: CredIn) -> None:
    encrypted = encrypt_cred(data.model_dump())
    if kind == "epus":
        obj.epus_cred = encrypted
    else:
        obj.asik_cred = encrypted
    db.commit()


def clear_cred(db: Session, obj: Puskesmas, kind: CredKind) -> None:
    if kind == "epus":
        obj.epus_cred = None
    else:
        obj.asik_cred = None
    db.commit()


def get_cred_decrypted(obj: Puskesmas, kind: CredKind) -> dict[str, str] | None:
    token = obj.epus_cred if kind == "epus" else obj.asik_cred
    if token is None:
        return None
    return decrypt_cred(token)
