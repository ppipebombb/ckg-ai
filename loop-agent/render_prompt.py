#!/usr/bin/env python3
"""Render loop-agent/PROMPT.md for ONE run by substituting the placeholders.

Placeholders per run:
  {name}       the puskesmas name         (env LOOP_PUSKESMAS_NAME)
  {region_url} the portal URL             (env LOOP_PORTAL_URL)
  {region}     the portal slug for branch names (derived: poso.epuskesmas.id -> poso)
  {detail_n}   how many patients to deep-check on BOTH sides (env LOOP_DETAIL_LIMIT, default 5)
  {max_fix}    fix-pass ceiling the prompt tells the agent (env LOOP_MAX_FIX_ITERS, default 5)

Prints the rendered prompt to stdout.
"""
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _slug(portal_url: str) -> str:
    host = re.sub(r"^https?://", "", portal_url).strip("/")
    return host.split(".")[0] if host else "region"


def main() -> None:
    template = (HERE / "PROMPT.md").read_text()
    name = os.environ.get("LOOP_PUSKESMAS_NAME", "").strip()
    region_url = os.environ.get("LOOP_PORTAL_URL", "").strip()
    region = _slug(region_url)
    detail_n = os.environ.get("LOOP_DETAIL_LIMIT", "").strip() or "5"
    max_fix = os.environ.get("LOOP_MAX_FIX_ITERS", "").strip() or "5"
    rendered = (
        template
        .replace("{name}", name)
        .replace("{region_url}", region_url)
        .replace("{region}", region)
        .replace("{detail_n}", detail_n)
        .replace("{max_fix}", max_fix)
    )
    print(rendered)


if __name__ == "__main__":
    main()
