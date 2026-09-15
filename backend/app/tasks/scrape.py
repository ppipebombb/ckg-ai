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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.celery_app import celery_app
from app.config import settings
from app.core.resource_sampler import ResourceSampler
from app.core.security import decrypt_json
from app.crud import llm_config as llm_config_crud
from app.crud import llm_log as llm_log_crud
from app.crud import patient as patient_crud
from app.crud import puskesmas as puskesmas_crud
from app.crud import school_patient as school_patient_crud
from app.crud import scrape_job as scrape_job_crud
from app.database import SessionLocal
from app.models.llm_config import LlmConfig
from app.models.patient import Patient
from app.models.puskesmas import Puskesmas
from app.models.scrape_job import ScrapeJob, ScrapeKind, ScrapeStatus
from app.models.school_patient import SchoolPatient

log = logging.getLogger(__name__)

_PER_MILLION = Decimal("1000000")


def _cancel_key(job_id: str) -> str:
    return f"scrape:job:{job_id}:cancel"


def _calc_cost(tokens: int | None, rate: Decimal | None) -> Decimal | None:
    if tokens is None or rate is None:
        return None
    return Decimal(tokens) * rate / _PER_MILLION


_JOB_TASK_COLS = (
    ScrapeJob.id, ScrapeJob.puskesmas_id, ScrapeJob.patient_id,
    ScrapeJob.kind, ScrapeJob.date_filter, ScrapeJob.date_filters,
    ScrapeJob.target_nik, ScrapeJob.target_niks, ScrapeJob.asik_list_only,
    ScrapeJob.asik_mandiri_only,
    ScrapeJob.status, ScrapeJob.triggered_by_id, ScrapeJob.triggered_by_type,
    ScrapeJob.celery_task_id, ScrapeJob.scraped_count, ScrapeJob.inserted_count,
    ScrapeJob.updated_count, ScrapeJob.duration_seconds, ScrapeJob.notes,
    ScrapeJob.started_at, ScrapeJob.finished_at, ScrapeJob.error_message,
    ScrapeJob.parent_gdp_job_id, ScrapeJob.created_at, ScrapeJob.updated_at,
)

def _resolve_scrapers_root() -> Path:
    if settings.SCRAPERS_ROOT:
        return Path(settings.SCRAPERS_ROOT)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "scrapers"
        if (candidate / "asik").is_dir() and (candidate / "epus").is_dir():
            return candidate
    return here.parents[2] / "scrapers"


SCRAPERS_ROOT = _resolve_scrapers_root()


def _resolve_sessions_root() -> Path:
    if settings.SCRAPER_SESSIONS_ROOT:
        return Path(settings.SCRAPER_SESSIONS_ROOT)
    # Default: <repo_root>/.scraper-sessions (sibling of scrapers/)
    return SCRAPERS_ROOT.parent / ".scraper-sessions"


def _asik_session_dir(puskesmas_id: "uuid.UUID") -> Path:
    d = _resolve_sessions_root() / "asik" / str(puskesmas_id)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def _asik_sekolah_session_dir(puskesmas_id: "uuid.UUID") -> Path:
    # Separate persistent profile from the CKG-Umum ASIK session so a school
    # scrape and an umum scrape can run concurrently without two Chromium
    # processes fighting over the same user-data-dir (both log into the same
    # portal, so each just solves CAPTCHA once for its own session).
    d = _resolve_sessions_root() / "asik_sekolah" / str(puskesmas_id)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


LOG_RING_MAX = 500
LOG_TTL_SECONDS = 86400
STDOUT_DRAIN_JOIN_TIMEOUT_SECONDS = 2

# Env vars passed through to scraper subprocess. Excludes secrets the worker
# already consumed (CRED_ENCRYPTION_KEY, DATABASE_URL, REDIS_URL, JWT_SECRET).
_SUBPROCESS_ENV_PASSTHROUGH = (
    "PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR",
    "DISPLAY", "PLAYWRIGHT_BROWSERS_PATH",
)


def _log_key(job_id: str) -> str:
    return f"scrape:job:{job_id}:log"


def _stream_chan(job_id: str) -> str:
    return f"scrape:job:{job_id}:stream"


class LlmConfigUnreadable(RuntimeError):
    """Active llm_config exists but its api_key blob cannot be decrypted."""


def _build_captcha_solver(db: Session) -> dict[str, Any]:
    active = llm_config_crud.get_active_for_captcha(db)
    if not active:
        return {"type": "manual", "api_key": ""}
    try:
        api_key = decrypt_json(active.api_key_enc)["api_key"]
    except Exception as exc:
        raise LlmConfigUnreadable(str(active.id)) from exc
    if not api_key:
        raise LlmConfigUnreadable(str(active.id))
    return {
        "type": "llm",
        "provider": active.provider,
        "model": active.model,
        "base_url": active.base_url,
        "api_key": api_key,
        "route_order": active.route_order or "",
        "llm_config_id": str(active.id),
    }


def _build_config(
    kind: ScrapeKind,
    creds: dict[str, str],
    date_iso: str | None,
    base_url: str | None,
    db: Session,
    nik: str | None = None,
    headless: bool = True,
    mandiri_only: bool = False,
) -> dict[str, Any]:
    if not base_url:
        # Route layer enforces this, but guard here so a misconfigured
        # puskesmas can't slip through.
        raise ValueError(f"{kind.value} base_url required")
    if kind == ScrapeKind.ASIK:
        cfg: dict[str, Any] = {
            "base_url": base_url,
            "target_path": "/ckg-pelayanan",
            "login_path": "/login",
            "headless": headless,
            "slow_mo": 0,
            "timeout": 60000,
            "max_pages": 500,
            "credentials": {
                "username": creds.get("email", ""),
                "password": creds.get("password", ""),
            },
            # Mandiri (Pemeriksaan Mandiri) now captured alongside Nakes. The
            # mandiri-only backfill flips this back per-job via mandiri_only.
            "pelayanan_nakes_only": False,
            "include_blank_forms": True,
            "scrape_tatalaksana": True,
            "captcha_solver": _build_captcha_solver(db),
        }
        if date_iso:
            cfg["date"] = date_iso
        if nik:
            cfg["nik"] = nik
        if mandiri_only:
            # Backfill: open ONLY the Pemeriksaan Mandiri forms (skip Nakes +
            # Tatalaksana, already scraped). patient_scraper honors this.
            cfg["mandiri_only"] = True
        return cfg
    if kind == ScrapeKind.ASIK_SEKOLAH:
        # Same ASIK portal/credentials, school module. Date-less: the scraper
        # dynamically walks every school × class. Nakes-only + tatalaksana,
        # blank forms included so every question schema is captured.
        return {
            "base_url": base_url,
            "target_path": "/ckg-pelayanan-sekolah",
            "login_path": "/login",
            "headless": headless,
            "slow_mo": 0,
            "timeout": 60000,
            "credentials": {
                "username": creds.get("email", ""),
                "password": creds.get("password", ""),
            },
            "pelayanan_nakes_only": True,
            "include_blank_forms": True,
            "scrape_tatalaksana": True,
            "captcha_solver": _build_captcha_solver(db),
        }
    # Multi-date EPUS (GDP orchestrator) leaves date_iso None — --dates CLI
    # arg supplies the date list, so the cfg's filters.date stays absent and
    # the scraper falls back to the CLI value per date.
    filters: dict[str, str] = {
        "status_periksa": "3",
        # "ruangan_id": "0001",  # filter removed — "0" = all ruangan (revert to "0001" to restore UMUM-only)
        "ruangan_id": "0",
        "limit": "100",
    }
    if date_iso:
        filters["date"] = _iso_to_ddmmyyyy(date_iso)
    if nik:
        filters["search_key"] = nik
    return {
        "base_url": base_url,
        "login_path": "/login",
        "target_path": "/pelayanan",
        "headless": headless,
        "slow_mo": 0,
        "timeout": 60000,
        "credentials": {
            "email": creds.get("email", ""),
            "password": creds.get("password", ""),
        },
        "filters": filters,
    }


# ASIK CLI takes ISO date (YYYY-MM-DD); EPUS CLI takes DDMMYYYY. Divergence
# preserved to match the upstream scrapers — do not unify without changing
# scrapers/{asik,epus}/scraper.py too.
def _iso_to_ddmmyyyy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}-{m}-{y}"


def _extract_patients(
    kind: ScrapeKind, output: dict[str, Any]
) -> tuple[list[tuple[str, str, dict, str | None]], list[dict], int]:
    """Returns (rows, skipped, scraped_count) where each row is
    ``(nik, nama, raw_entry, per_record_date_iso_or_none)``.

    The 4th tuple element is set when the scraper packs results from multiple
    dates into one output (multi-date ASIK). The orchestrator-supplied
    job.date_filter is a fallback when this is None (single-date scrape).
    """
    rows: list[tuple[str, str, dict, str | None]] = []
    skipped: list[dict] = []
    if kind == ScrapeKind.ASIK:
        raw_entries: list[tuple[dict, str | None]] = []
        # Multi-date output: {"by_date": {"2026-01-01": {belum_…, sedang_…, selesai_…}}}
        by_date = output.get("by_date") or {}
        if by_date:
            for date_iso, day_buckets in by_date.items():
                for bucket in ("belum_pemeriksaan", "sedang_pemeriksaan", "selesai_pemeriksaan"):
                    for e in (day_buckets.get(bucket) or []):
                        raw_entries.append((e, date_iso))
        else:
            for bucket in ("belum_pemeriksaan", "sedang_pemeriksaan", "selesai_pemeriksaan"):
                for e in (output.get(bucket) or []):
                    raw_entries.append((e, None))
        scraped_count = len(raw_entries)
        for entry, date_iso in raw_entries:
            indiv = (entry.get("detail_data") or {}).get("data_individu") or {}
            nik = (indiv.get("NIK") or "").strip()
            nama = (indiv.get("Nama") or "").strip()
            if not nik:
                skipped.append({
                    "source_id": str(indiv.get("ID") or ""),
                    "reason": "missing NIK",
                })
                continue
            rows.append((nik, nama, entry, date_iso))
    else:
        # EPUS multi-date: {"by_date": {iso: {"patients": [...]}}}
        # EPUS single-date: {"patients": [...]}
        raw_entries_e: list[tuple[dict, str | None]] = []
        by_date = output.get("by_date") or {}
        if by_date:
            for date_iso, day in by_date.items():
                for e in (day.get("patients") or []):
                    raw_entries_e.append((e, date_iso))
        else:
            for e in (output.get("patients") or []):
                raw_entries_e.append((e, None))
        scraped_count = len(raw_entries_e)
        for entry, date_iso in raw_entries_e:
            data = entry.get("data_pasien") or {}
            nik = (data.get("NIK") or "").strip()
            # Label varies by ePuskesmas tenant: kotabekasi uses "Nama Pasien",
            # jaksel uses "Nama". Scraper preserves raw HTML label verbatim.
            nama = (data.get("Nama Pasien") or data.get("Nama") or "").strip()
            if not nik:
                skipped.append({
                    "source_id": str(entry.get("pelayanan_id") or ""),
                    "reason": "missing NIK",
                })
                continue
            rows.append((nik, nama, entry, date_iso))
    return rows, skipped, scraped_count


_SCHOOL_TABS = ("belum_pemeriksaan", "sedang_pemeriksaan", "selesai_pemeriksaan")


def _extract_school_students(
    output: dict[str, Any]
) -> tuple[list[dict], list[dict], int]:
    """Flatten the CKG-Sekolah scraper output into per-student dicts.

    Output shape: ``{"schools": [{"school": {...}, "classes": [{"class_name",
    "tabs": {belum_…/sedang_…/selesai_…: [student, ...]}}]}]}``. Each student is
    the flat dict the scraper already normalized (nik, nama, screening_status,
    school/class/klaster, born_date, pelayanan_nakes, tatalaksana, _raw_*).
    Returns (students, skipped, scraped_count).
    """
    students: list[dict] = []
    skipped: list[dict] = []
    seen = 0
    for school in output.get("schools") or []:
        for cls in school.get("classes") or []:
            tabs = cls.get("tabs") or {}
            for bucket in _SCHOOL_TABS:
                for s in (tabs.get(bucket) or []):
                    seen += 1
                    nik = (s.get("nik") or "").strip()
                    if not nik:
                        skipped.append({
                            "source_id": str(s.get("reg_id") or ""),
                            "reason": "missing NIK",
                        })
                        continue
                    students.append(s)
    return students, skipped, seen


_LLM_USAGE_PREFIX = "LLM_USAGE:"


def _drain_to_redis(
    stdout,
    redis_client: "redis.Redis",
    log_key: str,
    chan: str,
    usage_buffer: list,
) -> None:
    try:
        for raw in stdout:
            line = raw.rstrip("\n").replace("\r", "").replace("\n", " ")
            if line.startswith(_LLM_USAGE_PREFIX):
                try:
                    usage_buffer.append(json.loads(line[len(_LLM_USAGE_PREFIX):].strip()))
                except json.JSONDecodeError:
                    pass
                # Do not forward to Redis — keep internal telemetry off the live log
                continue
            try:
                redis_client.rpush(log_key, line)
                redis_client.ltrim(log_key, -LOG_RING_MAX, -1)
                redis_client.expire(log_key, LOG_TTL_SECONDS)
                redis_client.publish(chan, line)
            except Exception:
                pass
    except Exception:
        pass


def _build_subprocess_env(
    cfg_path: Path, output_dir: Path, session_dir: Path, screenshot_dir: Path
) -> dict[str, str]:
    env: dict[str, str] = {
        "PYTHONUNBUFFERED": "1",
        "SCRAPER_CONFIG": str(cfg_path),
        "SCRAPER_OUTPUT_DIR": str(output_dir),
        "SCRAPER_SESSION_DIR": str(session_dir),
        "SCRAPER_SCREENSHOT_DIR": str(screenshot_dir),
    }
    for key in _SUBPROCESS_ENV_PASSTHROUGH:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env.setdefault("HOME", "/tmp")
    return env


@celery_app.task(bind=True, name="scrape.run")
def run_scrape(self, job_id: str, kind_value: str, headless: bool = True) -> None:
    db = SessionLocal()
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    log_key = _log_key(job_id)
    chan = _stream_chan(job_id)
    job: ScrapeJob | None = None
    try:
        job_uuid = uuid.UUID(job_id)
        kind = ScrapeKind(kind_value)
        job = db.scalar(
            select(ScrapeJob)
            .options(load_only(*_JOB_TASK_COLS))
            .where(ScrapeJob.id == job_uuid)
        )
        if job is None:
            return
        # Cancel may have arrived while job was PENDING and before this worker
        # picked it up. Honor it without touching status (route already wrote
        # CANCELLED + finished_at).
        if job.status == ScrapeStatus.CANCELLED:
            try:
                redis_client.publish(chan, "__cancelled__")
            except Exception:
                pass
            return

        cred_col = Puskesmas.epus_cred if kind == ScrapeKind.EPUS else Puskesmas.asik_cred
        puskesmas = db.scalar(
            select(Puskesmas)
            .options(load_only(Puskesmas.id, Puskesmas.epus_url, Puskesmas.asik_url, cred_col))
            .where(Puskesmas.id == job.puskesmas_id)
        )
        if puskesmas is None:
            scrape_job_crud.mark_failed(db, job, "puskesmas not found", datetime.now(UTC))
            return

        creds = puskesmas_crud.get_cred_decrypted(puskesmas, kind.value)
        if creds is None:
            scrape_job_crud.mark_failed(db, job, f"{kind.value} credentials not set", datetime.now(UTC))
            return

        patient_nik: str | None = None
        if job.patient_id is not None:
            patient_row = db.scalar(
                select(Patient)
                .options(load_only(Patient.id, Patient.nik))
                .where(Patient.id == job.patient_id)
            )
            if patient_row is None:
                scrape_job_crud.mark_failed(db, job, "patient not found", datetime.now(UTC))
                return
            patient_nik = patient_row.nik
        elif job.target_nik:
            # Orchestrator-driven per-NIK EPUS scrape with no Patient row yet.
            # Worker treats target_nik exactly like patient.nik downstream.
            patient_nik = job.target_nik

        scrape_job_crud.mark_running(db, job, self.request.id or "", datetime.now(UTC))

        with tempfile.TemporaryDirectory(prefix=f"scrape-{kind.value}-") as tmp:
            tmp_path = Path(tmp)
            cfg_path = tmp_path / "config.json"
            out_path = tmp_path / "out.json"
            session_dir = tmp_path / "session"
            output_dir = tmp_path / "output"
            screenshot_dir = tmp_path / "screenshots"
            output_dir.mkdir(parents=True, exist_ok=True)
            session_dir.mkdir(parents=True, exist_ok=True)
            screenshot_dir.mkdir(parents=True, exist_ok=True)

            if kind == ScrapeKind.ASIK:
                session_dir = _asik_session_dir(job.puskesmas_id)
            elif kind == ScrapeKind.ASIK_SEKOLAH:
                session_dir = _asik_sekolah_session_dir(job.puskesmas_id)

            # ASIK and ASIK_SEKOLAH both live on the ASIK portal; only EPUS uses epus_url.
            base_url = puskesmas.epus_url if kind == ScrapeKind.EPUS else puskesmas.asik_url
            base_url_full = f"https://{base_url}" if base_url else None
            try:
                cfg = _build_config(
                    kind, creds, job.date_filter, base_url_full, db,
                    nik=patient_nik, headless=headless,
                    mandiri_only=bool(job.asik_mandiri_only),
                )
            except LlmConfigUnreadable as exc:
                scrape_job_crud.mark_failed(
                    db, job, f"active llm_config unreadable (id={exc})", datetime.now(UTC)
                )
                return
            cfg_path.write_text(json.dumps(cfg))
            os.chmod(cfg_path, 0o600)
            llm_config_id_str = (cfg.get("captcha_solver") or {}).get("llm_config_id")

            # ASIK per-NIK uses a separate scraper module that searches by NIK
            # instead of date-paginating tabs. ePus per-NIK reuses the puskesmas-wide
            # scraper with --nik so it inherits the existing config / pagination.
            if kind == ScrapeKind.ASIK and patient_nik is not None:
                scraper_dir = SCRAPERS_ROOT / "asik_patient"
            else:
                scraper_dir = SCRAPERS_ROOT / kind.value
            env = _build_subprocess_env(cfg_path, output_dir, session_dir, screenshot_dir)

            cmd = [sys.executable, "-u", "scraper.py", "--output", str(out_path)]
            headless_flag = "--headless" if headless else "--no-headless"
            asik_dates: list[str] = []
            if kind == ScrapeKind.ASIK_SEKOLAH:
                # Date-less: the scraper walks every school × class × tab itself.
                cmd += [headless_flag, "--use-session"]
                # Resume: skip schools already saved for this puskesmas in the last
                # 24h (a prior partial run that died/cancelled), so we continue from
                # where it stopped instead of redoing hours of completed schools.
                try:
                    recent = datetime.now(UTC) - timedelta(hours=24)
                    ordered = db.scalars(
                        select(SchoolPatient.school_code)
                        .where(
                            SchoolPatient.puskesmas_id == job.puskesmas_id,
                            SchoolPatient.school_code.isnot(None),
                            SchoolPatient.scraped_at >= recent,
                        )
                        .order_by(SchoolPatient.scraped_at.desc())
                    ).all()
                    # "-1 school" safety: re-scrape the MOST-RECENTLY-completed school
                    # (the resume boundary) even though it's saved. A school can be
                    # saved PARTIAL if some classes were blocked while the session
                    # stayed alive, so skipping it could miss data; re-scraping just
                    # rewrites idempotently (keyed by puskesmas+nik+school_year).
                    newest = ordered[0] if ordered else None
                    skip_codes = sorted({c for c in ordered if c and c != newest})
                    if skip_codes:
                        cmd += ["--skip-schools", ",".join(skip_codes)]
                except Exception:
                    log.exception("failed to compute skip-schools; scraping all schools")
            elif kind == ScrapeKind.ASIK:
                if patient_nik is not None:
                    cmd += ["--nik", patient_nik, headless_flag, "--use-session"]
                elif job.date_filters:
                    # Multi-date ASIK (GDP orchestrator): one browser session,
                    # walks every date in the list. Per-record screening_date
                    # tells the upsert which Patient.filter_date to use.
                    try:
                        asik_dates = [str(d) for d in json.loads(job.date_filters) if d]
                    except (ValueError, TypeError) as exc:
                        scrape_job_crud.mark_failed(
                            db, job, f"invalid date_filters: {exc}", datetime.now(UTC)
                        )
                        return
                    if not asik_dates:
                        scrape_job_crud.mark_failed(
                            db, job, "date_filters is empty", datetime.now(UTC)
                        )
                        return
                    cmd += [
                        "--dates", ",".join(asik_dates),
                        "--tab", "all", headless_flag, "--use-session",
                    ]
                    if job.asik_list_only:
                        cmd += ["--list-only"]
                else:
                    # Puskesmas-wide ASIK: date_filter required (route + cron enforce).
                    assert job.date_filter, "asik puskesmas-wide scrape requires date_filter"
                    cmd += ["--date", job.date_filter, "--tab", "all", headless_flag, "--use-session"]
                    if job.asik_list_only:
                        cmd += ["--list-only"]
                    if job.asik_mandiri_only:
                        # Mandiri-only backfill: open ONLY Mandiri forms, and
                        # restrict to the missing-Mandiri NIKs for this date.
                        cmd += ["--mandiri-only"]
                        if job.target_niks:
                            try:
                                niks = [str(n) for n in json.loads(job.target_niks) if n]
                            except (ValueError, TypeError) as exc:
                                scrape_job_crud.mark_failed(
                                    db, job, f"invalid target_niks: {exc}", datetime.now(UTC)
                                )
                                return
                            if niks:
                                cmd += ["--niks", ",".join(niks)]
            else:
                if job.date_filters and patient_nik is None:
                    # EPUS multi-date (GDP orchestrator). One browser session
                    # walks every date; per-record date drives the upsert.
                    try:
                        epus_dates_iso = [str(d) for d in json.loads(job.date_filters) if d]
                    except (ValueError, TypeError) as exc:
                        scrape_job_crud.mark_failed(
                            db, job, f"invalid date_filters: {exc}", datetime.now(UTC)
                        )
                        return
                    if not epus_dates_iso:
                        scrape_job_crud.mark_failed(
                            db, job, "date_filters is empty", datetime.now(UTC)
                        )
                        return
                    epus_dates_dd = ",".join(_iso_to_ddmmyyyy(d) for d in epus_dates_iso)
                    cmd += ["--dates", epus_dates_dd, headless_flag]
                    if job.target_niks:
                        try:
                            niks = [str(n) for n in json.loads(job.target_niks) if n]
                        except (ValueError, TypeError) as exc:
                            scrape_job_crud.mark_failed(
                                db, job, f"invalid target_niks: {exc}", datetime.now(UTC)
                            )
                            return
                        if niks:
                            cmd += ["--niks", ",".join(niks)]
                else:
                    # ePus always needs a date (per-NIK uses patient.filter_date).
                    assert job.date_filter, "epus scrape requires date_filter"
                    cmd += ["--date", _iso_to_ddmmyyyy(job.date_filter), headless_flag]
                    if patient_nik is not None:
                        cmd += ["--nik", patient_nik]
                # Concurrent per-patient processing. EPUS_PATIENT_WORKERS env
                # overrides default (5). Set to "1" to disable concurrency
                # (legacy sequential mode). Retry on transient errors and
                # 30s per-tab timeout are baked into the scraper's
                # _parallel_fetch; tune via EPUS_FETCH_TIMEOUT / EPUS_FETCH_RETRIES.
                epus_pw = os.environ.get("EPUS_PATIENT_WORKERS", "5")
                cmd += ["--patient-workers", epus_pw]

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
            scrape_timeout_s = max(1, int(settings.SCRAPE_SUBPROCESS_TIMEOUT_SECONDS))
            # Progressive per-date upsert state. EPUS multi-date scraper drops
            # OUTPUT_DIR/by_date/<ISO>.json after each finished date with
            # matches. Worker polls between cancel-flag ticks, upserts +
            # commits per-date so a mid-run cancel preserves earlier dates.
            consumed_dates: set[str] = set()
            inserted_progressive = 0
            updated_progressive = 0
            by_date_dir = output_dir / "by_date"
            # Progressive per-school upsert state for ASIK_SEKOLAH: the scraper
            # writes OUTPUT_DIR/school_*.json after each completed school. Polling
            # + committing per school here means a mid-run cancel/crash preserves
            # every school done so far (the whole-puskesmas run is hours long).
            consumed_school_files: set[str] = set()
            school_inserted_progressive = 0
            school_updated_progressive = 0
            school_scraped_progressive = 0
            try:
                cancel_key = _cancel_key(job_id)
                while proc.poll() is None:
                    time.sleep(2)
                    # Hang backstop. Without this a Playwright subprocess that
                    # never returns holds this Celery slot forever and the job
                    # sits RUNNING with no error (observed: 14.5 h on an ASIK
                    # scrape whose batch tabs could not open). Progressive
                    # per-date / per-school upserts above are already committed,
                    # so a kill here keeps everything finished so far.
                    if time.monotonic() - t0 > scrape_timeout_s:
                        timed_out = True
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        break
                    # Cancel-flag is set by the cancel route in Redis. Polling Redis
                    # avoids one SELECT-per-tick against Postgres (N+1).
                    try:
                        flag = redis_client.get(cancel_key)
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

                    if kind == ScrapeKind.EPUS and by_date_dir.exists():
                        for f in sorted(by_date_dir.glob("*.json")):
                            iso = f.stem
                            if iso in consumed_dates:
                                continue
                            try:
                                day_payload = json.loads(f.read_text())
                            except (json.JSONDecodeError, OSError):
                                continue
                            mini = {"by_date": {iso: day_payload}}
                            day_rows, _, _ = _extract_patients(kind, mini)
                            try:
                                for nik, nama, raw, per_record_date in day_rows:
                                    eff = per_record_date or iso
                                    res = patient_crud.upsert_from_scrape(
                                        db, job.puskesmas_id, kind, nik, nama, raw, eff,
                                    )
                                    if res == "inserted":
                                        inserted_progressive += 1
                                    else:
                                        updated_progressive += 1
                                db.commit()
                                consumed_dates.add(iso)
                            except Exception:
                                db.rollback()
                                log.exception("progressive upsert failed for iso=%s", iso)
                                # leave file unconsumed — retry next tick

                    if kind == ScrapeKind.ASIK_SEKOLAH:
                        for f in sorted(output_dir.glob("school_*.json")):
                            if f.name in consumed_school_files:
                                continue
                            try:
                                payload = json.loads(f.read_text())
                            except (json.JSONDecodeError, OSError):
                                continue  # mid-write — retry next tick
                            students, _, seen = _extract_school_students(payload)
                            try:
                                now_s = datetime.now(UTC)
                                for s in students:
                                    res = school_patient_crud.upsert_from_school_scrape(
                                        db, job.puskesmas_id, s, now_s
                                    )
                                    if res == "inserted":
                                        school_inserted_progressive += 1
                                    else:
                                        school_updated_progressive += 1
                                db.commit()
                                school_scraped_progressive += seen
                                consumed_school_files.add(f.name)
                            except Exception:
                                db.rollback()
                                log.exception("progressive school upsert failed for %s", f.name)
                                # leave file unconsumed — retry next tick

                drain_thread.join(timeout=STDOUT_DRAIN_JOIN_TIMEOUT_SECONDS)
                if drain_thread.is_alive():
                    log.warning(
                        "scraper stdout drain still active after %.1fs; continuing with partial telemetry",
                        STDOUT_DRAIN_JOIN_TIMEOUT_SECONDS,
                    )
            finally:
                # Always stop the sampler — it owns a daemon thread that would otherwise
                # outlive the task and leak across Celery prefork lifecycles.
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
                            log.warning("llm_log row missing model; skipping: %r", u)
                            continue
                        in_tok = u.get("input_tokens")
                        # OpenAI: usage.completion_tokens already includes reasoning_tokens — do not add separately.
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
                                    source=u.get("source", "asik_captcha"),
                                    model=model,
                                    success=bool(u.get("success")),
                                    scrape_job_id=job_uuid,
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
                            log.warning("failed to write llm_log row: %s", exc)
                    db.commit()
                except Exception as exc:
                    log.warning("failed to write llm_logs batch: %s", exc)
                    db.rollback()

            if cancelled:
                # route already wrote CANCELLED + finished_at; persist resource metrics separately
                # Record what the progressive per-school upsert already saved, so a
                # cancelled school job shows its salvaged counts (the rows ARE in the DB).
                if kind == ScrapeKind.ASIK_SEKOLAH and consumed_school_files:
                    try:
                        job.scraped_count = school_scraped_progressive
                        job.inserted_count = school_inserted_progressive
                        job.updated_count = school_updated_progressive
                        db.commit()
                    except Exception:
                        db.rollback()
                try:
                    if resource_metrics and resource_metrics.get("samples", 0) > 0:
                        scrape_job_crud.set_resource_metrics(db, job, resource_metrics)
                except Exception as exc:
                    log.warning("failed to persist resource metrics on cancel: %s", exc)
                try:
                    redis_client.publish(chan, "__cancelled__")
                except Exception:
                    pass
                return

            if proc.returncode != 0:
                # Keep what progressive per-school upsert already saved on a crash.
                if kind == ScrapeKind.ASIK_SEKOLAH and consumed_school_files:
                    try:
                        job.scraped_count = school_scraped_progressive
                        job.inserted_count = school_inserted_progressive
                        job.updated_count = school_updated_progressive
                        db.commit()
                    except Exception:
                        db.rollback()
                try:
                    tail = "\n".join(redis_client.lrange(log_key, -50, -1) or [])
                except Exception:
                    tail = ""
                reason = (
                    f"scrape subprocess exceeded {scrape_timeout_s}s wall clock — killed"
                    if timed_out
                    else f"exit={proc.returncode}"
                )
                scrape_job_crud.mark_failed(
                    db, job,
                    f"{reason}\n{tail}"[:4000],
                    datetime.now(UTC),
                    metrics=resource_metrics,
                )
                try:
                    redis_client.publish(chan, "__failed__")
                except Exception:
                    pass
                return

            try:
                output = json.loads(out_path.read_text())
            except FileNotFoundError:
                scrape_job_crud.mark_failed(
                    db, job, "scraper produced no output file", datetime.now(UTC),
                    metrics=resource_metrics,
                )
                try:
                    redis_client.publish(chan, "__failed__")
                except Exception:
                    pass
                return

            if kind == ScrapeKind.ASIK_SEKOLAH:
                skipped = []
                if consumed_school_files:
                    # Progressive per-school upsert already saved everything during
                    # the run (and survived a cancel/crash). Just report totals;
                    # do NOT re-ingest the full out.json.
                    inserted = school_inserted_progressive
                    updated = school_updated_progressive
                    scraped_count = school_scraped_progressive
                else:
                    # Fallback: no per-school files were produced/consumed (e.g. an
                    # older scraper, or nothing scraped) — ingest the final out.json.
                    students, skipped, scraped_count = _extract_school_students(output)
                    inserted = 0
                    updated = 0
                    now = datetime.now(UTC)
                    try:
                        for student in students:
                            result = school_patient_crud.upsert_from_school_scrape(
                                db, job.puskesmas_id, student, now
                            )
                            if result == "inserted":
                                inserted += 1
                            else:
                                updated += 1
                        db.commit()
                    except Exception:
                        db.rollback()
                        raise
            elif job.asik_mandiri_only:
                # Mandiri-only backfill: patch the new pemeriksaan_mandiri into
                # each existing ASIK blob (never clobber Nakes). Patients with no
                # existing ASIK row are skipped — the backfill only updates rows
                # already in our DB.
                patients, skipped, scraped_count = _extract_patients(kind, output)
                inserted = 0
                updated = 0
                try:
                    for nik, _nama, raw, per_record_date in patients:
                        effective_date = per_record_date or job.date_filter
                        if not effective_date:
                            skipped.append({
                                "source_id": nik, "reason": "missing date for patch",
                            })
                            continue
                        result = patient_crud.patch_mandiri_from_scrape(
                            db, job.puskesmas_id, nik, raw, effective_date
                        )
                        if result == "updated":
                            updated += 1
                        else:
                            skipped.append({
                                "source_id": nik, "reason": "no existing ASIK row to patch",
                            })
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
            else:
                patients, skipped, scraped_count = _extract_patients(kind, output)
                inserted = inserted_progressive
                updated = updated_progressive
                try:
                    for nik, nama, raw, per_record_date in patients:
                        effective_date = per_record_date or job.date_filter
                        if not effective_date:
                            skipped.append({
                                "source_id": nik, "reason": "missing date for upsert",
                            })
                            continue
                        if effective_date in consumed_dates:
                            # already upserted progressively during subprocess run
                            continue
                        result = patient_crud.upsert_from_scrape(
                            db, job.puskesmas_id, kind, nik, nama, raw, effective_date
                        )
                        if result == "inserted":
                            inserted += 1
                        else:
                            updated += 1
                    db.commit()
                except Exception:
                    db.rollback()
                    raise

            notes: str | None = None
            if skipped:
                lines = [
                    f"source_id={s['source_id']} reason={s['reason']}"
                    for s in skipped
                ]
                notes = f"skipped {len(skipped)}:\n" + "\n".join(lines)

            scrape_job_crud.mark_success(
                db, job, scraped_count, inserted, updated, duration, datetime.now(UTC),
                notes=notes, metrics=resource_metrics,
            )
            try:
                redis_client.publish(chan, "__done__")
            except Exception:
                pass
    except Exception as e:
        db.rollback()
        # Sampler.stop() is idempotent — call it here so the daemon thread is reaped
        # even if the exception fired before the inner try/finally would have run.
        _sampler = locals().get("sampler")
        _metrics = _sampler.stop() if _sampler is not None else None
        if job is not None:
            try:
                db.refresh(job, ["status"])
                if job.status != ScrapeStatus.CANCELLED:
                    scrape_job_crud.mark_failed(
                        db, job, str(e)[:2000], datetime.now(UTC), metrics=_metrics,
                    )
            except Exception:
                pass
        try:
            redis_client.publish(chan, "__failed__")
        except Exception:
            pass
        raise
    finally:
        db.close()
