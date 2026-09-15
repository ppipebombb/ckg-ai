import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.api.deps import get_dashboard_admin_id, get_db
from app.core.rate_limit import enforce_conflicts_rate_limit, redis_client
from app.core.report_warm import request_warm
from app.core.security import decrypt_json
from app.models.patient import MatchStatus, Patient

log = logging.getLogger(__name__)

router = APIRouter(prefix="/merge-conflicts", tags=["merge-conflicts"])

CACHE_TTL_SECONDS = 86400
CACHE_KEY_ALL = "merge:conflicts:summary:all"


def _cache_key(puskesmas_id: uuid.UUID | None) -> str:
    if puskesmas_id is None:
        return CACHE_KEY_ALL
    return f"merge:conflicts:summary:puskesmas:{puskesmas_id}"


def _prettify_slug(slug: str) -> str:
    return slug.replace("_", " ").strip().title()


class ConflictRow(BaseModel):
    section: str
    section_label: str
    merged_key: str
    asik_question: str | None = None
    epus_question: str | None = None
    conflict_count: int
    conflict_pct: float


class ConflictSummary(BaseModel):
    puskesmas_id: uuid.UUID | None
    total_patients: int
    conflicts: list[ConflictRow]
    computed_at: datetime | None  # None while a background recompute is running
    cache_hit: bool
    computing: bool = False  # True → recompute enqueued, poll until data arrives


def _iter_items(sections: dict):
    """Yield (section_slug, section_label, item) for every item in merged_data.

    Handles BOTH the post-_group_into_pakets nested shape AND the legacy
    flat shape (sections[slug] = [items]) in case any old rows exist.
    """
    if not isinstance(sections, dict):
        return
    for slug, value in sections.items():
        if isinstance(value, dict):
            label = value.get("layanan_label") or slug
            sub_sections = value.get("sub_sections") or {}
            if isinstance(sub_sections, dict):
                for sub in sub_sections.values():
                    if not isinstance(sub, dict):
                        continue
                    for it in sub.get("items") or []:
                        if isinstance(it, dict):
                            yield slug, label, it
        elif isinstance(value, list):
            for it in value:
                if isinstance(it, dict):
                    yield slug, slug, it


def _compute_summary(db: Session, puskesmas_id: uuid.UUID | None) -> dict:
    cutoff = date.today() - timedelta(days=365)
    stmt = (
        select(Patient)
        .options(load_only(Patient.id, Patient.merged_data))
        .where(
            Patient.match_status == MatchStatus.MATCHED,
            Patient.merged_data.is_not(None),
            Patient.filter_date >= cutoff,
        )
    )
    if puskesmas_id is not None:
        stmt = stmt.where(Patient.puskesmas_id == puskesmas_id)

    # Group on (slug, normalized_key) — case-folded + whitespace-collapsed —
    # so per-patient casing/spacing drift doesn't fragment the same logical
    # question into multiple rows.
    counts: dict[tuple[str, str], int] = {}
    labels: dict[str, str] = {}
    display_key: dict[tuple[str, str], str] = {}
    asik_q: dict[tuple[str, str], str] = {}
    epus_q: dict[tuple[str, str], str] = {}
    total_patients = 0

    for row in db.scalars(stmt):
        total_patients += 1
        try:
            merged = decrypt_json(row.merged_data)
        except Exception as exc:
            log.warning("decrypt_json failed for patient %s: %s", row.id, exc)
            continue
        sections = (merged or {}).get("sections") if isinstance(merged, dict) else None
        for slug, label, item in _iter_items(sections or {}):
            if not (item.get("is_conflict") is True and item.get("is_same_answer") is False):
                continue
            key = item.get("merged_key")
            if not isinstance(key, str) or not key.strip():
                continue
            norm = " ".join(key.split()).casefold()
            gk = (slug, norm)
            counts[gk] = counts.get(gk, 0) + 1
            if gk not in display_key:
                display_key[gk] = key.strip()
            if slug not in labels and label:
                labels[slug] = label
            aq = item.get("asik_question")
            if isinstance(aq, str) and aq and gk not in asik_q:
                asik_q[gk] = aq
            eq = item.get("epus_question")
            if isinstance(eq, str) and eq and gk not in epus_q:
                epus_q[gk] = eq

    rows = []
    for gk, count in counts.items():
        slug = gk[0]
        label = labels.get(slug) or _prettify_slug(slug)
        if label == slug:
            label = _prettify_slug(slug)
        rows.append({
            "section": slug,
            "section_label": label,
            "merged_key": display_key[gk],
            "asik_question": asik_q.get(gk),
            "epus_question": epus_q.get(gk),
            "conflict_count": count,
            "conflict_pct": round(count * 100.0 / total_patients, 2) if total_patients else 0.0,
        })
    rows.sort(key=lambda r: (-r["conflict_count"], r["merged_key"]))

    return {
        "total_patients": total_patients,
        "conflicts": rows,
        "computed_at": datetime.now(UTC).isoformat(),
    }


def warm_conflict_summary(db: Session, rc, puskesmas_id: uuid.UUID | None, ttl: int) -> dict:
    """Compute the conflict summary and write it to Redis. Shared by the
    on-miss endpoint path and the nightly warm-up cron (cron.warm_reports)."""
    key = _cache_key(puskesmas_id)
    payload = _compute_summary(db, puskesmas_id)
    try:
        rc.set(key, json.dumps(payload), ex=ttl)
    except Exception as exc:
        log.warning("redis set failed for %s: %s", key, exc)
    return payload


@router.get("/summary", response_model=ConflictSummary)
def get_conflict_summary(
    puskesmas_id: uuid.UUID | None = Query(default=None),
    top: int = Query(default=50, ge=1, le=50),
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_dashboard_admin_id),
) -> ConflictSummary:
    enforce_conflicts_rate_limit(admin_id)

    key = _cache_key(puskesmas_id)
    rc = redis_client()
    cached: str | None = None
    try:
        cached = rc.get(key)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", key, exc)

    payload = None
    cache_hit = False
    if cached:
        try:
            payload = json.loads(cached)
            cache_hit = True
        except Exception:
            payload = None

    if payload is None:
        # Heavy decrypt scan — recompute in the background and return a
        # `computing` placeholder so the request never blocks (no timeout).
        request_warm(rc, key, "conflict", {"puskesmas_id": str(puskesmas_id) if puskesmas_id else None})
        return ConflictSummary(
            puskesmas_id=puskesmas_id,
            total_patients=0,
            conflicts=[],
            computed_at=None,
            cache_hit=False,
            computing=True,
        )

    return ConflictSummary(
        puskesmas_id=puskesmas_id,
        total_patients=payload["total_patients"],
        conflicts=[ConflictRow(**r) for r in payload["conflicts"][:top]],
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        cache_hit=cache_hit,
        computing=False,
    )


@router.delete("/cache", status_code=status.HTTP_204_NO_CONTENT)
def clear_conflict_cache(
    puskesmas_id: uuid.UUID | None = Query(default=None),
    admin_id: uuid.UUID = Depends(get_dashboard_admin_id),
) -> None:
    enforce_conflicts_rate_limit(admin_id)
    key = _cache_key(puskesmas_id)
    rc = redis_client()
    try:
        rc.delete(key)
    except Exception as exc:
        log.warning("redis delete failed: %s", exc)
    # Kick off the recompute now so the data is ready by the time the client
    # polls back (instead of waiting for the next GET to enqueue it).
    request_warm(rc, key, "conflict", {"puskesmas_id": str(puskesmas_id) if puskesmas_id else None})
