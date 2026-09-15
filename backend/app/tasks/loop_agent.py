import json
import logging
import queue
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.celery_app import celery_app
from app.config import settings
from app.core.security import decrypt_json
from app.crud import llm_config as llm_config_crud
from app.crud import loop_config as loop_config_crud
from app.crud import loop_run as crud
from app.database import SessionLocal
from app.models.loop_run import LoopRun, LoopRunStatus, LoopTrigger
from app.models.puskesmas import Puskesmas
from app.schemas.loop_run import LoopCoverageFindingOut
from app.services.github_pr import reconcile_needs_review

log = logging.getLogger(__name__)

LOG_RING_MAX = 1000
LOG_TTL_SECONDS = 86400
# The container emits its final verdict as one stdout line with this prefix
# (mirrors the scraper's LLM_USAGE: convention). Everything else is a log line.
_RESULT_PREFIX = "LOOP_RESULT:"
_HEARTBEAT_EVERY_S = 15.0
_TICK_S = 2.0


def _log_key(run_id: str) -> str:
    return f"loop:run:{run_id}:log"


def _stream_chan(run_id: str) -> str:
    return f"loop:run:{run_id}:stream"


def _cancel_key(run_id: str) -> str:
    return f"loop:run:{run_id}:cancel"


def _resolve_repo_root() -> Path:
    """Host path to the repo, bind-mounted into the container as the seed tree.

    LOOP_HOST_REPO_PATH wins (set it when the worker runs inside a container so
    the HOST path reaches `docker run -v`). Otherwise auto-detect the repo root
    — correct when the worker runs natively on the Mac.
    """
    if settings.LOOP_HOST_REPO_PATH:
        return Path(settings.LOOP_HOST_REPO_PATH)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "loop-agent").is_dir() and (parent / "backend").is_dir():
            return parent
    return here.parents[3]  # backend/app/tasks/loop_agent.py -> repo root


def _resolve_llm(db: Session, active) -> dict[str, str] | None:
    """Env dict for one llm_config role, or None when unusable."""
    if active is None:
        return None
    try:
        api_key = decrypt_json(active.api_key_enc)["api_key"]
    except Exception:
        return None
    if not api_key:
        return None
    return {
        "model": active.model,
        "base_url": active.base_url,
        "api_key": api_key,
        "reasoning": active.reasoning_effort or "",
        "route_order": active.route_order or "",
    }


def _build_env_args(
    run_id: str,
    puskesmas_name: str,
    portal_url: str,
    agent_llm: dict[str, str],
    reviewer_llm: dict[str, str] | None,
    pin_ref: str | None,
    merge_mode: str,
    max_fix_iters: int,
    max_review_iters: int,
    open_pr: bool,
) -> list[str]:
    """`-e KEY=VALUE` args for `docker run`. Secrets are passed as env, never
    baked into the image. EPUS credentials are NOT here — the container decrypts
    them itself from the read-only DB (the gate logs in, not the worker), so
    portal credentials never sit in `docker inspect`-able env."""
    # Routing pin precedence: the row's own route_order, else the worker-wide
    # LOOP_LLM_ROUTE_ORDER env (kept as fallback). The reviewer inherits the
    # agent's effective pin when its own row doesn't set one.
    agent_route = agent_llm.get("route_order") or settings.LOOP_LLM_ROUTE_ORDER or ""
    reviewer_route = (reviewer_llm or {}).get("route_order") or agent_route
    env: dict[str, str] = {
        "LOOP_RUN_ID": run_id,
        "LOOP_PUSKESMAS_NAME": puskesmas_name,
        "LOOP_PORTAL_URL": portal_url,
        "LOOP_LLM_MODEL": agent_llm["model"],
        "LOOP_LLM_BASE_URL": agent_llm["base_url"],
        "LOOP_LLM_API_KEY": agent_llm["api_key"],
        "LOOP_LLM_REASONING": agent_llm["reasoning"],
        "LOOP_REVIEWER_ENABLED": "1" if reviewer_llm else "0",
        "LOOP_REVIEWER_MODEL": (reviewer_llm or {}).get("model", ""),
        "LOOP_REVIEWER_BASE_URL": (reviewer_llm or {}).get("base_url", ""),
        "LOOP_REVIEWER_API_KEY": (reviewer_llm or {}).get("api_key", ""),
        "LOOP_REVIEWER_REASONING": (reviewer_llm or {}).get("reasoning", ""),
        "LOOP_PIN_REF": pin_ref or "",
        # From the loop_config singleton (+ the per-run PR decision).
        "LOOP_MERGE_MODE": merge_mode,
        "LOOP_MAX_FIX_ITERS": str(max_fix_iters),
        "LOOP_MAX_REVIEW_ITERS": str(max_review_iters),
        "LOOP_OPEN_PR": "1" if open_pr else "0",
        "LOOP_DETAIL_LIMIT": str(settings.LOOP_DETAIL_LIMIT),
        "LOOP_GITHUB_TOKEN": settings.LOOP_GITHUB_TOKEN or "",
        "LOOP_GITHUB_REPO": settings.LOOP_GITHUB_REPO or "",
        "LOOP_PR_REVIEWERS": settings.LOOP_PR_REVIEWERS or "",
        "LOOP_PR_ASSIGNEES": settings.LOOP_PR_ASSIGNEES or "",
        "LOOP_LLM_ROUTE_ORDER": agent_route,
        "LOOP_REVIEWER_ROUTE_ORDER": reviewer_route,
        # The in-container gate + regression gate (verify_converter) import app
        # code and READ the DB, so they need the DB + the app-config-required
        # secrets. DATABASE_URL is the READ-ONLY role when LOOP_AGENT_DB_URL is
        # set; the gate never writes. CRED_ENCRYPTION_KEY decrypts the EPUS
        # creds + scraped blobs inside the container. Documented trade-off: the
        # agent can read these via `env` (PLAN §8.2) — resource-capped container
        # on our VPS, read-only DB role.
        "DATABASE_URL": settings.LOOP_AGENT_DB_URL or settings.DATABASE_URL,
        "REDIS_URL": settings.REDIS_URL,
        "CRED_ENCRYPTION_KEY": settings.CRED_ENCRYPTION_KEY,
        "JWT_SECRET": settings.JWT_SECRET,
        "ADMIN_EMAIL": settings.ADMIN_EMAIL,
        "ADMIN_PASSWORD": settings.ADMIN_PASSWORD,
    }
    args: list[str] = []
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    return args


def _drain_stdout(stdout, out_q: "queue.Queue", rc: "redis.Redis", log_key: str, chan: str) -> None:
    """Runs in a thread. NEVER touches the DB Session (not thread-safe) — it only
    pushes to Redis for live streaming and hands lines to the main thread via a
    queue for DB persistence."""
    try:
        for raw in stdout:
            line = raw.rstrip("\n").replace("\r", "")
            if line.startswith(_RESULT_PREFIX):
                out_q.put(("__result__", line[len(_RESULT_PREFIX):].strip()))
                continue
            out_q.put(("log", line))
            try:
                rc.rpush(log_key, line)
                rc.ltrim(log_key, -LOG_RING_MAX, -1)
                rc.expire(log_key, LOG_TTL_SECONDS)
                rc.publish(chan, line)
            except Exception:
                pass
    except Exception:
        pass


def _map_result_to_status(
    decision: str | None, merge_mode: str, has_pr: bool, open_pr: bool, pushed: bool,
) -> LoopRunStatus:
    if decision == "covered":
        return LoopRunStatus.COVERED
    if decision == "no_data":
        return LoopRunStatus.NO_DATA
    if decision == "bad_login":
        return LoopRunStatus.BAD_CREDS
    if decision == "fixed" or decision == "gap":
        # The run wrote code: a human (or auto mode) must still take the
        # branch before it reaches master. changes_ready requires a PUSHED
        # branch — "work is safe on GitHub" must never be a false claim; an
        # unpushed patch (no token / push failed) parks in needs_review like
        # a failed PR open does.
        if has_pr and merge_mode == "auto":
            return LoopRunStatus.MERGED
        if not open_pr and not has_pr:
            return LoopRunStatus.CHANGES_READY if pushed else LoopRunStatus.NEEDS_REVIEW
        return LoopRunStatus.NEEDS_REVIEW
    return LoopRunStatus.FAILED


@celery_app.task(bind=True, name="loop_agent.run_one")
def run_one(self, run_id: str) -> None:
    db: Session = SessionLocal()
    rc = redis.from_url(settings.REDIS_URL, decode_responses=True)
    log_key = _log_key(run_id)
    chan = _stream_chan(run_id)
    cancel_key = _cancel_key(run_id)
    run: LoopRun | None = None
    container_name = f"loop-run-{run_id}"
    t0 = time.monotonic()
    try:
        run_uuid = uuid.UUID(run_id)
        run = db.scalar(
            select(LoopRun)
            .options(load_only(
                LoopRun.id, LoopRun.puskesmas_id, LoopRun.status, LoopRun.pin_ref,
                LoopRun.open_pr,
            ))
            .where(LoopRun.id == run_uuid)
        )
        if run is None:
            return
        if run.status == LoopRunStatus.CANCELLED:
            return

        puskesmas = db.scalar(
            select(Puskesmas)
            .options(load_only(
                Puskesmas.id, Puskesmas.name, Puskesmas.epus_url,
            ))
            .where(Puskesmas.id == run.puskesmas_id)
        )
        if puskesmas is None:
            crud.mark_failed(db, run, "puskesmas not found", datetime.now(UTC))
            rc.publish(chan, "__failed__")
            return
        if not puskesmas.epus_url:
            crud.mark_failed(db, run, "puskesmas has no epus_url", datetime.now(UTC))
            rc.publish(chan, "__failed__")
            return
        # EPUS credentials are deliberately NOT resolved here — the container
        # decrypts them from the (read-only) DB itself, so portal credentials
        # never pass through the worker or container env (PLAN §8.2).

        agent_cfg = _resolve_llm(db, llm_config_crud.get_active_for_loop_agent(db))
        if agent_cfg is None:
            crud.mark_failed(
                db, run,
                "no usable loop-agent llm_config — add one and set "
                "'Atur untuk Loop Agent' in Konfigurasi LLM before running the loop",
                datetime.now(UTC),
            )
            rc.publish(chan, "__failed__")
            return
        # Reviewer is optional (no fallback by design). Unset => the container
        # skips the review step and the run lands in needs_review.
        reviewer_cfg = _resolve_llm(db, llm_config_crud.get_active_for_loop_reviewer(db))

        cfg = loop_config_crud.get_or_create(db)
        merge_mode = cfg.merge_mode.value
        # Frozen at creation for manual runs (run.open_pr); nightly runs follow
        # the config live.
        open_pr = run.open_pr if run.open_pr is not None else cfg.auto_open_pr

        portal_url = f"https://{puskesmas.epus_url}"
        repo_root = _resolve_repo_root()

        cmd = [
            settings.LOOP_DOCKER_BIN, "run", "--rm",
            "--name", container_name,
            "--init",
            f"--memory={settings.LOOP_AGENT_MEMORY}",
            f"--pids-limit={settings.LOOP_AGENT_PIDS_LIMIT}",
            f"--cpus={settings.LOOP_AGENT_CPUS}",
            f"--shm-size={settings.LOOP_AGENT_SHM_SIZE}",
        ]
        # Join the app's docker network so the in-container gate can resolve
        # `postgres` (creds + patient fixtures). Without it the gate can't run.
        if settings.LOOP_AGENT_NETWORK:
            cmd += ["--network", settings.LOOP_AGENT_NETWORK]
        cmd += [
            "-v", f"{repo_root}:/seed:ro",
            *_build_env_args(
                run_id, puskesmas.name, portal_url, agent_cfg, reviewer_cfg,
                run.pin_ref, merge_mode, cfg.max_fix_iterations,
                cfg.max_review_iterations, open_pr,
            ),
            settings.LOOP_AGENT_IMAGE,
        ]

        crud.mark_running(db, run, self.request.id or "", container_name, datetime.now(UTC))
        rc.delete(cancel_key)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
        )
        out_q: queue.Queue = queue.Queue()
        drain = threading.Thread(
            target=_drain_stdout, args=(proc.stdout, out_q, rc, log_key, chan), daemon=True,
        )
        drain.start()

        last_heartbeat = t0
        seq = 0
        result_json: dict | None = None
        cancelled = False
        timed_out = False
        timeout_s = max(1, int(settings.LOOP_RUN_TIMEOUT_SECONDS))

        def _persist_pending() -> None:
            nonlocal seq, result_json
            while True:
                try:
                    kind, payload = out_q.get_nowait()
                except queue.Empty:
                    break
                if kind == "__result__":
                    try:
                        result_json = json.loads(payload)
                    except json.JSONDecodeError:
                        log.warning("loop run %s emitted an unparseable LOOP_RESULT", run_id)
                    continue
                if seq >= settings.LOOP_EVENT_CAP:
                    continue  # runaway session — drop, keep the summary row sane
                seq += 1
                try:
                    crud.append_event(db, run_uuid, seq, kind, payload, datetime.now(UTC))
                except Exception:
                    db.rollback()

        while proc.poll() is None:
            time.sleep(_TICK_S)
            _persist_pending()
            now = time.monotonic()
            if now - last_heartbeat >= _HEARTBEAT_EVERY_S:
                try:
                    crud.heartbeat(db, run, datetime.now(UTC))
                except Exception:
                    db.rollback()
                last_heartbeat = now
            if now - t0 > timeout_s:
                timed_out = True
                _docker_kill(container_name)
                break
            try:
                if rc.get(cancel_key) == "1":
                    cancelled = True
                    _docker_kill(container_name)
                    break
            except Exception:
                pass

        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        drain.join(timeout=5)
        _persist_pending()  # flush the tail

        finished = datetime.now(UTC)
        duration = time.monotonic() - t0
        if cancelled:
            # Cancel route already wrote CANCELLED; just signal the stream.
            rc.publish(chan, "__cancelled__")
            return
        if timed_out:
            crud.mark_failed(
                db, run, f"loop run exceeded {timeout_s}s wall clock — container killed", finished,
            )
            rc.publish(chan, "__failed__")
            return
        if proc.returncode != 0 and result_json is None:
            tail = "\n".join(rc.lrange(log_key, -30, -1) or [])
            crud.mark_failed(db, run, f"container exit={proc.returncode}\n{tail}"[:4000], finished)
            rc.publish(chan, "__failed__")
            return

        result_json = result_json or {}
        decision = result_json.get("decision")
        pr_url = result_json.get("pr_url")
        pushed = bool(result_json.get("pushed"))
        status = _map_result_to_status(decision, merge_mode, bool(pr_url), open_pr, pushed)
        # A verdict file without the key (old shape, or a run with no capture)
        # stays None; an explicit [] (captured, hunted, found nothing) persists.
        # Items are validated against the API schema because ONE malformed item
        # would otherwise 500 every run endpoint that serializes this column.
        coverage_findings = result_json.get("coverage_findings")
        if coverage_findings is not None:
            if not isinstance(coverage_findings, list):
                log.warning("loop run %s sent a non-list coverage_findings — ignored", run_id)
                coverage_findings = None
            else:
                cleaned: list[dict] = []
                for item in coverage_findings:
                    try:
                        cleaned.append(LoopCoverageFindingOut.model_validate(item).model_dump())
                    except Exception:
                        log.warning(
                            "loop run %s dropped a malformed coverage finding: %r",
                            run_id, item,
                        )
                coverage_findings = cleaned
        crud.mark_finished(
            db, run, status, finished,
            decision=decision,
            test_date=result_json.get("test_date"),
            live_count=result_json.get("live_count"),
            scraped_count=result_json.get("scraped_count"),
            gap_summary=result_json.get("gap_summary"),
            coverage_findings=coverage_findings,
            branch_name=result_json.get("branch_name"),
            pr_url=pr_url,
            review_verdict=result_json.get("review_verdict"),
            review_comments=result_json.get("review_comments"),
            duration_seconds=round(duration, 1),
        )
        # Stamp the "checked" clock ONLY on reached verdicts (covered / no_data).
        # A needs_review/merged run does NOT stamp: the portal must be re-checked
        # after its fix lands, and that next run will stamp it covered.
        if status in (LoopRunStatus.COVERED, LoopRunStatus.NO_DATA):
            try:
                crud.mark_puskesmas_checked(db, run.puskesmas_id, finished)
            except Exception:
                db.rollback()
        rc.publish(chan, "__done__")
    except Exception as e:
        db.rollback()
        if run is not None:
            try:
                db.refresh(run, ["status"])
                if run.status not in (LoopRunStatus.CANCELLED,):
                    crud.mark_failed(db, run, str(e)[:2000], datetime.now(UTC))
            except Exception:
                pass
        try:
            rc.publish(chan, "__failed__")
        except Exception:
            pass
        # Best-effort: never leave the container running if the task blew up.
        _docker_kill(container_name)
        raise
    finally:
        db.close()


def _docker_kill(container_name: str) -> None:
    try:
        subprocess.run(
            [settings.LOOP_DOCKER_BIN, "kill", container_name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )
    except Exception:
        pass


@celery_app.task(name="loop_agent.run_nightly")
def run_nightly() -> None:
    """Nightly sweep (PLAN §6): pick only the puskesmas that have NEVER reached a
    verdict, capped to the budget, and enqueue one loop run each. No-op unless
    loop_config.nightly_enabled — safe to schedule unconditionally in beat.
    Routed to the `loop` queue like run_one, so it serializes behind the
    concurrency-1 worker."""
    db: Session = SessionLocal()
    try:
        cfg = loop_config_crud.get_or_create(db)
        # Reconcile runs daily even when the sweep is off; it only polls GitHub to
        # settle PR statuses (merged / pr_rejected) and never dispatches a run.
        reconcile_needs_review(db)
        if not cfg.nightly_enabled:
            return
        targets = crud.select_nightly_targets(db, cfg.nightly_budget)
        for pid in targets:
            run = crud.create(
                db, puskesmas_id=pid, trigger=LoopTrigger.NIGHTLY, triggered_by_id=None,
            )
            try:
                celery_app.send_task("loop_agent.run_one", args=[str(run.id)])
            except Exception:
                crud.mark_failed(
                    db, run, "broker unreachable when enqueuing nightly run", datetime.now(UTC),
                )
    finally:
        db.close()
