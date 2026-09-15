import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import redis
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only

from app.celery_app import celery_app
from app.config import settings
from app.core.resource_sampler import ResourceSampler
from app.crud import llm_log as llm_log_crud
from app.crud import patient as patient_crud
from app.crud import puskesmas as puskesmas_crud
from app.crud import sync_job as sync_job_crud
from app.database import SessionLocal
from app.models.cron_config import CronSyncMode
from app.models.cron_run import CronRun
from app.models.llm_config import LlmConfig
from app.models.patient import MatchStatus, Patient
from app.models.puskesmas import Puskesmas
from app.models.scrape_job import ScrapeKind, TriggererType
from app.models.sync_job import SyncJob, SyncStatus
from app.services.asik_defaults import build_default_values_map
from app.services.epus_to_asik import epus_to_asik
from app.tasks.merge import _values_equal
from app.tasks.scrape import (
    STDOUT_DRAIN_JOIN_TIMEOUT_SECONDS,
    SCRAPERS_ROOT,
    LlmConfigUnreadable,
    _asik_session_dir,
    _build_captcha_solver,
    _build_subprocess_env,
    _drain_to_redis,
)

_PER_MILLION = Decimal("1000000")

# Scope decision (2026-07-21): ASIK sync submits ONLY AI-merged data — a patient
# must be MATCHED + merged (has merged_data). The EPUS-only fallback (convert raw
# ePuskesmas → ASIK shape and submit without an AI merge) is DISABLED, not removed:
# flip this to True to restore it. Gated in run_sync (below) and routes/sync.py.
ALLOW_EPUS_ONLY_SYNC = False

# Skip forms whose every value ASIK already holds (see `_annotate_same_as_asik`).
# OFF while the runner reports `would_prune` per form without acting on it, so the
# real elimination rate is measured on live data before anything stops being
# submitted. Flip to True to turn the measurement into the saving.
PRUNE_UNCHANGED_FORMS = False

# Patients per parallel round = concurrency * this. Bigger means fewer
# sequential bootstrap patients (less overhead) but a longer stretch on one
# session snapshot before it is refreshed — and a stale snapshot costs a whole
# round of requeues. 4 keeps a round well inside the observed session life at
# ~100 s/patient while amortising the bootstrap over 4 patients per worker.
_SYNC_ROUND_MULTIPLIER = 4


def _annotate_same_as_asik(merged: Any) -> Any:
    """Stamp every merged item with `same_as_asik` for the runner's elimination pass.

    ~7 forms are submitted per patient and each costs ~13 s, but a large share of
    them push values ASIK already has — a no-op submit. The runner cannot decide
    that itself: equality here is `merge.py:_values_equal`, the *same* comparator
    that decided the merge (numeric-tolerant, case-insensitive, and False whenever
    either side is None). Deciding it here rather than reimplementing it in the
    scraper is what keeps the two definitions from drifting apart.

    `_values_equal(x, None) is False`, so a field ASIK does not have can never
    look prunable. Mutates in place: `merged` is a freshly-decrypted blob per
    patient (`patient_crud.decrypt_merged`), not the ORM attribute.
    """
    sections = (merged or {}).get("sections")
    if not isinstance(sections, dict):
        return merged  # asik_preview shape (epus-only fallback) carries no asik_value

    def _stamp(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, dict):
                item["same_as_asik"] = _values_equal(
                    item.get("merged_value"), item.get("asik_value")
                )

    for payload in sections.values():
        if isinstance(payload, list):
            _stamp(payload)  # legacy flat shape
        elif isinstance(payload, dict):
            for sub in (payload.get("sub_sections") or {}).values():
                if isinstance(sub, dict):
                    _stamp(sub.get("items"))
    return merged


def _calc_cost(tokens: int | None, rate: Decimal | None) -> Decimal | None:
    if tokens is None or rate is None:
        return None
    return Decimal(tokens) * rate / _PER_MILLION


log = logging.getLogger(__name__)


def _log_key(job_id: str) -> str:
    return f"sync:job:{job_id}:log"


def _stream_chan(job_id: str) -> str:
    return f"sync:job:{job_id}:stream"


def _cancel_key(job_id: str) -> str:
    return f"sync:job:{job_id}:cancel"


_JOB_TASK_COLS = (
    SyncJob.id, SyncJob.puskesmas_id, SyncJob.patient_id, SyncJob.status,
    SyncJob.celery_task_id, SyncJob.forms_total, SyncJob.forms_succeeded,
    SyncJob.forms_failed, SyncJob.forms_skipped, SyncJob.duration_seconds,
    SyncJob.notes, SyncJob.started_at, SyncJob.finished_at, SyncJob.error_message,
    SyncJob.created_at, SyncJob.updated_at,
)


def _build_config(
    *,
    asik_creds: dict,
    base_url: str,
    nik: str,
    merged_data: Any,
    captcha_solver: dict[str, Any],
    headless: bool = True,
    filter_date: str | None = None,
    default_values: dict[str, Any] | None = None,
    session_mode: str = "persistent",
) -> dict[str, Any]:
    return {
        "base_url": base_url,
        "target_path": "/ckg-pelayanan",
        "login_path": "/login",
        "headless": headless,
        "slow_mo": 0,
        "timeout": 60000,
        "use_session": True,
        # "persistent" = own the Chromium profile and log in (one at a time).
        # "shared"     = non-persistent context seeded from the profile's saved
        #                state, never logs in — what the K parallel workers use.
        "session_mode": session_mode,
        "credentials": {
            "username": asik_creds.get("email", ""),
            "password": asik_creds.get("password", ""),
        },
        "nik": nik,
        # ASIK's patient list is date-range-scoped (default = current week). Without
        # this the sync searches the wrong week and never finds a past-date patient.
        "filter_date": filter_date,
        # {normalized_label: {value, kind}} — safe defaults for required questions
        # we have no data for (see app/services/asik_defaults.py).
        "default_values": default_values or {},
        # Every item carries `same_as_asik`; the runner skips a form only when
        # ALL of its items are True (and never `identitas_pasien`).
        "merged_data": _annotate_same_as_asik(merged_data),
        "prune_unchanged": PRUNE_UNCHANGED_FORMS,
        # CAPTCHA solver mirrors the asik scrape pipeline: use the active
        # llm_config when present, fall back to manual when no LLM is set.
        # Saved-session reuse via _asik_session_dir(puskesmas_id) skips CAPTCHA
        # entirely on the happy path.
        "captcha_solver": captcha_solver,
    }


def _count_merged_forms(merged: Any) -> int:
    """Number of ASIK forms present in a decrypted merged_data blob (a section
    that is a non-empty list, or a nested {sub_sections} dict). Legacy-flat and
    current-nested shapes both counted."""
    sections = (merged or {}).get("sections") or {}
    return sum(
        1 for v in sections.values()
        if (isinstance(v, list) and v)
        or (isinstance(v, dict) and v.get("sub_sections"))
    )


def _execute_sync(
    *,
    db,
    redis_client,
    job: SyncJob,
    patient: Patient,
    base_url_full: str,
    creds: dict,
    captcha_solver: dict[str, Any],
    merged: Any,
    forms_total: int,
    headless: bool,
    celery_task_id: str,
    cancel_key_str: str,
    session_mode: str = "persistent",
) -> str:
    """Run the sync scraper subprocess for ONE patient's SyncJob and finalize it.

    Returns the terminal status ('success' | 'failed' | 'cancelled'). On success
    persists asik_default_fills AND stamps patient.asik_synced_at (mark_synced).
    Polls `cancel_key_str` (the per-job key for the manual path, the cron-run key
    for a batch) to abort mid-run. NEVER raises for a normal failure — it records
    the failure on the job — so a batch loop can continue to the next patient.
    """
    log_key = _log_key(str(job.id))
    chan = _stream_chan(str(job.id))
    sampler = None
    try:
        sync_job_crud.mark_running(
            db, job, celery_task_id, datetime.now(UTC), forms_total
        )
        with tempfile.TemporaryDirectory(prefix="sync-asik-") as tmp:
            tmp_path = Path(tmp)
            cfg_path = tmp_path / "config.json"
            out_path = tmp_path / "out.json"
            output_dir = tmp_path / "output"
            screenshot_dir = tmp_path / "screenshots"
            output_dir.mkdir(parents=True, exist_ok=True)
            screenshot_dir.mkdir(parents=True, exist_ok=True)

            session_dir = _asik_session_dir(job.puskesmas_id)

            cfg = _build_config(
                asik_creds=creds,
                base_url=base_url_full,
                nik=patient.nik,
                merged_data=merged,
                captcha_solver=captcha_solver,
                headless=headless,
                filter_date=(
                    patient.filter_date.isoformat() if patient.filter_date else None
                ),
                default_values=build_default_values_map(),
                session_mode=session_mode,
            )
            cfg_path.write_text(json.dumps(cfg))
            os.chmod(cfg_path, 0o600)
            llm_config_id_str = (cfg.get("captcha_solver") or {}).get("llm_config_id")

            scraper_dir = SCRAPERS_ROOT / "asik_sync"
            env = _build_subprocess_env(cfg_path, output_dir, session_dir, screenshot_dir)

            cmd = [sys.executable, "-u", "sync.py", "--output", str(out_path)]

            t0 = time.monotonic()
            # Headed Chromium needs an X display. Linux worker container has
            # none — wrap with xvfb-run for a virtual framebuffer. macOS /
            # Windows dev hosts have a native display, so skip the wrap when
            # xvfb-run is missing from PATH.
            exec_cmd = cmd
            if not headless and shutil.which("xvfb-run"):
                exec_cmd = ["xvfb-run", "-a", "--", *cmd]
            proc = subprocess.Popen(
                exec_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                cwd=str(scraper_dir),
                env=env,
            )

            usage_buffer: list[dict] = []
            drain_thread = threading.Thread(
                target=_drain_to_redis,
                args=(proc.stdout, redis_client, log_key, chan, usage_buffer),
                daemon=True,
            )
            drain_thread.start()

            sampler = ResourceSampler("pid", pid=proc.pid).start()
            resource_metrics: dict | None = None
            cancelled = False
            timed_out = False
            timeout_s = max(1, int(settings.SYNC_SUBPROCESS_TIMEOUT_SECONDS))
            try:
                # Two different clocks on purpose. This loop is what notices the
                # subprocess has EXITED, and a 2 s tick added ~1 s of dead time to
                # every patient (~19 min across a 1,142-patient backfill) purely
                # waiting to observe an already-finished process — so poll the
                # process 8x faster. The cancel flag does NOT need that
                # granularity, so keep reading Redis on the original ~2 s cadence
                # rather than multiplying the round-trips by 8.
                _last_cancel_check = 0.0
                while proc.poll() is None:
                    time.sleep(0.25)
                    now = time.monotonic()
                    # Hang backstop. Without this a Playwright subprocess that
                    # never returns (e.g. a batch tab that never opens because
                    # the container is out of PID slots) holds this Celery slot
                    # forever and the job sits RUNNING with no error.
                    if now - t0 > timeout_s:
                        timed_out = True
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        break
                    if now - _last_cancel_check < 2.0:
                        continue
                    _last_cancel_check = now
                    try:
                        flag = redis_client.get(cancel_key_str)
                    except Exception:
                        flag = None
                    if flag == "1":
                        cancelled = True
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        break
                drain_thread.join(timeout=STDOUT_DRAIN_JOIN_TIMEOUT_SECONDS)
            finally:
                resource_metrics = sampler.stop()
            usage_snapshot = list(usage_buffer)
            duration = time.monotonic() - t0

            if llm_config_id_str and usage_snapshot:
                try:
                    llm_cfg_uuid = uuid.UUID(llm_config_id_str)
                    pricing_row = db.scalar(
                        select(LlmConfig)
                        .options(load_only(
                            LlmConfig.id,
                            LlmConfig.input_price_per_1m,
                            LlmConfig.output_price_per_1m,
                        ))
                        .where(LlmConfig.id == llm_cfg_uuid)
                    )
                    in_rate = pricing_row.input_price_per_1m if pricing_row else None
                    out_rate = pricing_row.output_price_per_1m if pricing_row else None
                    for u in usage_snapshot:
                        model = u.get("model")
                        if not model:
                            log.warning("sync llm_log missing model; skipping: %r", u)
                            continue
                        in_tok = u.get("input_tokens")
                        out_tok = u.get("output_tokens")
                        prompt_cost = _calc_cost(in_tok, in_rate)
                        completion_cost = _calc_cost(out_tok, out_rate)
                        total_cost = (
                            prompt_cost + completion_cost
                            if prompt_cost is not None and completion_cost is not None
                            else None
                        )
                        try:
                            with db.begin_nested():
                                llm_log_crud.record(
                                    db,
                                    llm_config_id=llm_cfg_uuid,
                                    source=u.get("source", "asik_sync_captcha"),
                                    model=model,
                                    success=bool(u.get("success")),
                                    patient_id=job.patient_id,
                                    puskesmas_id=job.puskesmas_id,
                                    input_tokens=in_tok,
                                    output_tokens=out_tok,
                                    total_tokens=u.get("total_tokens"),
                                    reasoning_tokens=u.get("reasoning_tokens"),
                                    prompt_cost=prompt_cost,
                                    completion_cost=completion_cost,
                                    total_cost=total_cost,
                                    latency_ms=u.get("latency_ms"),
                                    error=u.get("error"),
                                )
                        except Exception as exc:
                            log.warning("failed to write sync llm_log row: %s", exc)
                    db.commit()
                except Exception as exc:
                    log.warning("failed to write sync llm_logs batch: %s", exc)
                    db.rollback()

            if cancelled:
                try:
                    if resource_metrics and resource_metrics.get("samples", 0) > 0:
                        sync_job_crud.set_resource_metrics(db, job, resource_metrics)
                except Exception as exc:
                    log.warning("failed to persist resource metrics on cancel: %s", exc)
                # Mark the job CANCELLED if nothing else already did. The manual
                # path's cancel route marks it before setting the Redis flag, but a
                # cron batch has no such route — without this the in-flight patient's
                # SyncJob would be stuck RUNNING forever.
                try:
                    db.refresh(job, ["status"])
                    if job.status != SyncStatus.CANCELLED:
                        sync_job_crud.mark_cancelled(db, job)
                except Exception as exc:
                    log.warning("failed to mark sync job cancelled: %s", exc)
                try:
                    redis_client.publish(chan, "__cancelled__")
                except Exception:
                    pass
                return "cancelled"

            if proc.returncode != 0:
                # A shared-session worker that found the token stale did NOT
                # fail because of this patient — the batch re-logs-in and
                # requeues it. The runner writes its output file even when it
                # raises, so the flag survives the non-zero exit.
                #
                # A timeout kill is NOT a stale session — never requeue it, or a
                # reproducibly-hanging patient would be retried behind a fresh
                # login and burn the timeout all over again.
                if session_mode == "shared" and not timed_out:
                    try:
                        if json.loads(out_path.read_text()).get("session_dead"):
                            # CANCELLED, not FAILED: this attempt was abandoned,
                            # not refused by ASIK. The batch pushes the patient
                            # back to the front of the queue and runs it again
                            # behind a fresh login, which creates its own
                            # SyncJob — so a FAILED row here double-counts one
                            # patient and inflates the failure rate of every
                            # long batch (measured: 13 of 90 rows on the 2025-02
                            # Pekayon run, every one of them with a real
                            # outcome recorded separately). Keep the row for the
                            # audit trail; keep it out of the failure count.
                            try:
                                if resource_metrics and resource_metrics.get("samples", 0) > 0:
                                    sync_job_crud.set_resource_metrics(
                                        db, job, resource_metrics
                                    )
                            except Exception as exc:
                                log.warning(
                                    "failed to persist resource metrics on requeue: %s", exc
                                )
                            sync_job_crud.mark_cancelled(
                                db, job,
                                error_message="shared ASIK session expired — requeued",
                            )
                            try:
                                redis_client.publish(chan, "__cancelled__")
                            except Exception:
                                pass
                            return "session_dead"
                    except Exception:
                        pass
                try:
                    tail = "\n".join(redis_client.lrange(log_key, -50, -1) or [])
                except Exception:
                    tail = ""
                reason = (
                    f"sync subprocess exceeded {timeout_s}s wall clock — killed"
                    if timed_out
                    else f"exit={proc.returncode}"
                )
                sync_job_crud.mark_failed(
                    db, job,
                    f"{reason}\n{tail}"[:4000],
                    datetime.now(UTC),
                    metrics=resource_metrics,
                )
                try:
                    redis_client.publish(chan, "__failed__")
                except Exception:
                    pass
                return "failed"

            try:
                output = json.loads(out_path.read_text())
            except FileNotFoundError:
                sync_job_crud.mark_failed(
                    db, job, "sync produced no output file",
                    datetime.now(UTC), metrics=resource_metrics,
                )
                try:
                    redis_client.publish(chan, "__failed__")
                except Exception:
                    pass
                return "failed"

            forms = output.get("forms") or []
            # These three sets decide `mark_synced` (below), so every status the
            # runner can emit must land in exactly one of them. A status in NONE
            # of them is counted nowhere, keeps `failed == 0`, and therefore
            # stamps asik_synced_at on a patient whose form was never pushed —
            # it would never be retried. `toggle_failed` / `toggle_no_button`
            # were in that gap; they are retry-worthy, so they count as failed.
            #
            # "would_submit" only appears in dry_run (fills + defaults verified, no Kirim).
            succeeded = sum(1 for f in forms if f.get("status") in ("submitted", "would_submit"))
            failed = sum(1 for f in forms if f.get("status") in (
                "validation_error", "submit_unknown", "no_kirim_button",
                "form_load_timeout",
                # We reached the form but deliberately did not submit, because we
                # could not prove ASIK's existing answers had loaded — filling
                # then would overwrite real values with fabricated defaults.
                "answers_unconfirmed",
                # The row disappeared from the detail page between enumeration
                # and processing, so its data was never pushed.
                "row_vanished",
                "toggle_failed", "toggle_no_button",
            ))
            skipped = sum(1 for f in forms if f.get("status") in (
                "skipped_no_section", "skipped_no_real_data", "no_match",
                "no_button", "incomplete_data",
                # ASIK already holds every value this form would push.
                "skipped_unchanged",
            ))

            notes_lines: list[str] = []
            if not output.get("patient_found"):
                notes_lines.append(f"Patient NIK {patient.nik} not found on ASIK")
            else:
                notes_lines.append(f"Patient found in tab: {output.get('patient_tab')}")
                # Shadow measurement for PRUNE_UNCHANGED_FORMS: how many forms
                # ASIK already fully agrees with. This is the number that decides
                # whether turning pruning on is worth it, and it is only knowable
                # from live runs — so record it on every job while it is off.
                prunable = sum(1 for f in forms if f.get("would_prune"))
                matched = sum(1 for f in forms if f.get("matched_slug"))
                if matched:
                    notes_lines.append(
                        f"Elimination (shadow): {prunable}/{matched} matched forms "
                        f"already identical to ASIK"
                    )
                for f in forms:
                    notes_lines.append(
                        f"  {f.get('kind')}: {f.get('layanan')} → {f.get('status')} "
                        f"(filled={f.get('filled')}, skipped={f.get('skipped')})"
                    )
            notes = "\n".join(notes_lines)[:4000]

            # Intentional skips (NIK not present in ASIK, or the only ASIK
            # screening for this NIK is a different YEAR than the ePus visit).
            # These are NOT our failure — nothing to fill, no point retrying the
            # form load — so mark them terminally with a [SKIP:...] reason that
            # keeps them out of the genuine-failure signal. Must be checked BEFORE
            # `patient_found` (a not_found skip also has patient_found=False; a
            # year_mismatch skip has patient_found=True).
            if output.get("skipped"):
                reason = output.get("skip_reason") or "skipped"
                detail = output.get("error") or reason
                sync_job_crud.mark_failed(
                    db, job, f"[SKIP:{reason}] {detail}"[:2000],
                    datetime.now(UTC),
                    forms_succeeded=0, forms_failed=0, forms_skipped=0,
                    metrics=resource_metrics,
                )
                try:
                    redis_client.publish(chan, "__failed__")
                except Exception:
                    pass
                return "failed"

            if not output.get("patient_found"):
                sync_job_crud.mark_failed(
                    db, job,
                    output.get("error") or f"NIK {patient.nik} not found on ASIK",
                    datetime.now(UTC),
                    forms_succeeded=0, forms_failed=0, forms_skipped=0,
                    metrics=resource_metrics,
                )
                try:
                    redis_client.publish(chan, "__failed__")
                except Exception:
                    pass
                return "failed"

            # Record the default values we pushed for required-but-missing fields,
            # flattened across all forms, onto the patient (overwrites each sync). So
            # reports can separate real data from auto-fills.
            #
            # Stamp asik_synced_at (mark_synced) ONLY when no form FAILED — so the
            # cron NORMAL sync retries a patient whose forms hit a transient error
            # (validation_error / load timeout) rather than silently never pushing
            # them. `incomplete_data` / `skipped_no_real_data` are counted as skipped
            # (not failed): retrying them is futile (same missing data), so they do
            # not block the stamp. force_resync re-syncs regardless.
            mark_synced = failed == 0
            default_fills: list[dict] = []
            for f in forms:
                for d in (f.get("defaults") or []):
                    default_fills.append({
                        "layanan": f.get("layanan"),
                        "question": d.get("question"),
                        "value": d.get("value"),
                        "kind": d.get("kind"),
                    })
            try:
                patient_crud.set_asik_default_fills(
                    db, job.patient_id, default_fills or None, mark_synced=mark_synced
                )
            except Exception as exc:
                log.warning("failed to persist asik_default_fills: %s", exc)

            sync_job_crud.mark_success(
                db, job, duration, datetime.now(UTC),
                forms_succeeded=succeeded,
                forms_failed=failed,
                forms_skipped=skipped,
                notes=notes,
                metrics=resource_metrics,
            )
            try:
                redis_client.publish(chan, "__done__")
            except Exception:
                pass
            return "success"
    except Exception as e:
        db.rollback()
        _metrics = sampler.stop() if sampler is not None else None
        try:
            db.refresh(job, ["status"])
            if job.status != SyncStatus.CANCELLED:
                sync_job_crud.mark_failed(
                    db, job, str(e)[:2000], datetime.now(UTC), metrics=_metrics,
                )
        except Exception:
            pass
        try:
            redis_client.publish(chan, "__failed__")
        except Exception:
            pass
        return "failed"


@celery_app.task(bind=True, name="sync.run")
def run_sync(self, job_id: str, headless: bool = True) -> None:
    db = SessionLocal()
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    chan = _stream_chan(job_id)
    try:
        job_uuid = uuid.UUID(job_id)
        job = db.scalar(
            select(SyncJob).options(load_only(*_JOB_TASK_COLS)).where(SyncJob.id == job_uuid)
        )
        if job is None:
            return
        if job.status == SyncStatus.CANCELLED:
            try:
                redis_client.publish(chan, "__cancelled__")
            except Exception:
                pass
            return

        # Load patient (need merged_data OR scraped_epus_data for epus_only fallback)
        patient = db.scalar(
            select(Patient)
            .options(load_only(
                Patient.id, Patient.puskesmas_id, Patient.nik, Patient.nama,
                Patient.match_status, Patient.merged_data,
                Patient.scraped_epus_data, Patient.filter_date,
            ))
            .where(Patient.id == job.patient_id)
        )
        if patient is None:
            sync_job_crud.mark_failed(db, job, "patient not found", datetime.now(UTC))
            return
        # EPUS-only fallback is disabled by scope (ALLOW_EPUS_ONLY_SYNC=False): sync
        # requires merged_data (matched + AI-merged). The fallback code below is kept
        # so it can be re-enabled by flipping the flag.
        epus_only_fallback = (
            ALLOW_EPUS_ONLY_SYNC
            and patient.merged_data is None
            and patient.match_status == MatchStatus.EPUS_ONLY
            and patient.scraped_epus_data is not None
        )
        if patient.merged_data is None and not epus_only_fallback:
            sync_job_crud.mark_failed(
                db, job,
                "patient has no merged_data (sync requires matched + AI-merged data)",
                datetime.now(UTC),
            )
            return

        puskesmas = db.scalar(
            select(Puskesmas)
            .options(load_only(Puskesmas.id, Puskesmas.asik_url, Puskesmas.asik_cred))
            .where(Puskesmas.id == job.puskesmas_id)
        )
        if puskesmas is None:
            sync_job_crud.mark_failed(db, job, "puskesmas not found", datetime.now(UTC))
            return

        creds = puskesmas_crud.get_cred_decrypted(puskesmas, "asik")
        if creds is None:
            sync_job_crud.mark_failed(db, job, "asik credentials not set", datetime.now(UTC))
            return

        base_url_full = f"https://{puskesmas.asik_url}" if puskesmas.asik_url else None
        if not base_url_full:
            sync_job_crud.mark_failed(db, job, "asik_url not set", datetime.now(UTC))
            return

        if epus_only_fallback:
            try:
                epus = patient_crud.decrypt_field(patient, ScrapeKind.EPUS)
            except Exception as exc:
                sync_job_crud.mark_failed(
                    db, job, f"scraped_epus_data could not be decrypted: {exc}",
                    datetime.now(UTC),
                )
                return
            if not epus:
                sync_job_crud.mark_failed(
                    db, job, "scraped_epus_data is empty", datetime.now(UTC)
                )
                return
            # Pass the asik-preview output through as-is; the runner's
            # `_build_section_index` accepts both shapes natively.
            merged = epus_to_asik(epus)
            forms_total = sum(
                1 for v in (merged or {}).values()
                if isinstance(v, dict) and any(x is not None and x != "" for x in v.values())
            )
        else:
            merged = patient_crud.decrypt_merged(patient)
            if not merged:
                sync_job_crud.mark_failed(
                    db, job, "merged_data could not be decrypted", datetime.now(UTC)
                )
                return
            forms_total = _count_merged_forms(merged)

        try:
            captcha_solver = _build_captcha_solver(db)
        except LlmConfigUnreadable as exc:
            sync_job_crud.mark_failed(
                db, job, f"active llm_config unreadable (id={exc})", datetime.now(UTC)
            )
            return

        _execute_sync(
            db=db,
            redis_client=redis_client,
            job=job,
            patient=patient,
            base_url_full=base_url_full,
            creds=creds,
            captcha_solver=captcha_solver,
            merged=merged,
            forms_total=forms_total,
            headless=headless,
            celery_task_id=self.request.id or "",
            cancel_key_str=_cancel_key(job_id),
        )
    except Exception as e:
        # Only the entity-loading phase reaches here; _execute_sync never raises.
        db.rollback()
        try:
            j = db.scalar(select(SyncJob).where(SyncJob.id == uuid.UUID(job_id)))
            if j is not None:
                db.refresh(j, ["status"])
                if j.status != SyncStatus.CANCELLED:
                    sync_job_crud.mark_failed(db, j, str(e)[:2000], datetime.now(UTC))
        except Exception:
            pass
        try:
            redis_client.publish(chan, "__failed__")
        except Exception:
            pass
        raise
    finally:
        db.close()


@celery_app.task(name="sync.run_cron_batch")
def run_cron_batch(cron_run_id: str) -> None:
    """Cron SYNC step: push merged data into ASIK for every eligible patient of a
    (puskesmas, target_date), SEQUENTIALLY in one ASIK session (the session is
    reused across patients — one login, one account, no collision). Dispatched by
    cron.advance only when the parent config/backfill has sync_mode != OFF.

    Eligibility: patients with merged_data for that date. NORMAL syncs only those
    not yet synced (asik_synced_at IS NULL); FORCE_RESYNC syncs all. Per-patient
    failures are recorded on their own SyncJob and do NOT stop the batch. A FATAL
    failure (missing puskesmas / creds / llm_config) RAISES so cron's link_error
    marks the step failed.

    Re-submission semantics (IMPORTANT): a sync clicks Kirim on every fillable
    form for a found patient. ASIK keys a screening by (patient, date), so a
    re-submit UPDATES that record in place rather than creating a duplicate
    (verified live). FORCE_RESYNC is therefore a deliberate "push again" and is
    the only mode that re-submits already-synced patients. Crash window: the batch
    is one long Celery task; if the worker dies mid-batch and the message is
    redelivered (acks_late), the in-flight patient — whose asik_synced_at was not
    yet committed — is re-synced (bounded to 1 patient in NORMAL; the whole date in
    FORCE_RESYNC). The run shows current_step=sync while active, so the deploy
    preflight's in-flight-cron detection surfaces it before a restart. No
    soft_time_limit is set (matches scrape/merge), so a very large date can run
    long; keep sync date-ranges reasonable.
    """
    from app.tasks.cron import _is_cancelled, _resolve_sync_mode, cancel_key

    db = SessionLocal()
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        run = db.scalar(
            select(CronRun)
            .options(load_only(
                CronRun.id, CronRun.puskesmas_id, CronRun.target_date,
                CronRun.cron_backfill_id, CronRun.cron_config_id,
                CronRun.triggered_by_id, CronRun.sync_total,
            ))
            .where(CronRun.id == uuid.UUID(cron_run_id))
        )
        if run is None:
            return
        sync_mode = _resolve_sync_mode(db, run)
        if sync_mode is CronSyncMode.OFF:
            return  # defensive: only dispatched when != OFF

        puskesmas = db.scalar(
            select(Puskesmas)
            .options(load_only(Puskesmas.id, Puskesmas.asik_url, Puskesmas.asik_cred))
            .where(Puskesmas.id == run.puskesmas_id)
        )
        if puskesmas is None:
            raise RuntimeError("puskesmas not found for sync batch")
        creds = puskesmas_crud.get_cred_decrypted(puskesmas, "asik")
        if creds is None:
            raise RuntimeError("asik credentials not set for sync batch")
        base_url_full = f"https://{puskesmas.asik_url}" if puskesmas.asik_url else None
        if not base_url_full:
            raise RuntimeError("asik_url not set for sync batch")
        captcha_solver = _build_captcha_solver(db)  # LlmConfigUnreadable → fatal

        # Cache the run's scalar fields into locals BEFORE the loop. sync_job_crud.create
        # commits (expiring `run`), so touching run.* inside the loop would re-SELECT it
        # each iteration and could raise StaleDataError if the run was soft-deleted mid-batch.
        pk_id = run.puskesmas_id
        target_date = run.target_date
        triggered_by = run.triggered_by_id or run.puskesmas_id

        # Eligible patient ids for this puskesmas+date that have merged_data AND ASIK
        # data for this date (scraped_asik_data set = the patient is actually on ASIK
        # for target_date). The latter guard skips the EPUS-dated row of a cross-date
        # twin — its ASIK screening is on the OTHER date, so a sync scoped to this date
        # would never find it and would fail on every cron fire. The blob is decrypted
        # per patient below (never loaded all at once).
        conds = [
            Patient.puskesmas_id == pk_id,
            Patient.filter_date == target_date,
            Patient.merged_data.isnot(None),
            Patient.scraped_asik_data.isnot(None),
        ]
        if sync_mode is CronSyncMode.NORMAL:
            conds.append(Patient.asik_synced_at.is_(None))
        patient_ids = list(db.scalars(select(Patient.id).where(*conds)).all())

        # Stamp the denominator before any job exists. SyncJobs are created
        # lazily below, so a live "14/16 patients" needs this recorded up front —
        # counting jobs alone would read 14/14 and look finished.
        run.sync_total = len(patient_ids)
        db.commit()

        cancel_key_str = cancel_key(cron_run_id)
        run_uuid = uuid.UUID(cron_run_id)

        def _run_one(pid, session_mode: str, session: Any) -> str:
            """Sync ONE patient on `session`. Returns a terminal status or ''.

            `session` is per-caller: a worker thread MUST NOT share the batch's
            Session (SQLAlchemy Sessions are not thread-safe).
            """
            patient = session.scalar(
                select(Patient)
                .options(load_only(
                    Patient.id, Patient.puskesmas_id, Patient.nik, Patient.nama,
                    Patient.merged_data, Patient.filter_date,
                ))
                .where(Patient.id == pid)
            )
            if patient is None or patient.merged_data is None:
                return ""
            merged = patient_crud.decrypt_merged(patient)
            if not merged:
                return ""  # undecryptable blob → skip (no job); a later run retries
            try:
                job = sync_job_crud.create(
                    session,
                    puskesmas_id=pk_id,
                    patient_id=pid,
                    triggered_by_id=triggered_by,
                    triggered_by_type=TriggererType.CRON,
                    cron_run_id=run_uuid,
                )
            except IntegrityError:
                # uq_sync_jobs_active_per_patient: this patient already has an active
                # SyncJob (a concurrent manual sync, or a stuck RUNNING job). Skip it —
                # one conflicting patient must not fail the whole date's sync step.
                session.rollback()
                return ""
            return _execute_sync(
                db=session,
                redis_client=redis_client,
                job=job,
                patient=patient,
                base_url_full=base_url_full,
                creds=creds,
                captcha_solver=captcha_solver,
                merged=merged,
                forms_total=_count_merged_forms(merged),
                headless=True,  # cron always headless
                celery_task_id=cron_run_id,
                cancel_key_str=cancel_key_str,
                session_mode=session_mode,
            )

        def _run_one_threaded(pid) -> tuple[Any, str]:
            """Thread entry point: own DB session, own Redis client, own browser."""
            session = SessionLocal()
            try:
                return pid, _run_one(pid, "shared", session)
            except Exception as exc:  # a thread must never take down the batch
                log.warning("sync worker for patient %s crashed: %s", pid, exc)
                return pid, "failed"
            finally:
                session.close()

        # ------------------------------------------------------------------
        # One login, K browsers (Phase C).
        #
        # The work is ~94 s of idle waiting per patient, so it parallelises
        # almost linearly — but ASIK invalidates a session on a second LOGIN,
        # not on concurrent requests. So exactly one patient per round runs in
        # "persistent" mode: it owns the Chromium profile, logs in if needed,
        # and saves the session state. The rest of the round runs in "shared"
        # mode off that saved state and is forbidden from logging in.
        #
        # The saved snapshot goes stale (measured: a ~30-minute-old one probed
        # 401 while the live SPA keeps itself alive via refresh-token). Rather
        # than hardcode a lifetime, a worker that finds it stale returns
        # "session_dead" and its patient goes back to the front of the queue —
        # the next round's bootstrap re-logs-in and it runs again.
        # ------------------------------------------------------------------
        concurrency = max(1, int(settings.ASIK_SYNC_CONCURRENCY))
        pending = deque(patient_ids)
        requeued: set[Any] = set()
        while pending:
            if _is_cancelled(redis_client, cron_run_id):
                break
            # 1. Bootstrap: sequential, owns the profile, refreshes the session.
            bootstrap_id = pending.popleft()
            if _run_one(bootstrap_id, "persistent", db) == "session_dead":
                # Only reachable if someone hand-set persistent→shared; treat as
                # unrecoverable rather than spinning on the same patient.
                log.error("bootstrap patient reported a dead session; aborting batch")
                break
            if concurrency == 1 or not pending:
                continue
            # 2. The rest of this round, in parallel off that fresh session.
            round_size = min(len(pending), concurrency * _SYNC_ROUND_MULTIPLIER)
            chunk = [pending.popleft() for _ in range(round_size)]
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                for pid, status in pool.map(_run_one_threaded, chunk):
                    if status != "session_dead":
                        continue
                    if pid in requeued:
                        # Already retried once behind a fresh login and still
                        # dead → this is not a session problem. Drop it so the
                        # batch cannot loop on one patient forever.
                        log.warning("patient %s reported session_dead twice; giving up", pid)
                        continue
                    requeued.add(pid)
                    pending.appendleft(pid)
            if _is_cancelled(redis_client, cron_run_id):
                break
    finally:
        db.close()
