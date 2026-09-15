import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.puskesmas import Puskesmas


class CronMergeMode(str, enum.Enum):
    """How a cron run / backfill treats the merge step.

    - NORMAL: scrape (EPUS+ASIK) then merge only patients not yet merged.
    - FORCE_REMERGE: scrape then re-merge every matched patient (re-calls LLM).
    - NO_MERGE: scrape only, skip the merge step entirely — lets scraping keep
      running while the LLM provider is down. Patients stay merged_at=NULL and
      are picked up by a later normal/force run or a date-range merge.
    """
    NORMAL = "normal"
    FORCE_REMERGE = "force_remerge"
    NO_MERGE = "no_merge"


class CronSyncMode(str, enum.Enum):
    """Whether/how a cron run pushes merged data into ASIK after the merge step.

    - OFF: no sync step (default) — the run stops after merge.
    - NORMAL: run the ASIK sync for patients merged for this date that are NOT
      yet synced (skips any with asik_synced_at set). The sync analog of a
      NORMAL merge (only-new).
    - FORCE_RESYNC: re-sync EVERY eligible patient for this date, ignoring the
      already-synced guard. The sync analog of FORCE_REMERGE.

    NO_MERGE + a sync mode is a no-op: advance() short-circuits to 'done' at the
    merge step, so the sync step never runs (nothing freshly merged to push).
    """
    OFF = "off"
    NORMAL = "normal"
    FORCE_RESYNC = "force_resync"


class CronSourceScope(str, enum.Enum):
    """Which source(s) a date-range backfill scrapes before the merge step.

    - BOTH: scrape EPUS then ASIK (the original chain), then merge.
    - EPUS_ONLY: scrape EPUS only, then merge. Skips the ASIK step.
    - ASIK_ONLY: scrape ASIK only, then merge. Skips the EPUS step.
    - NONE: scrape NOTHING (no rescrape). Start straight at MERGE (merge any
      matched-but-unmerged patients from data already on disk), then the ASIK
      sync step. A sync-only backfill — requires sync on and merge != no_merge
      (both enforced at create time). Occupies BOTH lanes → mutually exclusive
      with every other active run for the puskesmas (it writes merged_data and
      pushes to the one-account ASIK session, so nothing else may run alongside).

    Independent of merge_mode: scope picks the scraper(s); merge_mode still
    governs the merge. A run "occupies a lane" per source it touches (BOTH →
    EPUS+ASIK, EPUS_ONLY → EPUS, ASIK_ONLY → ASIK, NONE → both lanes). The two
    partial unique indexes on cron_runs use this to allow one EPUS-touching run
    and one ASIK-touching run per puskesmas concurrently (so EPUS_ONLY ∥
    ASIK_ONLY is allowed, but BOTH and NONE conflict with everything). Only
    CronBackfill exposes it; scheduled config / run-now runs are always BOTH.
    """
    BOTH = "both"
    EPUS_ONLY = "epus_only"
    ASIK_ONLY = "asik_only"
    NONE = "none"


# Lane occupancy per scope: a run "touches" a source lane when its scope includes
# that source. Two scopes conflict (cannot both be active for the same puskesmas)
# iff their lanes intersect — the same rule the two partial unique indexes on
# cron_runs (uq_cron_runs_active_epus / _asik) enforce at INSERT time.
_SCOPE_LANES: dict[CronSourceScope, frozenset[str]] = {
    CronSourceScope.BOTH: frozenset({"epus", "asik"}),
    CronSourceScope.EPUS_ONLY: frozenset({"epus"}),
    CronSourceScope.ASIK_ONLY: frozenset({"asik"}),
    # NONE doesn't scrape, but it merges + pushes to the one-account ASIK
    # session — occupy both lanes so it is mutually exclusive with every scope.
    CronSourceScope.NONE: frozenset({"epus", "asik"}),
}


def scopes_conflict(a: CronSourceScope, b: CronSourceScope) -> bool:
    return bool(_SCOPE_LANES[a] & _SCOPE_LANES[b])


class CronConfig(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    # Partial unique on (puskesmas_id) WHERE deleted_at IS NULL is created by
    # the migration; SoftDeleteMixin's auto-filter excludes soft-deleted rows
    # from SELECT, and IntegrityError on the partial index enforces the rule
    # for re-creation only when an active row exists.
    __tablename__ = "cron_configs"

    puskesmas_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("puskesmas.id"),
        nullable=False,
    )
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    minute: Mapped[int] = mapped_column(Integer, nullable=False)
    target_offset_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Rolling lookback window: each scheduled fire re-processes the last N days
    # ([target - (N-1) .. target]) so late-arriving EPUS/ASIK that only match a past
    # date once BOTH sides land still gets re-scraped + re-merged. 1 = just the target
    # date (legacy behavior). Implemented by spawning a CronBackfill over the window.
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    merge_mode: Mapped[CronMergeMode] = mapped_column(
        SAEnum(
            CronMergeMode,
            name="cron_merge_mode",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=CronMergeMode.NORMAL,
    )
    # Optional ASIK sync step after merge. OFF by default — a scheduled run only
    # scrapes + merges unless the admin opts in.
    sync_mode: Mapped[CronSyncMode] = mapped_column(
        SAEnum(
            CronSyncMode,
            name="cron_sync_mode",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=CronSyncMode.OFF,
    )
    # Optional ASIK create step AFTER sync: register this date's epus_only + tandai_ckg
    # patients into ASIK, then fill. OFF by default; only meaningful when sync_mode != OFF
    # (enforced at create/update time). Runs in the same one-account ASIK lane as sync.
    create_new: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    puskesmas: Mapped["Puskesmas"] = relationship()
