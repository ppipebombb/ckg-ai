"""Profile a SOURCE's decrypted population BEFORE you decide what's in/out of scope.

Why this exists (read the war story in SKILL.md "Never declare scope from assumption"):
a researcher once asserted "EPUS has no pediatric data, so kids are out of scope" —
WITHOUT checking. The data said otherwise: ~23% of EPUS patients are under 18. But the
*second* layer mattered too: those kids' pediatric tabs (Imunisasi, Tumbuh Kembang Anak)
turned out to be near-empty SHELLS — staff names + dates, no antigen-level / developmental
content. Only the general clinical tabs (Periksa Fisik anthropometry, PTM) carry real data.

Both facts are things you must MEASURE, not guess. This script measures both:
  1. Age-band distribution (how many bayi/balita/anak/remaja/dewasa/lansia).
  2. Per-tab population per band, separating real CLINICAL content from metadata
     (staff names / dates / visit boilerplate) — so a "present" tab that's actually a
     hollow shell is visible at a glance. Counts BOTH halves of a tab — ``fields``
     AND ``tables`` (the editable grids: lab results, Resep, Diagnosa). Counting
     only ``fields`` mislabels a tables-only tab (Laboratorium) as a SHELL — the
     2026-06-03 lab miss. "present" ≠ "populated", and data ≠ only in ``fields``.

Usage:
  backend/.venv/bin/python profile_source.py --source epus
  backend/.venv/bin/python profile_source.py --source epus --sample 2000   # faster
  backend/.venv/bin/python profile_source.py --source epus --band 12-17     # tab detail for one band
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[4] / "backend"
sys.path.insert(0, str(BACKEND))


def _load_env():
    import os
    env = BACKEND / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

from sqlalchemy import select, func            # noqa: E402
from sqlalchemy.orm import load_only           # noqa: E402
from app.database import SessionLocal          # noqa: E402
from app.core.security import decrypt_json     # noqa: E402
from app.models.patient import Patient         # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling import
from _regions import resolve_regions           # noqa: E402

# Metadata leaf-names that are NOT clinical content. A tab whose only non-null leaves
# match these is a hollow shell, not a data source. Substring match, case-insensitive.
_META = (
    "dokter", "perawat", "bidan", "nutrisionist", "sanitarian", "asisten", "tenaga medis",
    "tgl", "tanggal", "status pulang", "lama pelayanan", "rencana kontrol",
    "umur ", "versi", "faskes", "episode of care", "nama kader", "nama dukun",
    "telp", "no. hp", "no hp", "konselor", "observasi", "keterangan", "nasihat",
)

# EPUS-shaped age path. Add a branch here when onboarding a new source whose age
# lives elsewhere (the whole point: don't assume — look at one record first).
def _age_years(source: str, raw: dict):
    if raw is None:
        return None
    if source == "epus":
        from app.services.epus_to_asik import _years_from_umur
        return _years_from_umur((raw.get("data_pasien") or {}).get("Umur"))
    # Fallback: try a few common shapes.
    for path in (("data_pasien", "Umur"), ("data_individu", "Umur"), ("Umur",)):
        cur = raw
        for k in path:
            cur = cur.get(k) if isinstance(cur, dict) else None
        if cur:
            import re
            m = re.match(r"\s*(\d+)", str(cur))
            if m:
                return int(m.group(1))
    return None


def _band(y):
    if y is None:
        return "unknown"
    if y < 1:
        return "<1 (bayi)"
    if y <= 4:
        return "1-4 (balita)"
    if y <= 11:
        return "5-11 (anak)"
    if y <= 17:
        return "12-17 (remaja)"
    if y <= 59:
        return "18-59 (dewasa)"
    return "60+ (lansia)"


_ORDER = ["<1 (bayi)", "1-4 (balita)", "5-11 (anak)", "12-17 (remaja)",
          "18-59 (dewasa)", "60+ (lansia)", "unknown"]


def _is_meta(name: str) -> bool:
    n = name.lower()
    return any(tok in n for tok in _META)


def _clinical_leaves(fields: dict) -> int:
    """Count non-null leaves under a tab's ``fields`` that are real clinical content
    (excludes metadata + the 'Pasien Pulang' boilerplate group)."""
    n = 0
    for grp, gv in (fields or {}).items():
        if grp == "Pasien Pulang":
            continue
        items = gv.items() if isinstance(gv, dict) else []
        for k, v in items:
            if isinstance(v, dict):
                for kk, vv in v.items():
                    if vv not in (None, "", 0, "0") and not _is_meta(kk):
                        n += 1
            elif v not in (None, "", 0, "0") and not _is_meta(k):
                n += 1
    return n


def _clinical_table_leaves(tables: dict) -> int:
    """Count non-null, non-metadata cells in a tab's ``tables`` — the editable
    grids (lab exam/result rows, Resep drug rows, …) the ``fields`` pass never
    sees. WITHOUT this, a tab whose ONLY clinical content lives in ``tables``
    (Laboratorium: results sit in the "Ubah Data Laboratorium" grid, while
    ``fields`` holds just visit boilerplate) is wrongly flagged a SHELL — which
    is exactly why the Laboratorium lab data was missed (see SKILL.md). History
    grids ("Lihat Riwayat …") are skipped: provider/date noise, not this visit's
    data."""
    if not isinstance(tables, dict):
        return 0
    n = 0
    for tname, rows in tables.items():
        if "riwayat" in str(tname).lower() or not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for k, v in row.items():
                if v in (None, "", "-", "- Pilih -", 0, "0") or _is_meta(k):
                    continue
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="epus")
    ap.add_argument("--sample", type=int, default=None,
                    help="Random-sample N records instead of the full population (faster).")
    ap.add_argument("--band", default=None,
                    help="Show per-tab clinical-content detail for one band, e.g. '12-17'.")
    ap.add_argument("--region", default=None,
                    help="restrict the profile to one region (epus_url / puskesmas-name substring)")
    args = ap.parse_args()
    col = getattr(Patient, f"scraped_{args.source}_data")

    db = SessionLocal()
    q = select(Patient).options(load_only(Patient.nik, col)).where(col.isnot(None))
    if args.region:
        pids = resolve_regions(db, args.source, [args.region])
        if not pids:
            print(f"no region matched {args.region!r}"); sys.exit(2)
        q = q.where(Patient.puskesmas_id.in_(pids))
    if args.sample:
        q = q.order_by(func.random()).limit(args.sample)
    rows = db.execute(q).scalars().all()

    rows_by = Counter()
    niks_by = defaultdict(set)
    # band -> tab -> [present_count, clinical_content_count, sum_clinical_leaves]
    tabstat = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    for p in rows:
        try:
            raw = decrypt_json(getattr(p, f"scraped_{args.source}_data"))
        except Exception:
            raw = None
        b = _band(_age_years(args.source, raw))
        rows_by[b] += 1
        niks_by[b].add(p.nik)
        for tn, tv in ((raw or {}).get("tabs") or {}).items():
            if not isinstance(tv, dict):
                continue
            # Count BOTH halves — fields AND tables. A tables-only tab
            # (Laboratorium) would otherwise read as a hollow shell.
            cl = _clinical_leaves(tv.get("fields")) + _clinical_table_leaves(tv.get("tables"))
            st = tabstat[b][tn]
            st[0] += 1
            if cl > 0:
                st[1] += 1
                st[2] += cl
    db.close()

    total = sum(rows_by.values())
    print(f"=== SOURCE PROFILE: {args.source}  (rows={total}, "
          f"unique NIK={len({n for s in niks_by.values() for n in s})}) ===\n")
    print(f"{'age band':<16} {'rows':>7} {'uniq NIK':>9} {'%':>6}")
    for b in _ORDER:
        if rows_by[b]:
            print(f"{b:<16} {rows_by[b]:>7} {len(niks_by[b]):>9} {100*rows_by[b]/total:>5.1f}%")
    u18 = sum(rows_by[b] for b in _ORDER[:4])
    print(f"\n  under-18: {u18} rows ({100*u18/total:.1f}%) — "
          f"{'NOT negligible — profile before scoping' if u18 else 'none'}")

    bands = [args.band] if args.band else _ORDER[:4]  # default: the under-18 bands
    for b in bands:
        b = next((x for x in _ORDER if x.startswith(b)), b)
        if not rows_by.get(b):
            continue
        n = rows_by[b]
        print(f"\n--- tabs for band {b} (n={n}) — present% | has-clinical% | avg clinical leaves ---")
        items = sorted(tabstat[b].items(), key=lambda kv: -kv[1][1])
        for tn, (pres, hascl, sumcl) in items:
            tag = "  <-- SHELL (metadata only)" if pres and hascl == 0 else ""
            avg = (sumcl / hascl) if hascl else 0
            print(f"   {tn:<28} {100*pres/n:>4.0f}%  {100*hascl/n:>4.0f}%  {avg:>5.1f}{tag}")


if __name__ == "__main__":
    main()
