"""Enumerate populated SOURCE leaf-fields the converter does NOT consume.

Answers "does the source have values we don't yet map?" — the inverse of
audit_coverage.py (which checks the ASIK target side). For each matched patient
it flattens the decrypted ``scraped_<source>_data`` into ``A > B > C`` leaf
paths, counts how many patients have each non-empty, and flags the ones whose
leaf field-name is not referenced by any ``<SOURCE>_BREADCRUMBS`` value.

Walks BOTH halves of every tab — ``fields`` AND ``tables``. The ``tables`` half
is the editable grids (lab exam/result rows, Resep drug rows, diagnosis rows)
the ``fields`` pass never sees. Walking only ``fields`` is exactly why the
Laboratorium lab results (Microalbuminuria / Trombosit / Hb …) were
scraped-but-unmapped and stayed invisible to this audit until 2026-06-03 — see
SKILL.md "fields are only HALF the data". A lab-style "<name> + Hasil" row is
indexed by its test-name leaf so the result surfaces as ``<tab> > <table> >
<Test>`` (and consumed-detection by leaf still works); any other grid is walked
column-wise.

Consumed-detection is a HEURISTIC (leaf field-name appears somewhere in the
breadcrumb table) — it is meant to SURFACE candidates for a human to judge, not
to be authoritative. Region spelling variants ("Trombosit (PLT)" vs the mapped
"Trombosit") may read as uncovered even when an alias maps them — that's fine,
the variant is worth seeing. Admin/visit/provider/narrative noise is filtered
via NOISE so the candidate list stays signal-heavy.

Read-only. Source-agnostic via --source (loads app.services.<source>_to_asik).

Usage:
  backend/.venv/bin/python audit_uncovered.py --source epus [--n 80] [--all]
"""
import argparse
import importlib
import re
import sys
from collections import defaultdict
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

from sqlalchemy import func, select            # noqa: E402
from app.core.security import decrypt_json     # noqa: E402
from app.database import SessionLocal          # noqa: E402
from app.models.patient import MatchStatus, Patient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling import
from _regions import resolve_regions           # noqa: E402

# Admin / visit / provider / generic head-to-toe nursing narrative that the
# ASIK CKG form does not ask. Tuned for EPUS; extend per source as needed.
NOISE = (
    "> Dokter", "> Perawat", "> Versi", "Pasien Pulang", "Data Kunjungan",
    "Buat Baru Tindakan", "Buat Baru Diagnosa", "Buat Baru Surat", "Register >",
    "Buat Baru Laboratorium", "Lihat Riwayat", "Buat Baru Data Pengkajian", "Surat Keterangan",
    "Nama Faskes", "Nama Ruangan", "Poli", "No. eRM", "No.", "Asuransi", "Cara Bayar",
    "Penjamin", "Kelas", "Instalasi", "Kamar", "ID.", "ID Pendaftaran", "Tanggal ",
    "Tgl", "Dibuat pada", "Diubah pada", "Status Kunjungan", "Jenis Kunjungan",
    "Kesadaran", "> MAP", "Cara Ukur", "Triage", "Detak Jantung",
    "Lainnya > Tipe", "Lainnya > Edukasi", "Lainnya > Terapi", "Lainnya > BMHP",
    "Keadaan Fisik > Pemeriksaan Kepala", "Keadaan Fisik > Pemeriksaan Wajah",
    "Keadaan Fisik > Pemeriksaan Leher", "Keadaan Fisik > Pemeriksaan Dada",
    "Keadaan Fisik > Pemeriksaan Kardiovask", "Keadaan Fisik > Pemeriksaan Abdomen",
    "Keadaan Fisik > Pemeriksaan Ekster", "Keadaan Fisik > Pemeriksaan Genital",
    "Keadaan Fisik > Pemeriksaan Anus", "Keadaan Fisik > Pemeriksaan Hidung",
    "Keadaan Fisik > Pemeriksaan Kuku", "Keadaan Fisik > Pemeriksaan Punggung",
    "Keadaan Fisik > Pemeriksaan Neuro", "Keadaan Fisik > Pemeriksaan Muskulo",
    "Asesmen >", "Prognosa", "No Surat", "No. Sertifikat",
)


def load_breadcrumb_leaves(source):
    """Set of leaf field-names referenced anywhere in <SOURCE>_BREADCRUMBS."""
    mod = importlib.import_module(f"app.services.{source}_to_asik")
    crumbs = getattr(mod, f"{source.upper()}_BREADCRUMBS")
    leaves = set()
    for fmap in crumbs.values():
        for path in fmap.values():
            if not path:
                continue
            for seg in str(path).split(">"):
                seg = _norm_leaf(seg)
                if seg:
                    leaves.add(seg)
    return leaves


def _norm_leaf(s):
    """Normalise a path segment / test-name leaf for consumed-detection: drop
    parenthetical notes (so breadcrumb "Hb (Hemoglobin)" and a scraped
    "Hb (Hemoglobin)" / "Trombosit (PLT)" leaf compare equal) and strip
    surrounding space/dots. Applied to BOTH the breadcrumb side and the
    candidate side so they match symmetrically."""
    return re.sub(r"\([^)]*\)", "", str(s)).strip(" .")


def walk(o, prefix, sink):
    if isinstance(o, dict):
        for k, v in o.items():
            walk(v, f"{prefix} > {k}" if prefix else str(k), sink)
    elif isinstance(o, list):
        for x in o:
            walk(x, prefix, sink)
    elif o not in (None, "", "-", [], {}):
        sink[prefix].append(o)


# Editable-grid `tables` the `fields` pass never sees. A lab-style row
# ({"Pemeriksaan": "<panel> / <Test>", "Hasil": <value>, …}) collapses to one
# leaf keyed by its test name so the result reads "<tab> > <table> > <Test>"
# and lines up with the breadcrumb's test-name segment for consumed-detection.
# Any other grid (Resep, Diagnosa rows) is walked column-wise.
_TABLE_NAME_COLS = ("Pemeriksaan",)
_TABLE_VALUE_COLS = ("Hasil", "Nilai")


def walk_tables(tab, tables, sink):
    if not isinstance(tables, dict):
        return
    for tname, rows in tables.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            name_col = next((c for c in _TABLE_NAME_COLS if row.get(c)), None)
            val_col = next((c for c in _TABLE_VALUE_COLS
                            if row.get(c) not in (None, "")), None)
            if name_col and val_col:
                leaf = str(row[name_col]).split("/")[-1].strip().lstrip("↳").strip()
                if leaf:
                    sink[f"{tab} > {tname} > {leaf}"].append(row[val_col])
            else:
                walk(row, f"{tab} > {tname}", sink)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="epus")
    ap.add_argument("--column", default=None, help="defaults to scraped_<source>_data")
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--all", action="store_true", help="show noise rows too")
    ap.add_argument("--region", default=None,
                    help="restrict the sample to one region (epus_url / puskesmas-name substring) "
                         "— find data the converter misses in THAT region")
    args = ap.parse_args()
    column = args.column or f"scraped_{args.source}_data"
    data_col = getattr(Patient, column)
    consumed_leaves = load_breadcrumb_leaves(args.source)

    db = SessionLocal()
    conds = [Patient.deleted_at.is_(None), Patient.match_status == MatchStatus.MATCHED,
             data_col.isnot(None), Patient.scraped_asik_data.isnot(None)]
    if args.region:
        pids = resolve_regions(db, args.source, [args.region])
        if not pids:
            print(f"no region matched {args.region!r}"); sys.exit(2)
        conds.append(Patient.puskesmas_id.in_(pids))
    rows = db.execute(select(data_col).where(*conds)
                      .order_by(func.random()).limit(args.n)).all()

    fill, sample, n = defaultdict(int), {}, 0
    for (blob,) in rows:
        try:
            raw = decrypt_json(blob)
        except Exception:
            continue
        n += 1
        sink = defaultdict(list)
        for top in ("data_pasien", "penyakit_khusus"):
            walk(raw.get(top) or ({} if top == "data_pasien" else []), top, sink)
        for tab, tv in (raw.get("tabs") or {}).items():
            tv = tv or {}
            walk(tv.get("fields") or {}, "", sink)         # drop tab+fields wrapper
            walk_tables(tab, tv.get("tables") or {}, sink)  # editable-grid tables
        # Klaster & Siklus Hidup screening battery (EPUS CKG forms — a 3rd data
        # class beyond fields+tables, added 2026-06-04). Each done screening
        # carries a getlist `record` (structured items, e.g. ADL's 10 Barthel
        # scores) + an edit-page `detail` ({input_name: value}). Surface both as
        # `skrining_klaster > <key> > <field>` so unmapped screening fields show
        # up here (consumed-detection by leaf still works once breadcrumbs map them).
        for skey, sv in (raw.get("skrining_klaster") or {}).items():
            if not isinstance(sv, dict):
                continue
            walk(sv.get("detail") or {}, f"skrining_klaster > {skey}", sink)
            for rec in (sv.get("records") or [])[:1]:
                walk(rec, f"skrining_klaster > {skey}", sink)
        for path in sink:
            fill[path] += 1
            sample.setdefault(path, sink[path][0])
    db.close()

    def is_consumed(p):
        leaf = _norm_leaf(p.split(" > ")[-1])
        return leaf in consumed_leaves or (p.startswith("penyakit_khusus") and leaf == "ICDX")

    def is_noise(p):
        return any(k in p for k in NOISE)

    uncovered = sorted((p for p in fill if not is_consumed(p)), key=lambda p: -fill[p])
    candidates = [p for p in uncovered if args.all or not is_noise(p)]

    print(f"=== {args.source.upper()} uncovered source fields  ({n} matched patients) ===")
    print(f"populated leaf paths: {len(fill)} | consumed: {sum(1 for p in fill if is_consumed(p))} "
          f"| uncovered: {len(uncovered)} | candidates (noise filtered): "
          f"{sum(1 for p in uncovered if not is_noise(p))}\n")
    print("fill%  path  ::  sample")
    for p in candidates[:90]:
        sv = str(sample[p])[:44].replace("\n", " ")
        print(f"  {round(100*fill[p]/n):3d}%  {p[:74]:74}  {sv!r}")
    print("\nHeuristic: 'consumed' = leaf name present in "
          f"{args.source.upper()}_BREADCRUMBS. Eyeball candidates for a real ASIK target.")


if __name__ == "__main__":
    main()
