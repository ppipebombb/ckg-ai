import math
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")

MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    page: int = Field(ge=1)
    size: int = Field(ge=1, le=MAX_PAGE_SIZE)


def page_params(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
) -> PageParams:
    return PageParams(page=page, size=size)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int


def paginate(db: Session, stmt: Select, params: PageParams) -> tuple[list, int, int]:
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.offset((params.page - 1) * params.size).limit(params.size)).all()
    pages = math.ceil(total / params.size) if total else 0
    return list(rows), total, pages


def paginate_execute(db: Session, stmt: Select, params: PageParams) -> tuple[list, int, int]:
    """For tuple/column-projection selects where db.scalars() would return only the first column."""
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = db.scalar(count_stmt) or 0
    rows = db.execute(stmt.offset((params.page - 1) * params.size).limit(params.size)).all()
    pages = math.ceil(total / params.size) if total else 0
    return list(rows), total, pages
