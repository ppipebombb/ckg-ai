"""Unit tests for the cold-cache warm de-duplication fixes.

Two guards stop the "duplicate-warm thrash" (a scan slower than the 20-min
warming-flag TTL re-enqueuing itself every poll, then redundant copies re-running
after the cache is already filled):

- Fix A: ``_cache_fresh`` lets ``warm_one_report`` skip the decrypt when the cache
  is already populated (fail-safe: Redis error → proceed with the warm).
- Fix B: ``make_progress_writer`` heartbeats the ``:warming`` flag on each tick so
  a live scan never lets its own dedupe flag expire.
"""

from app.core.report_warm import (
    WARMING_FLAG_TTL_SECONDS,
    make_progress_writer,
    progress_key,
    warming_key,
)
from app.tasks.cron import _cache_fresh


class FakeRC:
    def __init__(self, *, exists_val: int = 0, exists_exc: Exception | None = None):
        self.exists_val = exists_val
        self.exists_exc = exists_exc
        self.sets: list[tuple] = []
        self.expires: list[tuple] = []

    def exists(self, key):
        if self.exists_exc is not None:
            raise self.exists_exc
        return self.exists_val

    def set(self, key, value, ex=None):
        self.sets.append((key, value, ex))

    def expire(self, key, ttl):
        self.expires.append((key, ttl))


# ── Fix A: _cache_fresh ─────────────────────────────────────────────────────
def test_cache_fresh_true_when_key_present():
    assert _cache_fresh(FakeRC(exists_val=1), "k") is True


def test_cache_fresh_false_when_key_absent():
    assert _cache_fresh(FakeRC(exists_val=0), "k") is False


def test_cache_fresh_failsafe_on_redis_error():
    # A Redis hiccup must return False so we proceed with the warm, never skip one.
    assert _cache_fresh(FakeRC(exists_exc=RuntimeError("redis down")), "k") is False


# ── Fix B: progress-writer heartbeat ────────────────────────────────────────
def test_writer_heartbeats_warming_flag_on_tick():
    rc = FakeRC()
    write = make_progress_writer(rc, "ck", buckets=10)
    write(100, 1000)  # step = 1000//10 = 100 → this is a real (throttled) tick
    assert rc.sets and rc.sets[-1][0] == progress_key("ck")
    assert (warming_key("ck"), WARMING_FLAG_TTL_SECONDS) in rc.expires


def test_writer_bounded_writes_with_matching_heartbeats():
    rc = FakeRC()
    write = make_progress_writer(rc, "ck", buckets=10)
    for i in range(1, 1001):
        write(i, 1000)
    # ~buckets + terminal tick, and one heartbeat per progress write.
    assert len(rc.sets) <= 12
    assert len(rc.expires) == len(rc.sets)
    assert rc.sets[-1][1] and '"done": 1000' in rc.sets[-1][1]  # terminal tick emitted
