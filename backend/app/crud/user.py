from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


def create(db: Session, data: UserCreate) -> User:
    obj = User(
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        puskesmas_id=data.puskesmas_id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update(db: Session, obj: User, data: UserUpdate) -> User:
    payload = data.model_dump(exclude_unset=True)
    pw = payload.pop("password", None)
    if pw is not None:
        obj.password_hash = hash_password(pw)
    for field, value in payload.items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return obj


def soft_delete(db: Session, obj: User) -> None:
    obj.deleted_at = datetime.now(UTC)
    db.commit()
