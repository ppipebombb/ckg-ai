#!/usr/bin/env python3
"""screenshot.py — Playwright screenshot helper for the fix agent (PLAN §7).

GLM-5.3-Flash is natively multimodal, so the agent can LOOK at a page while
checking a portal. Investigation aid only — the agent owns the verdict.

Usage:
  python3 loop-agent/screenshot.py <url> <out.png> [--wait 2000]

Logs in first with the puskesmas's credentials (decrypted from the read-only
DB for this run's portal), so authenticated pages work. Read-only: a GET, a
screenshot, nothing else.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
EPUS = REPO / "scrapers" / "epus"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(EPUS))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--wait", type=int, default=2000, help="ms to wait after load")
    args = ap.parse_args()

    os.environ.setdefault("SCRAPER_SESSION_DIR", str((REPO / ".gate_session").resolve()))
    from playwright.sync_api import sync_playwright
    from helpers import launch_persistent_context, login

    portal = os.environ.get("LOOP_PORTAL_URL", "").rstrip("/")
    base = f"https://{portal.replace('https://', '').split('/')[0]}" if portal else ""
    with sync_playwright() as pw:
        ctx = launch_persistent_context(pw, headless=True, slow_mo=0)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            if base and args.url.startswith(base):
                from app.crud import puskesmas as pcrud
                from app.database import SessionLocal
                from app.models.puskesmas import Puskesmas
                from sqlalchemy import select

                host = base.replace("https://", "")
                with SessionLocal() as db:
                    row = db.execute(
                        select(Puskesmas.id).where(Puskesmas.epus_url == host)
                    ).first()
                    creds = pcrud.get_cred_decrypted(db.get(Puskesmas, row[0]), "epus") if row else None
                if creds:
                    login(page, base, creds, headless=True)
            page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(args.wait)
            page.screenshot(path=args.out, full_page=True)
            print(f"[screenshot] wrote {args.out}")
            return 0
        finally:
            ctx.close()


if __name__ == "__main__":
    sys.exit(main())
