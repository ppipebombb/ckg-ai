"""Async warm orchestration for heavy Redis-cached reports.

A cold cache miss (or a manual refresh) on a report whose compute is an O(N)
blob-decrypt scan can take minutes. Doing that inside the HTTP request risks a
gateway/uvicorn timeout. Instead the route enqueues a Celery task and returns a
`computing` response immediately; the frontend polls until the cache fills.

State lives entirely in Redis so it survives a browser reload and is shared
across users:

- ``<cache_key>:warming`` — NX flag, short TTL. Set when a warm is enqueued,
  deleted by the task when it finishes. While set, the GET returns `computing`
  instead of recomputing synchronously. NX dedupes concurrent callers; the TTL
  self-heals if the worker dies mid-compute (the next GET re-enqueues).
- ``<cache_key>:progress`` — approximate ``{phase, done, total}`` written by the
  running scan (see ``make_progress_writer``), read by the ``computing`` GET so
  the UI can show a determinate bar. Same TTL as the flag; cleared with it when
  the task finishes.
"""

import json
import logging

log = logging.getLogger(__name__)

# Longer than the worst-case single-report compute (GDP dashboard ~3 min) so a
# healthy task always clears the flag itself; short enough that a dead worker
# unblocks within a few minutes.
WARMING_FLAG_TTL_SECONDS = 20 * 60


def warming_key(cache_key: str) -> str:
    return f"{cache_key}:warming"


def progress_key(cache_key: str) -> str:
    return f"{cache_key}:progress"


def make_progress_writer(rc, cache_key: str, *, buckets: int = 100):
    """Return a throttled ``write(done, total, phase="decrypting")`` callback that
    records approximate scan progress to ``<cache_key>:progress`` for the polling
    GET to surface (see ``read_progress``).

    Writes are bounded to ~``buckets`` per scan (a Redis SET only every
    ``total // buckets`` items, plus the final one), so instrumenting a loop of N
    rows costs at most ~``buckets`` sub-millisecond local Redis calls — negligible
    against a multi-minute decrypt. Every write is best-effort: a Redis error is
    swallowed so progress reporting can never break or stall the compute.

    Each throttled tick also **heartbeats the ``:warming`` flag** (refreshes its
    TTL): a scan that outlives ``WARMING_FLAG_TTL_SECONDS`` (the heavy hipertensi
    scans do) would otherwise let its own dedupe flag expire mid-run, so the
    polling GET re-enqueues duplicate warms. Refreshing on each tick (~once every
    few seconds for a multi-minute scan) keeps a live scan's flag alive; if the
    worker dies the ticks stop and the flag still self-heals ~TTL later."""
    key = progress_key(cache_key)
    wkey = warming_key(cache_key)
    state = {"last": -1}

    def write(done: int, total: int, phase: str = "decrypting") -> None:
        step = max(1, total // buckets)
        # Always emit the terminal tick; otherwise throttle to one per step.
        if done < total and done - state["last"] < step:
            return
        state["last"] = done
        try:
            rc.set(
                key,
                json.dumps({"phase": phase, "done": done, "total": total}),
                ex=WARMING_FLAG_TTL_SECONDS,
            )
            # Heartbeat the dedupe flag so a long scan never re-enqueues itself.
            rc.expire(wkey, WARMING_FLAG_TTL_SECONDS)
        except Exception:
            pass

    return write


def read_progress(rc, cache_key: str) -> dict | None:
    """Read the ``<cache_key>:progress`` blob (``{phase, done, total}``) written by
    ``make_progress_writer`` for a ``computing`` GET to surface, or ``None`` if no
    progress has been recorded yet (or Redis is unreachable)."""
    try:
        raw = rc.get(progress_key(cache_key))
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def request_warm(rc, cache_key: str, report_type: str, kwargs: dict) -> None:
    """Enqueue a background recompute for ``cache_key`` unless one is already in
    flight. ``report_type`` + ``kwargs`` are dispatched by the
    ``report.warm_one`` Celery task to the matching ``warm_*`` helper."""
    # Imported here to avoid a core<->celery import cycle at module load.
    from app.celery_app import celery_app

    try:
        won = rc.set(warming_key(cache_key), "1", nx=True, ex=WARMING_FLAG_TTL_SECONDS)
    except Exception as exc:
        log.warning("warming flag set failed for %s: %s", cache_key, exc)
        won = True  # best-effort: still enqueue rather than stall forever

    if not won:
        return  # another caller already enqueued this warm

    try:
        celery_app.send_task("report.warm_one", args=[report_type, kwargs])
    except Exception as exc:
        log.warning("enqueue warm failed for %s: %s", cache_key, exc)
        # Roll back the flag so a later request can retry the enqueue.
        try:
            rc.delete(warming_key(cache_key))
        except Exception:
            pass
