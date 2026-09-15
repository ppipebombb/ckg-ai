"""One-time enrichment: add the CKG (Cek Kesehatan Gratis) field to existing
scraped_epus_data blobs WITHOUT a full re-scrape.

Existing EPUS records were scraped before the CKG feature, so their blobs
have no `ckg` key. A full re-scrape would re-fetch ~32 tabs per patient
(expensive). CKG only needs two light requests per patient:

  1. GET  /pelayanan/show/{pelayanan_id}   (raw HTML, no JS — same as scraper)
  2. POST /pelayanan/getdatapkg            (the CKG XHR the page fires)

This script logs into each puskesmas's EPUS portal once (reusing the
scraper's `helpers.auth.login` — EPUS has no CAPTCHA), then for every live
patient row with an EPUS blob it fetches CKG via `patient_scraper._fetch_ckg`
(year-scoped to the visit), patches `blob["ckg"]`, re-encrypts, and updates
the row.

Idempotent + resumable: rows that already carry a `ckg` key are skipped
unless --force. Re-running after an interruption picks up where it left off.

Read-only against EPUS (login + GET show + getdatapkg POST, which is a read).

Run it inside the backend/worker container (has Playwright + chromium + DB):

  # on the VPS, in tmux so it survives disconnects:
  tmux new -s ckg
  docker exec -it ckg-ai-celery_worker-1 \
      python -m scripts.backfill_ckg --dry-run --puskesmas <UUID>
  docker exec -it ckg-ai-celery_worker-1 \
      python -m scripts.backfill_ckg --puskesmas <UUID>

  # all puskesmas:
  docker exec -it ckg-ai-celery_worker-1 python -m scripts.backfill_ckg

Progress prints to stdout every batch (processed / ya / tidak / errors).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, load_only

from app.config import settings
from app.core.security import decrypt_json, encrypt_json
from app.database import SessionLocal
from app.models.patient import Patient
from app.models.puskesmas import Puskesmas

log = logging.getLogger("backfill_ckg")


def _resolve_scrapers_root() -> Path:
    if settings.SCRAPERS_ROOT:
        return Path(settings.SCRAPERS_ROOT)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "scrapers"
        if (candidate / "asik").is_dir() and (candidate / "epus").is_dir():
            return candidate
    return here.parents[2] / "scrapers"


# Make the EPUS scraper importable, then pull in login + the CKG fetcher.
_EPUS_DIR = _resolve_scrapers_root() / "epus"
sys.path.insert(0, str(_EPUS_DIR))
os.environ.setdefault("SCRAPER_SCREENSHOT_DIR", "/tmp/ckg_backfill_shots")
Path(os.environ["SCRAPER_SCREENSHOT_DIR"]).mkdir(parents=True, exist_ok=True)

from helpers.auth import login  # noqa: E402
from patient_scraper import (  # noqa: E402
    _USER_AGENT,
    _cookie_header_from_context,
    _fetch_ckg,
    _get_http_client,
)
from playwright.sync_api import sync_playwright  # noqa: E402


def _puskesmas_creds(db: Session, pid: uuid.UUID) -> tuple[str, dict] | None:
    p = db.scalar(
        select(Puskesmas)
        .options(load_only(Puskesmas.id, Puskesmas.name, Puskesmas.epus_url, Puskesmas.epus_cred))
        .where(Puskesmas.id == pid)
    )
    if p is None or not p.epus_url or not p.epus_cred:
        return None
    try:
        cred = decrypt_json(p.epus_cred)
    except Exception:
        log.error("puskesmas %s: epus_cred unreadable", pid)
        return None
    base_url = p.epus_url if p.epus_url.startswith("http") else f"https://{p.epus_url}"
    return base_url, {
        "email": cred.get("email", ""),
        "password": cred.get("password", ""),
    }


def _target_puskesmas(db: Session, only: uuid.UUID | None) -> list[uuid.UUID]:
    stmt = (
        select(Patient.puskesmas_id)
        .where(Patient.scraped_epus_data.isnot(None), Patient.deleted_at.is_(None))
        .group_by(Patient.puskesmas_id)
    )
    if only is not None:
        stmt = stmt.where(Patient.puskesmas_id == only)
    return list(db.scalars(stmt))


def _row_ids_for(
    db: Session, pid: uuid.UUID, limit: int
) -> list[uuid.UUID]:
    stmt = (
        select(Patient.id)
        .where(
            Patient.puskesmas_id == pid,
            Patient.scraped_epus_data.isnot(None),
            Patient.deleted_at.is_(None),
        )
        .order_by(Patient.id)
    )
    if limit:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt))


def _process_puskesmas(
    db: Session,
    pid: uuid.UUID,
    *,
    dry_run: bool,
    force: bool,
    workers: int,
    batch_size: int,
    limit: int,
) -> None:
    info = _puskesmas_creds(db, pid)
    if info is None:
        log.warning("puskesmas %s: no usable EPUS creds, skipping", pid)
        return
    base_url, credentials = info
    if not credentials["email"] or not credentials["password"]:
        log.warning("puskesmas %s: empty EPUS email/password, skipping", pid)
        return

    row_ids = _row_ids_for(db, pid, limit)
    log.info("puskesmas %s: %d candidate rows (base=%s)", pid, len(row_ids), base_url)
    if not row_ids:
        return

    from concurrent.futures import ThreadPoolExecutor

    # CKG result cache keyed by pelayanan_id — cross-date twins share one
    # pelayanan_id, so we never fetch the same visit twice.
    ckg_cache: dict[str, dict] = {}

    totals = {"processed": 0, "ya": 0, "tidak": 0, "skipped": 0, "errors": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        page = context.new_page()
        page.set_default_timeout(60000)
        try:
            login(page, base_url, credentials, headless=True)
        except Exception as exc:
            log.error("puskesmas %s: login failed: %s", pid, exc)
            browser.close()
            return
        cookie_header = _cookie_header_from_context(context)

        def fetch_ckg_for(pelayanan_id: str) -> dict:
            if pelayanan_id in ckg_cache:
                return ckg_cache[pelayanan_id]
            show_url = f"{base_url}/pelayanan/show/{pelayanan_id}"
            try:
                r = _get_http_client().get(
                    show_url, headers={"Cookie": cookie_header, "User-Agent": _USER_AGENT}
                )
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}")
                ckg = _fetch_ckg(
                    r.text,
                    base_url=base_url,
                    cookie_header=cookie_header,
                    user_agent=_USER_AGENT,
                    referer=show_url,
                )
            except Exception as exc:
                raise RuntimeError(str(exc)) from exc
            ckg_cache[pelayanan_id] = ckg
            return ckg

        for start in range(0, len(row_ids), batch_size):
            batch = row_ids[start : start + batch_size]
            rows = db.scalars(
                select(Patient)
                .options(load_only(
                    Patient.id, Patient.scraped_epus_data, Patient.filter_date,
                ))
                .where(Patient.id.in_(batch), Patient.deleted_at.is_(None))
            ).all()

            # Decrypt + decide which rows need work.
            work: list[tuple[Patient, dict, str]] = []  # (row, blob, pelayanan_id)
            for row in rows:
                try:
                    blob = decrypt_json(row.scraped_epus_data)
                except Exception:
                    totals["errors"] += 1
                    continue
                if not force and isinstance(blob.get("ckg"), dict):
                    totals["skipped"] += 1
                    continue
                pelayanan_id = str(blob.get("pelayanan_id") or "").strip()
                if not pelayanan_id:
                    totals["errors"] += 1
                    continue
                work.append((row, blob, pelayanan_id))

            # Fetch CKG concurrently (dedup by pelayanan_id).
            unique_pids = list({pid_ for _, _, pid_ in work})
            results: dict[str, dict | None] = {}
            if unique_pids:
                with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                    futs = {pool.submit(fetch_ckg_for, q): q for q in unique_pids}
                    for fut in futs:
                        q = futs[fut]
                        try:
                            results[q] = fut.result()
                        except Exception as exc:
                            results[q] = None
                            log.debug("ckg fetch failed pelayanan=%s: %s", q, exc)

            # Patch + persist.
            for row, blob, pelayanan_id in work:
                ckg = results.get(pelayanan_id)
                if ckg is None:
                    totals["errors"] += 1
                    continue
                blob["ckg"] = ckg
                totals["ya" if ckg.get("sudah_ckg") else "tidak"] += 1
                totals["processed"] += 1
                if not dry_run:
                    db.execute(
                        update(Patient)
                        .where(Patient.id == row.id, Patient.deleted_at.is_(None))
                        .values(scraped_epus_data=encrypt_json(blob), updated_at=func.now())
                    )
            if not dry_run:
                db.commit()
            log.info(
                "puskesmas %s: %d/%d rows | ya=%d tidak=%d skipped=%d errors=%d%s",
                pid, min(start + batch_size, len(row_ids)), len(row_ids),
                totals["ya"], totals["tidak"], totals["skipped"], totals["errors"],
                " [DRY-RUN]" if dry_run else "",
            )

        browser.close()

    log.info(
        "puskesmas %s DONE: processed=%d ya=%d tidak=%d skipped=%d errors=%d%s",
        pid, totals["processed"], totals["ya"], totals["tidak"],
        totals["skipped"], totals["errors"], " [DRY-RUN]" if dry_run else "",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Fetch + report, write nothing.")
    parser.add_argument("--puskesmas", type=str, default=None, help="Restrict to one puskesmas UUID.")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if a ckg key already exists.")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent EPUS fetches (default 8).")
    parser.add_argument("--batch-size", type=int, default=200, help="Rows per DB commit batch (default 200).")
    parser.add_argument("--limit", type=int, default=0, help="Cap rows per puskesmas (0 = all). For testing.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    only = uuid.UUID(args.puskesmas) if args.puskesmas else None

    db: Session = SessionLocal()
    try:
        targets = _target_puskesmas(db, only)
        log.info("targeting %d puskesmas", len(targets))
        for pid in targets:
            _process_puskesmas(
                db, pid,
                dry_run=args.dry_run,
                force=args.force,
                workers=args.workers,
                batch_size=args.batch_size,
                limit=args.limit,
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
