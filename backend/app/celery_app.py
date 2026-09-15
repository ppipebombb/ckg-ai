from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "ckg",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.scrape",
        "app.tasks.merge",
        "app.tasks.cron",
        "app.tasks.sync",
        "app.tasks.create_patient",
        "app.tasks.gdp_report",
        "app.tasks.loop_agent",
    ],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    # Default Redis-broker visibility_timeout is 3600s. Orchestrator-style
    # tasks (gdp_report.run) block in _wait_child for hours waiting on long
    # ASIK + EPUS scrapes — at 1h the broker would re-deliver the message
    # to the same worker and a second instance of the orchestrator would
    # run, spawning duplicate children. Bump to 24h.
    broker_transport_options={"visibility_timeout": 86400},
    # Loop-agent tasks run on their OWN dedicated queue so the maintenance agent
    # (which docker-runs a throwaway container) is fully isolated from the
    # scrape/merge/sync workers (PLAN §6). The default worker never sees them;
    # the celery_worker_loop service consumes `-Q loop` at concurrency=1.
    task_routes={"loop_agent.*": {"queue": "loop"}},
    # Business timezone — crontab beat entries below fire in WIB.
    timezone="Asia/Jakarta",
    beat_schedule={
        "cron-dispatch-due-every-minute": {
            "task": "cron.dispatch_due",
            "schedule": 60.0,
        },
        "cron-dispatch-school-due-every-minute": {
            "task": "cron.dispatch_school_due",
            "schedule": 60.0,
        },
        # Pre-warm the Conflict Analysis + GD Puasa dashboard caches daily so
        # users hit a warm cache instead of paying the cold-cache decrypt scan.
        "warm-reports-daily-0500": {
            "task": "cron.warm_reports",
            "schedule": crontab(hour=5, minute=0),
        },
        # Loop-agent nightly sweep (PLAN §6): picks never-checked portals up to
        # nightly_budget. No-op unless loop_config.nightly_enabled, so it is safe
        # to schedule unconditionally. Routed to the `loop` queue.
        "loop-agent-nightly-0000": {
            "task": "loop_agent.run_nightly",
            "schedule": crontab(hour=0, minute=0),
        },
    },
)
