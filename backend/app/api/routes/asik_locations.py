"""Read-only proxy over ASIK's public teritorial-service location cascade.

The puskesmas form (frontend-internal) lets an admin pick a default domicile —
Provinsi / Kota / Kecamatan / Kelurahan — for the ASIK "create new patient" flow.
The names MUST match ASIK's registration cascade exactly, so we source them from
ASIK's own teritorial-service (a PUBLIC, plain-JSON API — no auth) rather than a
third-party dataset. See documents/create-patient-asik/FINDINGS.md §6.

Contract (per level, POST body): `search` (server-side name match — the only
working filter), `page`, `limit`. There is NO server-side parent filter, so we
request a page and scope children by their `parent_code` here. Each item is
`{name, code, parent_code}`; `code` is the official Kemendagri wilayah code.
"""
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import get_current_admin_id

router = APIRouter(prefix="/asik-locations", tags=["asik-locations"])

_ASIK_TERITORIAL_BASE = "https://sehatindonesiaku.kemkes.go.id/api/teritorial-service"
# province → city → district (kecamatan) → subdistrict (kelurahan)
_LEVELS = ("province", "city", "district", "subdistrict")
# One page is enough: a name search narrows to a handful of matches, then the
# parent_code filter narrows further. 100 comfortably covers a searched level.
_PAGE_LIMIT = 100
_HTTP_TIMEOUT = 10.0


class AsikLocationOut(BaseModel):
    name: str
    code: str


@router.get("/{level}", response_model=list[AsikLocationOut])
def list_asik_locations(
    level: str,
    search: str = Query(default="", max_length=100),
    parent_code: str | None = Query(default=None, max_length=16),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> list[AsikLocationOut]:
    if level not in _LEVELS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown location level")
    if level != "province" and not parent_code:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "parent_code is required for this level",
        )
    if parent_code is not None and not parent_code.isdigit():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "parent_code must be numeric")

    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.post(
                f"{_ASIK_TERITORIAL_BASE}/{level}",
                json={"search": search or "", "limit": _PAGE_LIMIT},
            )
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "ASIK location service unavailable"
        ) from exc

    out: list[AsikLocationOut] = []
    seen: set[str] = set()
    for item in payload.get("data") or []:
        name = item.get("name")
        code = item.get("code")
        if not name or not code:
            continue
        # Scope children to the chosen parent (the API returns cross-parent
        # name matches — e.g. "Cipondoh" exists in two kecamatan).
        if level != "province" and str(item.get("parent_code")) != str(parent_code):
            continue
        if str(code) in seen:
            continue
        seen.add(str(code))
        out.append(AsikLocationOut(name=str(name), code=str(code)))
    return out
