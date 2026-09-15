"""Backend orchestration for the ASIK "create new patient" feature.

For now this ships ONLY the dry-run PROBE path. It measures how many
`epus_only + tandai_ckg` patients are genuinely NOT yet in ASIK (the registration
guard "Individu sudah menerima layanan" is the only reliable detector — see
documents/create-patient-asik/FINDINGS.md §2/§3b), and it captures the step-2
"Isi data pendukung" DOM for the first candidate that reaches it (the Alamat
picker we have never seen). The live-creation write path is wired later.

The heavy lifting runs in a Playwright subprocess (`scrapers/asik_sync/register.py`,
added later); this module builds its config, runs it, and tallies outcomes. It
reuses the ASIK subprocess machinery from `app.tasks.sync` / `app.tasks.scrape`
(session dir, env, captcha solver).
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import redis
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, load_only

from app.celery_app import celery_app
from app.config import settings
from app.crud import patient as patient_crud
from app.crud import puskesmas as puskesmas_crud
from app.crud import sync_job as sync_job_crud
from app.database import SessionLocal
from app.models.patient import MatchStatus, Patient
from app.models.puskesmas import Puskesmas
from app.models.scrape_job import ScrapeKind, TriggererType
from app.models.sync_job import SyncJob, SyncStatus
from app.services.epus_to_asik import _disabilitas, _status_perkawinan, epus_to_asik
from app.tasks.scrape import (
    LOG_RING_MAX,
    LOG_TTL_SECONDS,
    SCRAPERS_ROOT,
    _asik_session_dir,
    _build_captcha_solver,
    _build_subprocess_env,
    _drain_to_redis,
)
from app.tasks.sync import _cancel_key as _sync_cancel_key
from app.tasks.sync import _execute_sync, _log_key, _stream_chan

log = logging.getLogger(__name__)

# The four outcome buckets a dry-run probe tallies. Anything the scraper emits
# that is not one of {would_create, already_served, dukcapil_invalid} lands in
# `error` (and is logged with its raw outcome), so a probe run always sums to
# `probed` even if the scraper grows a new terminal state.
_DEFAULT_WHATSAPP = "800000000"

# ASIK step-2 "Isi data pendukung" defaults (field structure captured live —
# documents/create-patient-asik/FINDINGS.md §Step2). ePus carries none of these
# except a free-text address, so we default and log to asik_default_fills.
_DEFAULT_STATUS_PERNIKAHAN = "Belum Menikah"
_DEFAULT_DISABILITAS = "Tidak memiliki disabilitas"  # else "Memiliki disablilitas" (ASIK's typo)
_DEFAULT_PEKERJAAN = "Lainnya"


def _derive_from_nik(nik: str) -> tuple[date, str]:
    """Derive (birth_date, gender) from an Indonesian NIK.

    Digits 7-12 (1-indexed) encode DDMMYY. A day > 40 means female — subtract 40
    to recover the real day. The 2-digit year is disambiguated to a full year by
    plausibility: prefer the most-recent century that yields an age in [0, 120]
    as of today (so `85` → 1985, `05` → 2005). Registration's Dukcapil gate
    validates DOB against the NIK's own DDMMYY, so this — NOT `patient.birth_date`
    — is what must be filled (FINDINGS §3).

    Raises ValueError for a NIK too short to carry a date or one whose DDMMYY is
    not a plausible real birth date.
    """
    digits = "".join(ch for ch in (nik or "") if ch.isdigit())
    if len(digits) < 12:
        raise ValueError(f"NIK too short to derive DOB/gender: {nik!r}")
    dd = int(digits[6:8])
    mm = int(digits[8:10])
    yy = int(digits[10:12])
    female = dd > 40
    day = dd - 40 if female else dd
    gender = "Perempuan" if female else "Laki-laki"
    today = date.today()
    # Most-recent century first — the first valid one is the most recent past.
    for century in (2000, 1900):
        try:
            candidate = date(century + yy, mm, day)
        except ValueError:
            continue
        age = today.year - candidate.year - (
            (today.month, today.day) < (candidate.month, candidate.day)
        )
        if 0 <= age <= 120:
            return candidate, gender
    raise ValueError(f"NIK encodes an implausible birth date: {nik!r}")


def _is_own_nik(nik: str, birth_date: date | None) -> bool:
    """True when the NIK's embedded DDMMYY == birth_date — i.e. the NIK belongs to
    THIS patient (their own KIA/KTP NIK), not a guardian's. Every Indonesian NIK
    (KIA included) encodes the holder's own DOB, so a minor recorded under a
    parent's NIK, or a bayi carrying the parent's NIK, fails this check."""
    if birth_date is None:
        return False
    try:
        nik_dob, _gender = _derive_from_nik(nik)
    except ValueError:
        return False
    return nik_dob == birth_date


def _wali_block_reason(nik: str, birth_date: date | None, exam_date: date) -> str | None:
    """Why this patient can't be auto-created via the own-NIK path — i.e. needs the
    (not-yet-built) wali flow — or None if creatable. Two gates, both verified against
    live ASIK on 2026-08-31 (Puskesmas Poso dry-run probes):

    - Under 6 at the exam date → ASIK makes the wali section mandatory (Selanjutnya
      stays disabled) EVEN when the child's own NIK is filled. Age 6+ registers fine
      without wali.
    - A minor (<18) whose NIK's DOB does not match their birth date is recorded under
      someone else's NIK (a guardian's). "Daftarkan dengan NIK" would lock onto that
      person's Dukcapil identity — the fatal mis-assign — so it must go to the wali flow.

    Adults are never own-NIK-gated (an adult's NIK is their own; a mismatch is a
    birth_date data glitch and registration derives DOB from the NIK anyway)."""
    if birth_date is None:
        return "no birth_date on record — cannot age-gate the create"
    age = exam_date.year - birth_date.year - (
        (exam_date.month, exam_date.day) < (birth_date.month, birth_date.day)
    )
    if age < 6:
        return f"under 6 at exam date (age {age}) — ASIK requires wali data"
    if age < 18 and not _is_own_nik(nik, birth_date):
        return "minor whose NIK does not match their birth date — likely a guardian's NIK"
    return None


def _title_case_name(nama: str) -> str:
    """"SANTI" → "Santi", per word. ASIK stores names in title case.

    Word-based (not str.title) so punctuation rides along untouched: "SANTI, ANI"
    → "Santi, Ani", "BUDI" → "Budi". Robust to empty / stray tokens.
    """
    return " ".join(w[:1].upper() + w[1:].lower() for w in (nama or "").split())


def _whatsapp_from_epus(epus: dict) -> tuple[str, bool]:
    """Normalize the ePus phone to an ASIK-fillable number.

    ASIK's field carries a +62 prefix and requires the local part to start with
    8. ePus stores it under `data_pasien["No Telp / HP"]` (e.g. "081319373789").
    Strip non-digits, drop a single leading 0, and accept it only if it then
    starts with 8 and is 9-14 digits long. Otherwise fall back to a placeholder.

    Returns (whatsapp, used_default) — used_default=True is worth logging to
    asik_default_fills so a fabricated number is never mistaken for real data.
    """
    raw = ((epus or {}).get("data_pasien") or {}).get("No Telp / HP")
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if digits.startswith("0"):
        digits = digits[1:]
    if digits.startswith("8") and 9 <= len(digits) <= 14:
        return digits, False
    return _DEFAULT_WHATSAPP, True


def _build_step2(patient: Patient, epus: dict, puskesmas: Puskesmas) -> dict[str, Any] | None:
    """Assemble the ASIK step-2 "Isi data pendukung" values for a live create.

    Returns None when the puskesmas has NO configured default alamat — the caller
    must then SKIP the patient, because the 4-level Alamat Domisili cascade is
    required and we never guess a domicile.

    Sourcing (FINDINGS.md §Step2): Status Pernikahan + disabilitas reuse the
    `epus_to_asik` converter (default when ePus lacks them); Pekerjaan has no
    ePus source → always "Lainnya"; the Alamat cascade uses the puskesmas'
    configured Prov/Kota/Kec/Kel names; Detail Alamat = ePus free-text `Alamat`.
    Defaulted fields should be logged to `patient.asik_default_fills` by the live
    create task that commits the registration.
    """
    alamat_cfg = puskesmas.asik_default_alamat
    if not alamat_cfg:
        return None
    pasien = ((epus or {}).get("data_pasien")) or {}
    status = _status_perkawinan(pasien.get("Status Perkawinan")) or _DEFAULT_STATUS_PERNIKAHAN
    disabilitas = (
        "Memiliki disablilitas"
        if _disabilitas(epus or {}) == "Penyandang disabilitas"
        else _DEFAULT_DISABILITAS
    )
    raw_alamat = pasien.get("Alamat")
    detail_alamat = re.sub(r"\s+", " ", str(raw_alamat)).strip() if raw_alamat else ""
    return {
        "status_pernikahan": status,
        "disabilitas": disabilitas,
        "pekerjaan": _DEFAULT_PEKERJAAN,
        "alamat": {
            "provinsi": (alamat_cfg.get("provinsi") or {}).get("name"),
            "kota": (alamat_cfg.get("kota") or {}).get("name"),
            "kecamatan": (alamat_cfg.get("kecamatan") or {}).get("name"),
            "kelurahan": (alamat_cfg.get("kelurahan") or {}).get("name"),
        },
        "detail_alamat": detail_alamat,
    }


def _build_register_config(
    *,
    asik_creds: dict,
    base_url: str,
    patient: Patient,
    epus: dict,
    exam_date: date,
    dry_run_probe: bool,
    captcha_solver: dict[str, Any],
    headless: bool,
    step2: dict[str, Any] | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    """Build the config.json the `register.py` scraper reads.

    Identity is derived here, not taken from the ORM: name from the ePus
    `data_pasien["Nama Pasien"]` (title-cased), DOB + gender from the NIK,
    whatsapp normalized from ePus. `_derive_from_nik` may raise ValueError for a
    malformed NIK — the caller treats that as an un-probable patient. `step2` is
    the assembled step-2 fill (from `_build_step2`) — supplied only on the LIVE
    path; the dry-run probe stops before step 2 and omits it.
    """
    birth_date, gender = _derive_from_nik(patient.nik)
    nama_raw = ((epus or {}).get("data_pasien") or {}).get("Nama Pasien") or patient.nama
    whatsapp, _used_default = _whatsapp_from_epus(epus)
    register: dict[str, Any] = {
        "nik": patient.nik,
        "nama": _title_case_name(nama_raw),
        "dob": birth_date.isoformat(),
        "gender": gender,
        "whatsapp": whatsapp,
        "exam_date": exam_date.isoformat(),
    }
    if step2 is not None:
        register["step2"] = step2
    # commit=True enables register.py's live create path (step 3 "Daftarkan dengan
    # NIK" = THE COMMIT → Konfirmasi Hadir). Only the create task sets this; the
    # dry-run probe never does, so a probe can never write an ASIK record.
    register["commit"] = bool(commit)
    return {
        "base_url": base_url,
        "login_path": "/login",
        "headless": headless,
        "timeout": 60000,
        "slow_mo": 0,
        # "persistent" = own the Chromium profile and log in (the probe runs one
        # patient at a time, so there is no shared-session parallelism here).
        "session_mode": "persistent",
        "use_session": True,
        "credentials": {
            "username": asik_creds.get("email", ""),
            "password": asik_creds.get("password", ""),
        },
        # CAPTCHA solver mirrors the scrape/sync pipeline: LLM when configured,
        # manual fallback. A warm saved session skips CAPTCHA on the happy path.
        "captcha_solver": captcha_solver,
        # True = fill step-1, click Selanjutnya, read the guard, and STOP before
        # any commit (Daftarkan dengan NIK). No ASIK record is created.
        "dry_run_probe": dry_run_probe,
        "register": register,
    }


def _read_register_output(out_path: Path) -> dict[str, Any]:
    """Parse register.py's output.json, mapping every failure to an error dict."""
    try:
        return json.loads(out_path.read_text())
    except FileNotFoundError:
        return {"outcome": "error", "error": "register produced no output file"}
    except (ValueError, OSError) as exc:
        return {"outcome": "error", "error": f"unreadable register output: {exc}"}


def _run_register(
    *,
    cfg: dict[str, Any],
    session_dir: Path,
    timeout: int,
    redis_client: "redis.Redis | None" = None,
    log_key: str | None = None,
    stream_chan: str | None = None,
    cancel_key_str: str | None = None,
) -> dict[str, Any]:
    """Run the `register.py` scraper subprocess for ONE patient and return its
    parsed output.json. Never raises: a launch/exit/timeout/parse failure comes
    back as `{"outcome": "error", "error": <msg>}` so a caller loop keeps going.

    Two modes:
    - PROBE (redis_client None): capture stdout in one shot (logged at debug), no
      cancel polling — a dry-run probe is short and one-shot.
    - STREAMED (redis_client + log_key given): drain stdout LIVE to the SyncJob log
      (RPUSH log_key + PUBLISH stream_chan via `_drain_to_redis`) and poll
      `cancel_key_str` so the register phase shows in the same live log as the fill.
    Both kill a hung Chromium subprocess at the wall-clock timeout.
    """
    streaming = redis_client is not None and log_key is not None
    with tempfile.TemporaryDirectory(prefix="create-asik-") as tmp:
        tmp_path = Path(tmp)
        cfg_path = tmp_path / "config.json"
        out_path = tmp_path / "out.json"
        output_dir = tmp_path / "output"
        screenshot_dir = tmp_path / "screenshots"
        output_dir.mkdir(parents=True, exist_ok=True)
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        cfg_path.write_text(json.dumps(cfg))
        os.chmod(cfg_path, 0o600)

        scraper_dir = SCRAPERS_ROOT / "asik_sync"
        env = _build_subprocess_env(cfg_path, output_dir, session_dir, screenshot_dir)
        cmd = [sys.executable, "-u", "register.py", "--output", str(out_path)]

        # Headed Chromium needs an X display. The Linux worker container has none,
        # so wrap with xvfb-run; on a macOS/Windows dev host (no xvfb-run) skip it.
        exec_cmd = cmd
        if not cfg.get("headless", True) and shutil.which("xvfb-run"):
            exec_cmd = ["xvfb-run", "-a", "--", *cmd]

        proc = subprocess.Popen(
            exec_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1 if streaming else -1,
            cwd=str(scraper_dir),
            env=env,
        )

        if not streaming:
            try:
                stdout, _ = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                proc.communicate()  # reap the pipe so the tempdir can be cleaned up
                return {
                    "outcome": "error",
                    "error": f"register subprocess exceeded {timeout}s wall clock — killed",
                }
            if stdout:
                log.debug("register stdout:\n%s", stdout)
            if proc.returncode != 0:
                tail = "\n".join((stdout or "").splitlines()[-30:])
                return {"outcome": "error", "error": f"exit={proc.returncode}\n{tail}"[:2000]}
            return _read_register_output(out_path)

        # Streamed: a daemon thread pumps stdout → Redis; this loop watches for the
        # subprocess exit, the wall-clock timeout, and the cancel flag (throttled to
        # ~2s so a ~90s register doesn't hammer Redis).
        drain = threading.Thread(
            target=_drain_to_redis,
            args=(proc.stdout, redis_client, log_key, stream_chan, []),
            daemon=True,
        )
        drain.start()
        t0 = time.monotonic()
        last_cancel_check = 0.0
        cancelled = False
        timed_out = False
        while proc.poll() is None:
            time.sleep(0.25)
            now = time.monotonic()
            if now - t0 > timeout:
                timed_out = True
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            if cancel_key_str and now - last_cancel_check >= 2.0:
                last_cancel_check = now
                try:
                    if redis_client.get(cancel_key_str) == "1":
                        cancelled = True
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        break
                except Exception:
                    pass
        drain.join(timeout=5)
        if cancelled:
            return {"outcome": "cancelled"}
        if timed_out:
            return {
                "outcome": "error",
                "error": f"register subprocess exceeded {timeout}s wall clock — killed",
            }
        if proc.returncode not in (0, None):
            return {"outcome": "error", "error": f"register exited {proc.returncode}"}
        return _read_register_output(out_path)


def probe_batch(
    db: Session,
    puskesmas_id: uuid.UUID,
    *,
    limit: int,
    dry_run: bool = True,
    headless: bool = True,
    adults_only: bool = False,
) -> dict[str, Any]:
    """Dry-run probe the `epus_only + tandai_ckg` population of one puskesmas.

    For up to `limit` current-year candidates (most-recent visit first — past
    years are greyed on ASIK's registration calendar and cannot be created),
    run register.py in dry-run mode: fill step-1, click Selanjutnya, read the
    guard, commit nothing. Returns a tally of outcomes, the list of `would_create`
    NIKs (genuinely not-yet-in-ASIK), and the FIRST captured step2_dom.
    """
    puskesmas = db.scalar(
        select(Puskesmas)
        .options(load_only(
            Puskesmas.id, Puskesmas.name, Puskesmas.asik_url, Puskesmas.asik_cred,
        ))
        .where(Puskesmas.id == puskesmas_id)
    )
    if puskesmas is None:
        raise RuntimeError(f"puskesmas {puskesmas_id} not found")

    creds = puskesmas_crud.get_cred_decrypted(puskesmas, "asik")
    if creds is None:
        raise RuntimeError("asik credentials not set for this puskesmas")
    base_url = f"https://{puskesmas.asik_url}" if puskesmas.asik_url else None
    if not base_url:
        raise RuntimeError("asik_url not set for this puskesmas")

    captcha_solver = _build_captcha_solver(db)
    session_dir = _asik_session_dir(puskesmas_id)
    timeout = max(1, int(settings.SYNC_SUBPROCESS_TIMEOUT_SECONDS))

    today = date.today()
    exam_date = today
    year_start = date(today.year, 1, 1)
    conds = [
        Patient.puskesmas_id == puskesmas_id,
        Patient.match_status == MatchStatus.EPUS_ONLY,
        Patient.epus_tandai_ckg.is_(True),
        Patient.filter_date >= year_start,
    ]
    if adults_only:
        # 18+ only: excludes balita/children, who need mandatory guardian (wali)
        # data we don't scrape and therefore cannot be registered anyway.
        adult_cutoff = date(today.year - 18, today.month, today.day)
        conds.append(Patient.birth_date.isnot(None))
        conds.append(Patient.birth_date <= adult_cutoff)
    patients = list(db.scalars(
        select(Patient)
        .options(load_only(
            Patient.id, Patient.nik, Patient.nama, Patient.birth_date,
            Patient.filter_date, Patient.scraped_epus_data,
        ))
        .where(*conds)
        .order_by(Patient.filter_date.desc())
        .limit(limit)
    ).all())

    tally = {"would_create": 0, "already_served": 0, "dukcapil_invalid": 0, "error": 0}
    would_create_niks: list[str] = []
    first_step2_dom: Any = None

    log.info(
        "probe start: puskesmas=%s (%s) candidates=%d dry_run=%s",
        puskesmas.name, puskesmas_id, len(patients), dry_run,
    )
    total = len(patients)
    for i, patient in enumerate(patients, start=1):
        nik = patient.nik
        try:
            epus = patient_crud.decrypt_field(patient, ScrapeKind.EPUS)
        except Exception as exc:
            log.warning("probe %d/%d NIK=%s: epus decrypt failed: %s", i, total, nik, exc)
            tally["error"] += 1
            continue
        if not epus:
            log.warning("probe %d/%d NIK=%s: no scraped_epus_data", i, total, nik)
            tally["error"] += 1
            continue

        try:
            cfg = _build_register_config(
                asik_creds=creds,
                base_url=base_url,
                patient=patient,
                epus=epus,
                exam_date=exam_date,
                dry_run_probe=dry_run,
                captcha_solver=captcha_solver,
                headless=headless,
            )
        except ValueError as exc:
            log.warning("probe %d/%d NIK=%s: not derivable: %s", i, total, nik, exc)
            tally["error"] += 1
            continue

        log.info("probe %d/%d NIK=%s → register (dry_run=%s)", i, total, nik, dry_run)
        out = _run_register(cfg=cfg, session_dir=session_dir, timeout=timeout)
        outcome = out.get("outcome") or "error"

        if outcome == "would_create":
            tally["would_create"] += 1
            would_create_niks.append(nik)
        elif outcome == "already_served":
            tally["already_served"] += 1
        elif outcome == "dukcapil_invalid":
            tally["dukcapil_invalid"] += 1
        else:
            tally["error"] += 1
            log.warning(
                "probe %d/%d NIK=%s: unexpected outcome=%s error=%s",
                i, total, nik, outcome, out.get("error"),
            )

        if first_step2_dom is None and out.get("step2_dom"):
            first_step2_dom = out.get("step2_dom")
        log.info("probe %d/%d NIK=%s → %s", i, total, nik, outcome)

    log.info("probe done: puskesmas=%s tally=%s", puskesmas.name, tally)
    return {
        "puskesmas_id": str(puskesmas_id),
        "puskesmas_name": puskesmas.name,
        "dry_run": dry_run,
        "probed": total,
        "tally": tally,
        "would_create_niks": would_create_niks,
        "step2_dom": first_step2_dom,
    }


def _log_line(
    redis_client: "redis.Redis", log_key: str, chan: str, line: str
) -> None:
    """Append one annotation line to the SyncJob live log (same ring/TTL/publish
    contract as `_drain_to_redis`), so the create phase reads like a normal sync log."""
    try:
        redis_client.rpush(log_key, line)
        redis_client.ltrim(log_key, -LOG_RING_MAX, -1)
        redis_client.expire(log_key, LOG_TTL_SECONDS)
        redis_client.publish(chan, line)
    except Exception:
        pass


# Human-readable reasons for the register outcomes that stop the flow before a fill.
_REGISTER_FAIL_REASON = {
    "already_served": "patient already registered in ASIK (sudah menerima layanan)",
    "dukcapil_invalid": "Dukcapil validation failed (NIK / name / DOB mismatch)",
    "step2_filled": "stopped after step 2 (commit disabled)",
}


def create_one_patient(
    db: Session,
    *,
    job: "SyncJob",
    patient: Patient,
    epus: dict,
    puskesmas: Puskesmas,
    base_url: str,
    creds: dict,
    captcha_solver: dict[str, Any],
    headless: bool,
    redis_client: "redis.Redis",
    cancel_key_str: str,
    celery_task_id: str = "",
) -> tuple[str, str]:
    """The ONE create+fill flow for a single epus_only patient, tracked on an EXISTING
    SyncJob (created by the caller — the manual route or the cron batch). Streams both
    the register subprocess AND the fill subprocess to that job's live log, so it shows
    in the sync-jobs history/log UI exactly like a normal sync.

    Steps: mark job running → register into ASIK (register.py COMMIT, exam date =
    patient.filter_date) → on `created`, fill the exam via the existing `_execute_sync`
    (builds merged live from ePus via `epus_to_asik`, stamps `asik_synced_at`, logs
    `asik_default_fills`, finalizes the job). Any non-`created` register outcome finalizes
    the job FAILED with a clear reason and publishes the SSE terminal event itself (so a
    watcher's stream closes). Returns (register_outcome, job_terminal_status).

    NOTE: deliberately bypasses `run_sync`'s `ALLOW_EPUS_ONLY_SYNC` gate — filling an
    epus_only patient is the whole point here, and `_execute_sync` takes the pre-built
    `merged` blob directly.
    """
    log_key = _log_key(str(job.id))
    chan = _stream_chan(str(job.id))
    sync_job_crud.mark_running(db, job, celery_task_id, datetime.now(UTC), 0)

    # Own-NIK / age gate (defense in depth — the batch pre-filters, but the manual
    # single-create route reaches here directly). A patient needing the wali flow
    # must never be registered via "Daftarkan dengan NIK".
    block = _wali_block_reason(patient.nik, patient.birth_date, patient.filter_date)
    if block:
        msg = f"cannot create via own NIK — {block} (wali flow not yet supported)"
        _log_line(redis_client, log_key, chan, f"[create] {msg}")
        sync_job_crud.mark_failed(db, job, msg, datetime.now(UTC))
        try:
            redis_client.publish(chan, "__failed__")
        except Exception:
            pass
        return "needs_wali", "failed"

    step2 = _build_step2(patient, epus, puskesmas)
    if step2 is None:
        msg = "puskesmas has no ASIK default alamat configured — cannot register"
        _log_line(redis_client, log_key, chan, f"[create] {msg}")
        sync_job_crud.mark_failed(db, job, msg, datetime.now(UTC))
        try:
            redis_client.publish(chan, "__failed__")
        except Exception:
            pass
        return "skipped_no_alamat", "failed"

    try:
        cfg = _build_register_config(
            asik_creds=creds,
            base_url=base_url,
            patient=patient,
            epus=epus,
            exam_date=patient.filter_date,  # ePus visit date = ASIK Tanggal Pemeriksaan
            dry_run_probe=False,
            captcha_solver=captcha_solver,
            headless=headless,
            step2=step2,
            commit=True,
        )
    except ValueError as exc:
        msg = f"cannot derive DOB/gender from NIK — not registerable: {exc}"
        _log_line(redis_client, log_key, chan, f"[create] {msg}")
        sync_job_crud.mark_failed(db, job, msg, datetime.now(UTC))
        try:
            redis_client.publish(chan, "__failed__")
        except Exception:
            pass
        return "error", "failed"

    session_dir = _asik_session_dir(puskesmas.id)
    timeout = max(1, int(settings.SYNC_SUBPROCESS_TIMEOUT_SECONDS))
    _log_line(
        redis_client, log_key, chan,
        f"[create] registering NIK {patient.nik} into ASIK "
        f"(exam date {patient.filter_date.isoformat()})",
    )
    out = _run_register(
        cfg=cfg,
        session_dir=session_dir,
        timeout=timeout,
        redis_client=redis_client,
        log_key=log_key,
        stream_chan=chan,
        cancel_key_str=cancel_key_str,
    )
    outcome = out.get("outcome") or "error"

    if outcome == "cancelled":
        _log_line(redis_client, log_key, chan, "[create] cancelled during registration")
        sync_job_crud.mark_cancelled(db, job)
        try:
            redis_client.publish(chan, "__cancelled__")
        except Exception:
            pass
        return "cancelled", "cancelled"

    if outcome != "created":
        reason = _REGISTER_FAIL_REASON.get(outcome) or out.get("error") or f"outcome {outcome}"
        _log_line(redis_client, log_key, chan, f"[create] not created — {outcome}: {reason}")
        sync_job_crud.mark_failed(db, job, f"{outcome}: {reason}"[:2000], datetime.now(UTC))
        try:
            redis_client.publish(chan, "__failed__")
        except Exception:
            pass
        return outcome, "failed"

    # Registered + attended → fill the exam via the existing sync machinery. It streams
    # to the SAME job log and finalizes the job (success/failed + SSE terminal event).
    _log_line(
        redis_client, log_key, chan,
        f"[create] registered (ticket={out.get('ticket')} hadir={out.get('hadir')}) "
        f"→ filling exam via sync",
    )
    merged = epus_to_asik(epus)
    forms_total = sum(
        1 for v in (merged or {}).values()
        if isinstance(v, dict) and any(x is not None and x != "" for x in v.values())
    )
    status = _execute_sync(
        db=db,
        redis_client=redis_client,
        job=job,
        patient=patient,
        base_url_full=base_url,
        creds=creds,
        captcha_solver=captcha_solver,
        merged=merged,
        forms_total=forms_total,
        headless=headless,
        celery_task_id=celery_task_id,
        cancel_key_str=cancel_key_str,
    )
    return "created", status


def create_batch(
    db: Session,
    puskesmas_id: uuid.UUID,
    *,
    target_date: date | None = None,
    limit: int,
    headless: bool = True,
    triggered_by_id: uuid.UUID | None = None,
    cron_run_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Register `epus_only + tandai_ckg` patients into ASIK, then fill — ONE SyncJob per
    patient (streamed to the sync-jobs log/history, exactly like a normal sync).

    `target_date` set → this specific date's cohort (`filter_date == target_date`) — the
    cron/backfill per-date step, mirroring the sync step. None → every still-creatable
    candidate this year (`filter_date >= Jan 1`) — a manual bulk run. Patients already
    stamped `asik_synced_at` are skipped (a prior create+fill handled them). The ASIK EXAM
    date is set PER PATIENT to `patient.filter_date` (the ePus "Tanggal Pemeriksaan"), so the
    created record carries the same visit date as ePuskesmas; prior YEARS are greyed on
    ASIK's calendar and excluded. Most-recent-first.

    Each candidate runs through `create_one_patient` (register COMMIT → Konfirmasi Hadir →
    fill via `_execute_sync`), SEQUENTIALLY on the one shared ASIK session. Returns a tally
    + the created NIKs.
    """
    # cron cancel key lives in cron.py; import lazily to avoid an import cycle.
    from app.tasks.cron import cancel_key as _cron_cancel_key

    puskesmas = db.scalar(
        select(Puskesmas)
        .options(load_only(
            Puskesmas.id, Puskesmas.name, Puskesmas.asik_url, Puskesmas.asik_cred,
            Puskesmas.asik_default_alamat,
        ))
        .where(Puskesmas.id == puskesmas_id)
    )
    if puskesmas is None:
        raise RuntimeError(f"puskesmas {puskesmas_id} not found")

    creds = puskesmas_crud.get_cred_decrypted(puskesmas, "asik")
    if creds is None:
        raise RuntimeError("asik credentials not set for this puskesmas")
    base_url = f"https://{puskesmas.asik_url}" if puskesmas.asik_url else None
    if not base_url:
        raise RuntimeError("asik_url not set for this puskesmas")

    # No default alamat → the required 4-level domicile cascade can't be filled. Skip the
    # WHOLE batch cleanly (one early return) rather than failing one job per patient.
    if not puskesmas.asik_default_alamat:
        log.info("create: puskesmas %s has no asik_default_alamat → batch skipped", puskesmas.name)
        return {
            "puskesmas_id": str(puskesmas_id), "puskesmas_name": puskesmas.name,
            "candidates": 0, "tally": {}, "created_niks": [], "skipped_no_alamat_config": True,
        }

    captcha_solver = _build_captcha_solver(db)
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    trig_id = triggered_by_id or puskesmas_id

    today = date.today()
    # A prior-year target date is greyed on ASIK's registration calendar and can't be
    # registered at all → the whole cohort is unreachable, so short-circuit to a no-op.
    # (Per-patient exam date = patient.filter_date; see create_one_patient.)
    if target_date is not None and target_date.year < today.year:
        log.info("create: target_date %s is a prior year (calendar greyed) → no-op", target_date)
        return {
            "puskesmas_id": str(puskesmas_id), "puskesmas_name": puskesmas.name,
            "candidates": 0, "tally": {}, "created_niks": [], "skipped_prior_year": True,
        }
    conds = [
        Patient.puskesmas_id == puskesmas_id,
        Patient.match_status == MatchStatus.EPUS_ONLY,
        Patient.epus_tandai_ckg.is_(True),
        # Skip anyone a previous create+fill already synced (mirrors sync NORMAL mode).
        Patient.asik_synced_at.is_(None),
    ]
    if target_date is not None:
        # Cron/backfill per-date step: this date's epus_only cohort (mirrors sync).
        conds.append(Patient.filter_date == target_date)
    else:
        # Manual bulk run: everyone still creatable this year (prior years are greyed).
        conds.append(Patient.filter_date >= date(today.year, 1, 1))
    # Stream-A create gate: only patients creatable via their OWN NIK. Coarse SQL
    # floor drops anyone clearly under 6 (ASIK mandates wali for <6 — unsupported).
    # `today - 6y` is over-inclusive vs the per-patient exam-date age (age only grows,
    # so nobody ≥6 at their exam date is dropped); the precise age + own-NIK guard runs
    # per patient in the loop (`_wali_block_reason`). birth_date is required to age-gate.
    conds.append(Patient.birth_date.isnot(None))
    conds.append(Patient.birth_date <= date(today.year - 6, today.month, today.day))
    # CKG is one screening per person per year. A same-NIK row carrying ASIK data in the
    # same year means ASIK already has this person (register would only answer
    # already_served), even when the matcher never paired it with THIS ePus visit.
    # Decision: leave those alone — no job, no retry.
    # The soft-delete auto-filter does NOT reach these correlated EXISTS subqueries
    # (verified by compiling the statement), so deleted_at is filtered explicitly.
    asik_row = aliased(Patient)
    conds.append(~exists().where(
        asik_row.puskesmas_id == Patient.puskesmas_id,
        asik_row.nik == Patient.nik,
        asik_row.id != Patient.id,
        asik_row.scraped_asik_data.isnot(None),
        func.extract("year", asik_row.filter_date) == func.extract("year", Patient.filter_date),
        asik_row.deleted_at.is_(None),
    ))
    # already_served is terminal: without this the cron lookback re-picks the same patient
    # every run. The manual single create (create.run_one) does not go through here.
    conds.append(~exists().where(
        SyncJob.patient_id == Patient.id,
        SyncJob.error_message.like("already_served:%"),
        SyncJob.deleted_at.is_(None),
    ))
    patients = list(db.scalars(
        select(Patient)
        .options(load_only(
            Patient.id, Patient.puskesmas_id, Patient.nik, Patient.nama,
            Patient.birth_date, Patient.filter_date, Patient.scraped_epus_data,
        ))
        .where(*conds)
        .order_by(Patient.filter_date.desc())
        .limit(limit)
    ).all())

    tally = {
        "created": 0, "filled": 0, "fill_failed": 0,
        "already_served": 0, "dukcapil_invalid": 0,
        "cancelled": 0, "skipped_active_job": 0, "needs_wali": 0, "error": 0,
    }
    created_niks: list[str] = []
    total = len(patients)
    log.info("create start: puskesmas=%s (%s) candidates=%d", puskesmas.name, puskesmas_id, total)

    for i, patient in enumerate(patients, start=1):
        nik = patient.nik
        try:
            epus = patient_crud.decrypt_field(patient, ScrapeKind.EPUS)
        except Exception as exc:
            log.warning("create %d/%d NIK=%s: epus decrypt failed: %s", i, total, nik, exc)
            tally["error"] += 1
            continue
        if not epus:
            log.warning("create %d/%d NIK=%s: no scraped_epus_data", i, total, nik)
            tally["error"] += 1
            continue

        # Own-NIK / age gate — skip anyone needing the (unbuilt) wali flow BEFORE
        # opening a SyncJob, so no noisy failed job is created for them.
        block = _wali_block_reason(nik, patient.birth_date, patient.filter_date)
        if block:
            log.info("create %d/%d NIK=%s: needs wali flow — skip (%s)", i, total, nik, block)
            tally["needs_wali"] += 1
            continue

        # One SyncJob per patient. The active-per-patient unique index means a patient
        # already mid-sync is skipped rather than double-registered.
        try:
            job = sync_job_crud.create(
                db,
                puskesmas_id=puskesmas_id,
                patient_id=patient.id,
                triggered_by_id=trig_id,
                triggered_by_type=TriggererType.CRON,
                cron_run_id=cron_run_id,
            )
        except IntegrityError:
            db.rollback()
            log.info("create %d/%d NIK=%s: active sync job exists → skip", i, total, nik)
            tally["skipped_active_job"] += 1
            continue

        cancel_key_str = (
            _cron_cancel_key(str(cron_run_id)) if cron_run_id is not None
            else _sync_cancel_key(str(job.id))
        )
        try:
            outcome, status = create_one_patient(
                db,
                job=job,
                patient=patient,
                epus=epus,
                puskesmas=puskesmas,
                base_url=base_url,
                creds=creds,
                captcha_solver=captcha_solver,
                headless=headless,
                redis_client=redis_client,
                cancel_key_str=cancel_key_str,
            )
        except Exception as exc:
            log.warning("create %d/%d NIK=%s: create_one_patient raised: %s", i, total, nik, exc)
            outcome, status = "error", "failed"

        if outcome == "created":
            tally["created"] += 1
            created_niks.append(nik)
            tally["filled" if status == "success" else "fill_failed"] += 1
        elif outcome in ("already_served", "dukcapil_invalid", "needs_wali"):
            tally[outcome] += 1
        elif outcome == "cancelled":
            tally["cancelled"] += 1
            log.info("create: cancelled at NIK=%s → stop batch", nik)
            break
        else:
            tally["error"] += 1
        log.info("create %d/%d NIK=%s → %s (job=%s status=%s)", i, total, nik, outcome, job.id, status)

    log.info("create done: puskesmas=%s tally=%s", puskesmas.name, tally)
    return {
        "puskesmas_id": str(puskesmas_id),
        "puskesmas_name": puskesmas.name,
        "candidates": total,
        "tally": tally,
        "created_niks": created_niks,
    }


@celery_app.task(name="create.probe_batch")
def run_probe_batch(puskesmas_id: str, limit: int = 20) -> None:
    """Celery wrapper around `probe_batch` (for later scheduled/triggered use).

    Kept thin: opens a Session, runs the probe, logs the tally. The rich result
    (would_create NIKs, step2_dom) is returned by `probe_batch` for the CLI
    (scripts/probe_create_yield.py); here it is only logged.
    """
    db = SessionLocal()
    try:
        result = probe_batch(db, uuid.UUID(puskesmas_id), limit=limit)
        log.info("create.probe_batch: tally=%s", result.get("tally"))
    finally:
        db.close()


@celery_app.task(name="create.run_batch")
def run_create_batch(
    puskesmas_id: str, limit: int = 20, target_date: str | None = None
) -> None:
    """Celery wrapper around `create_batch` (for cron/triggered use). Opens a Session,
    runs the batch (register + Konfirmasi Hadir + fill per candidate), logs the tally.
    `target_date` (ISO) → that date's cohort (the cron per-date step); None → bulk."""
    db = SessionLocal()
    try:
        td = date.fromisoformat(target_date) if target_date else None
        result = create_batch(db, uuid.UUID(puskesmas_id), target_date=td, limit=limit)
        log.info("create.run_batch: tally=%s", result.get("tally"))
    finally:
        db.close()


@celery_app.task(name="create.run_cron_batch")
def run_create_cron_batch(cron_run_id: str) -> None:
    """Cron CREATE step: register this (puskesmas, target_date)'s epus_only + tandai_ckg
    patients into ASIK, then fill — SEQUENTIALLY in one ASIK session. Dispatched by
    cron.advance only when the parent config/backfill has create_new set (itself gated on
    sync_mode != OFF, and it runs AFTER the sync step so the account is free). Mirrors
    sync.run_cron_batch: RAISES on a fatal (missing puskesmas/creds) so cron's link_error
    marks the step failed; per-patient failures are recorded and don't stop the batch."""
    from app.models.cron_run import CronRun

    db = SessionLocal()
    try:
        run = db.scalar(
            select(CronRun)
            .options(load_only(CronRun.id, CronRun.puskesmas_id, CronRun.target_date))
            .where(CronRun.id == uuid.UUID(cron_run_id))
        )
        if run is None:
            return
        # limit high enough to cover a single date's whole epus_only cohort.
        result = create_batch(
            db, run.puskesmas_id, target_date=run.target_date, limit=10_000,
            cron_run_id=run.id,
        )
        log.info("create.run_cron_batch: run=%s tally=%s", cron_run_id, result.get("tally"))
    finally:
        db.close()


@celery_app.task(bind=True, name="create.run_one")
def run_create_one(self, job_id: str, headless: bool = True) -> None:
    """Manual single-patient CREATE: register ONE epus_only + tandai_ckg patient into ASIK
    then fill, tracked on the SyncJob the route already created (so it streams to the same
    sync-jobs log/history UI as a normal sync). Mirrors sync.run_sync's entity-loading +
    error handling; the create+fill itself lives in `create_one_patient`, which never raises
    for a normal failure — it records it on the job."""
    db = SessionLocal()
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    chan = _stream_chan(job_id)
    try:
        job = db.scalar(select(SyncJob).where(SyncJob.id == uuid.UUID(job_id)))
        if job is None:
            return
        if job.status == SyncStatus.CANCELLED:
            try:
                redis_client.publish(chan, "__cancelled__")
            except Exception:
                pass
            return

        patient = db.scalar(
            select(Patient)
            .options(load_only(
                Patient.id, Patient.puskesmas_id, Patient.nik, Patient.nama,
                Patient.match_status, Patient.epus_tandai_ckg,
                Patient.scraped_epus_data, Patient.filter_date, Patient.birth_date,
            ))
            .where(Patient.id == job.patient_id)
        )
        if patient is None:
            sync_job_crud.mark_failed(db, job, "patient not found", datetime.now(UTC))
            _publish_terminal(redis_client, chan, "__failed__")
            return
        if not (
            patient.match_status == MatchStatus.EPUS_ONLY
            and patient.epus_tandai_ckg
            and patient.scraped_epus_data is not None
        ):
            sync_job_crud.mark_failed(
                db, job,
                "patient is not an epus_only + tandai_ckg candidate with ePus data",
                datetime.now(UTC),
            )
            _publish_terminal(redis_client, chan, "__failed__")
            return

        puskesmas = db.scalar(
            select(Puskesmas)
            .options(load_only(
                Puskesmas.id, Puskesmas.asik_url, Puskesmas.asik_cred,
                Puskesmas.asik_default_alamat,
            ))
            .where(Puskesmas.id == job.puskesmas_id)
        )
        if puskesmas is None:
            sync_job_crud.mark_failed(db, job, "puskesmas not found", datetime.now(UTC))
            _publish_terminal(redis_client, chan, "__failed__")
            return

        creds = puskesmas_crud.get_cred_decrypted(puskesmas, "asik")
        if creds is None:
            sync_job_crud.mark_failed(db, job, "asik credentials not set", datetime.now(UTC))
            _publish_terminal(redis_client, chan, "__failed__")
            return
        base_url = f"https://{puskesmas.asik_url}" if puskesmas.asik_url else None
        if not base_url:
            sync_job_crud.mark_failed(db, job, "asik_url not set", datetime.now(UTC))
            _publish_terminal(redis_client, chan, "__failed__")
            return

        try:
            epus = patient_crud.decrypt_field(patient, ScrapeKind.EPUS)
        except Exception as exc:
            sync_job_crud.mark_failed(
                db, job, f"scraped_epus_data could not be decrypted: {exc}", datetime.now(UTC)
            )
            _publish_terminal(redis_client, chan, "__failed__")
            return
        if not epus:
            sync_job_crud.mark_failed(db, job, "scraped_epus_data is empty", datetime.now(UTC))
            _publish_terminal(redis_client, chan, "__failed__")
            return

        captcha_solver = _build_captcha_solver(db)
        create_one_patient(
            db,
            job=job,
            patient=patient,
            epus=epus,
            puskesmas=puskesmas,
            base_url=base_url,
            creds=creds,
            captcha_solver=captcha_solver,
            headless=headless,
            redis_client=redis_client,
            cancel_key_str=_sync_cancel_key(job_id),
            celery_task_id=self.request.id or "",
        )
    except Exception as e:
        db.rollback()
        try:
            j = db.scalar(select(SyncJob).where(SyncJob.id == uuid.UUID(job_id)))
            if j is not None:
                db.refresh(j, ["status"])
                if j.status != SyncStatus.CANCELLED:
                    sync_job_crud.mark_failed(db, j, str(e)[:2000], datetime.now(UTC))
        except Exception:
            pass
        _publish_terminal(redis_client, chan, "__failed__")
        raise
    finally:
        db.close()


def _publish_terminal(redis_client: "redis.Redis", chan: str, sentinel: str) -> None:
    try:
        redis_client.publish(chan, sentinel)
    except Exception:
        pass
