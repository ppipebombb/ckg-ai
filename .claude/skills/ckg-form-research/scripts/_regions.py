"""Shared region helpers for the per-source verification scripts.

EPUS is not one portal — it is a FAMILY of per-region instances, each on its
own URL (``<region>.epuskesmas.id``) with its own login, and *the raw data
shape can differ between them* (e.g. jaksel renames ``Tempat/Tgl Lahir`` to
``Tempat & Tgl Lahir``). A random sample is region-blind and gets dominated by
the busiest region, so a quirk in a smaller region slips through.

This module gives every script the same region-aware sampling so "test all
EPUS" means *every region explicitly*, not "whatever random happened to pull".

Region identity = ``puskesmas.<source>_url`` (the per-region base URL). Patients
link to a puskesmas via ``Patient.puskesmas_id``.

Importable by sibling scripts: when a script is run as
``python <skill>/scripts/foo.py`` its own dir is on ``sys.path[0]``, so
``from _regions import ...`` resolves. This module sets up the backend import
path + ``.env`` itself, so import order does not matter.
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[4] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_env():
    """Load backend/.env into os.environ (setdefault → never clobbers a real
    env var). CWD-independent, same loader the other scripts use."""
    env = BACKEND / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

from sqlalchemy import func, select          # noqa: E402
from sqlalchemy.orm import load_only          # noqa: E402
from app.models.patient import MatchStatus, Patient  # noqa: E402
from app.models.puskesmas import Puskesmas     # noqa: E402


def source_column(source):
    """The ``Patient.scraped_<source>_data`` column object."""
    return getattr(Patient, f"scraped_{source}_data")


def _url_of(p, source):
    """Per-region base URL for a puskesmas, or its name if the source has no
    ``<source>_url`` column (single-instance source)."""
    return getattr(p, f"{source}_url", None) or p.name


def region_inventory(db, source="epus"):
    """Regions that have data for this source, busiest first.

    Returns ``[{puskesmas_id, name, url, n_rows, n_matched}, ...]``. Counts
    respect the soft-delete auto-filter (deleted patients excluded).
    """
    pus = db.execute(select(Puskesmas)).scalars().all()
    info = {p.id: (p.name, _url_of(p, source)) for p in pus}

    col = source_column(source)
    rows = db.execute(
        select(Patient.puskesmas_id, Patient.match_status, func.count())
        .where(col.isnot(None))
        .group_by(Patient.puskesmas_id, Patient.match_status)
    ).all()
    agg = {}
    for pid, ms, c in rows:
        a = agg.setdefault(pid, {"n_rows": 0, "n_matched": 0})
        a["n_rows"] += c
        if ms == MatchStatus.MATCHED:
            a["n_matched"] += c

    out = []
    for pid, a in agg.items():
        name, url = info.get(pid, ("?", None))
        out.append({"puskesmas_id": pid, "name": name, "url": url, **a})
    out.sort(key=lambda r: -r["n_rows"])
    return out


def resolve_regions(db, source, needles):
    """Map user-supplied region tokens (url or name substrings, case-insensitive)
    to puskesmas_ids. Unknown tokens are ignored — caller can diff against the
    inventory to warn."""
    inv = region_inventory(db, source)
    pids = []
    for n in needles:
        nl = str(n).lower()
        for r in inv:
            if nl in str(r["url"]).lower() or nl in str(r["name"]).lower():
                if r["puskesmas_id"] not in pids:
                    pids.append(r["puskesmas_id"])
    return pids


def sample_by_region(db, source="epus", per_region=40, *, matched_only=True,
                     require_asik=False, regions=None, overfetch=1):
    """Stratified sample: ``{url: [(nik, blob), ...]}`` with up to
    ``per_region * overfetch`` random rows per region.

    - ``matched_only`` — only ``MatchStatus.MATCHED`` patients.
    - ``require_asik`` — also require ``scraped_asik_data`` (merge/verify needs both).
    - ``regions`` — restrict to these url/name substrings (None = all regions).
    - ``overfetch`` — pull extra so the caller can decrypt + age-filter then trim.
    """
    col = source_column(source)
    inv = region_inventory(db, source)
    if regions:
        wanted = set(resolve_regions(db, source, regions))
        inv = [r for r in inv if r["puskesmas_id"] in wanted]

    out = {}
    for r in inv:
        if not r["n_rows"]:
            continue
        conds = [Patient.puskesmas_id == r["puskesmas_id"], col.isnot(None)]
        if matched_only:
            conds.append(Patient.match_status == MatchStatus.MATCHED)
        if require_asik:
            conds.append(Patient.scraped_asik_data.isnot(None))
        rows = db.execute(
            select(Patient.nik, col).where(*conds)
            .order_by(func.random()).limit(per_region * overfetch)
        ).all()
        out[r["url"]] = rows
    return out


def source_age(source, raw):
    """Best-effort age in years from a decrypted source record. EPUS keeps it in
    ``data_pasien.Umur``; falls back to a few common shapes for other sources."""
    if not raw:
        return None
    if source == "epus":
        from app.services.epus_to_asik import _years_from_umur
        return _years_from_umur((raw.get("data_pasien") or {}).get("Umur"))
    import re
    for path in (("data_pasien", "Umur"), ("data_individu", "Umur"), ("Umur",)):
        cur = raw
        for k in path:
            cur = cur.get(k) if isinstance(cur, dict) else None
        if cur:
            m = re.match(r"\s*(\d+)", str(cur))
            if m:
                return int(m.group(1))
    return None
