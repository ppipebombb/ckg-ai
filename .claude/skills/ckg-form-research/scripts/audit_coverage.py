"""Coverage + drift audit for any <source>_to_asik converter vs the live ASIK
target schema (asik_form_mapping.json).

Source-agnostic: `--source epus` loads `app.services.epus_to_asik.epus_to_asik`
+ `EPUS_BREADCRUMBS` and reads `Patient.scraped_epus_data`. A new source X needs
`app/services/x_to_asik.py` (fn `x_to_asik`, table `X_BREADCRUMBS`) and a
`scraped_x_data` column.

Reports, against the adult/lansia ASIK slice:
  1. Converter form names with no exact canonical paket/audit match (name drift).
  2. <SOURCE>_BREADCRUMBS field labels not present in the canonical form
     (label drift -> breaks paket grouping + ASIK sync-back).
  3. Canonical adult ASIK forms the converter never emits (missing forms).
  4. Per emitted form: covered/total question tally.

Read-only. Updates the per-question `covered_by_<source>` flag in
asik_form_mapping.json only with --write.

Usage:
  backend/.venv/bin/python audit_coverage.py --source epus [--limit 120] [--write]
"""
import argparse
import importlib
import json
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[4] / "backend"
sys.path.insert(0, str(BACKEND))
MAPPING_PATH = BACKEND / "app" / "data" / "asik_form_mapping.json"


def _load_env():
    import os
    env = BACKEND / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()  # CWD-independent: app.config.Settings reads these env vars

from sqlalchemy import select, func          # noqa: E402
from app.database import SessionLocal         # noqa: E402
from app.core.security import decrypt_json    # noqa: E402
from app.models.patient import Patient, MatchStatus  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling import
from _regions import resolve_regions          # noqa: E402

# Pediatric / non-adult-CKG markers — the converter target is the adult+lansia
# slice. Extend if a source covers other klasters.
PED = ('anak', 'balita', 'remaja', 'bayi', 'sekolah', 'kelas', 'prasekolah',
       'pra sekolah', '1-2 tahun', '3-6 tahun', '12-17', '18 bulan', '1- 5',
       '1-9', '10-14', '0-2', '14-', '2-4', 'pengantin laki', 'catin laki',
       'eid', 'malaria', 'talasemia', 'g6pd', 'shk', 'pjb', 'empedu',
       'kuning', 'berat lahir', 'imunisasi rutin', 'imunisasi hpv',
       'perkembangan', 'pertumbuhan', 'frambusia')


def is_ped(s):
    s = (s or '').lower()
    return any(p in s for p in PED)


def load_converter(source):
    mod = importlib.import_module(f"app.services.{source}_to_asik")
    fn = getattr(mod, f"{source}_to_asik")
    crumbs = getattr(mod, f"{source.upper()}_BREADCRUMBS")
    return fn, crumbs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="epus")
    ap.add_argument("--column", default=None, help="defaults to scraped_<source>_data")
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--write", action="store_true", help="write covered_by_<source> back to mapping json")
    ap.add_argument("--region", default=None,
                    help="restrict the emitted-forms sample to one region (epus_url / puskesmas-name substring)")
    args = ap.parse_args()
    source = args.source
    column = args.column or f"scraped_{source}_data"

    convert, crumbs = load_converter(source)
    data_col = getattr(Patient, column)

    mp = json.loads(MAPPING_PATH.read_text())
    forms = mp["forms"]
    canon_by_paket, canon_by_audit = {}, {}
    canon_labels = defaultdict(set)
    for f in forms:
        pk = (f.get('paket_name') or '').strip()
        at = (f.get('audit_form_title') or '').strip()
        if pk and pk not in canon_by_paket:
            canon_by_paket[pk] = f
        if at and at not in canon_by_audit:
            canon_by_audit[at] = f
        for q in f.get('questions') or []:
            lbl = (q.get('label') or '').strip()
            for n in {pk, at}:
                if n and lbl:
                    canon_labels[n].add(lbl)

    db = SessionLocal()
    conds = [Patient.deleted_at.is_(None), Patient.match_status == MatchStatus.MATCHED,
             data_col.isnot(None)]
    if args.region:
        pids = resolve_regions(db, args.source, [args.region])
        if not pids:
            print(f"no region matched {args.region!r}"); sys.exit(2)
        conds.append(Patient.puskesmas_id.in_(pids))
    rows = db.execute(select(data_col).where(*conds)
                      .order_by(func.random()).limit(args.limit)).all()
    emitted = set()
    for (blob,) in rows:
        try:
            for fn in convert(decrypt_json(blob)):
                emitted.add(fn)
        except Exception:
            pass
    db.close()

    fails = 0
    print("=" * 72)
    print(f"1. CONVERTER FORM NAMES vs CANONICAL  (source={source}, n={len(rows)})")
    print("=" * 72)
    for fn in sorted(emitted):
        if fn == 'identitas_pasien' or fn in canon_by_paket or fn in canon_by_audit:
            continue
        ft = set(fn.lower().replace('(', ' ').replace(')', ' ').split())
        best, sc = None, 0
        for cn in canon_by_paket:
            c = len(ft & set(cn.lower().replace('(', ' ').replace(')', ' ').split()))
            if c > sc:
                best, sc = cn, c
        print(f"  [NAME DRIFT] {fn!r}\n        closest: {best!r}")
        fails += 1

    print("\n" + "=" * 72)
    print("2. BREADCRUMB LABEL DRIFT (field label not in canonical form)")
    print("=" * 72)
    for form, fmap in crumbs.items():
        if form == 'identitas_pasien':
            continue
        cset = canon_labels.get(form)
        if not cset:
            print(f"  [FORM NOT IN CANON] {form!r} ({len(fmap)} fields)")
            continue
        for field in fmap:
            if field not in cset:
                print(f"  [LABEL DRIFT] {form!r}\n        field={field[:90]!r}")
                fails += 1

    print("\n" + "=" * 72)
    print("3. CANONICAL ADULT FORMS NOT EMITTED BY CONVERTER")
    print("=" * 72)
    seen = set()
    for f in forms:
        pk = (f.get('paket_name') or '').strip()
        ln, at = f.get('layanan_name') or '', (f.get('audit_form_title') or '').strip()
        if is_ped(pk) or is_ped(ln) or is_ped(at) or pk in seen:
            continue
        seen.add(pk)
        if pk in emitted or at in emitted:
            continue
        src = sum(1 for q in (f.get('questions') or []) if q.get('epus_source'))
        print(f"  [MISSING] {pk!r}  (layanan={ln!r}, in_audit={f.get('in_audit')}, q={f.get('question_count')}, with_src={src})")

    print("\n" + "=" * 72)
    print("4. PER EMITTED FORM: coverage tally")
    print("=" * 72)
    for fn in sorted(emitted):
        if fn == 'identitas_pasien':
            continue
        f = canon_by_paket.get(fn) or canon_by_audit.get(fn)
        if not f:
            continue
        qs = f.get('questions') or []
        cov = sum(1 for q in qs if (q.get('label') or '').strip() in crumbs.get(fn, {}))
        print(f"  {fn[:55]:55} covered {cov}/{len(qs)}")

    print("\n" + "=" * 72)
    print(f"NAME/LABEL DRIFT ISSUES: {fails}  (target = 0 before shipping)")
    if args.write:
        for f in forms:
            pk = (f.get('paket_name') or '').strip()
            fmap = crumbs.get(pk) or crumbs.get((f.get('audit_form_title') or '').strip()) or {}
            for q in f.get('questions') or []:
                q[f"covered_by_{source}"] = (q.get('label') or '').strip() in fmap
        MAPPING_PATH.write_text(json.dumps(mp, ensure_ascii=False, indent=2))
        print(f"wrote covered_by_{source} flags back to {MAPPING_PATH.name}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
