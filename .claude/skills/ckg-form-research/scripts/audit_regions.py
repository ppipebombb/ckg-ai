"""Cross-region audit for a multi-instance source (EPUS = per-region portals).

EPUS is a FAMILY of regional instances (``<region>.epuskesmas.id``), each with
its own login and *potentially its own data shape*. The converter
(``epus_to_asik.py``) was authored against one region — this script proves it
generalises to ALL of them, and flags where it does not.

Per region it reports:
  1. SHAPE — top-level keys + tab names; what is common vs region-specific, and
     whether any converter-critical tab is missing somewhere.
  2. EXTRACTION PARITY — age-controlled (adults by default, so age mix doesn't
     skew it) avg forms + avg filled fields per region, and per-form fill
     divergence across regions.
  3. UNCOVERED LEAVES — high-fill source leaf fields the converter does NOT
     consume, per region (catches data hiding under a region-specific label,
     e.g. jaksel's ``Tempat & Tgl Lahir`` vs the converter's ``Tempat/Tgl Lahir``).

Exits non-zero if a region materially under-extracts (< --min-ratio of the best
region) or is missing a converter-critical tab — so it can gate CI / a run.

Usage:
  backend/.venv/bin/python audit_regions.py --source epus
  backend/.venv/bin/python audit_regions.py --source epus --per-region 60 --min-age 18 --max-age 59
  backend/.venv/bin/python audit_regions.py --source epus --regions jaksel,kotabekasi
"""
import argparse
import importlib
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports
from _regions import (region_inventory, sample_by_region,  # noqa: E402
                      source_age, source_column)
from app.core.security import decrypt_json                  # noqa: E402
from app.database import SessionLocal                        # noqa: E402
from audit_uncovered import NOISE, load_breadcrumb_leaves, walk  # noqa: E402

# Tabs the converter actually reads, per source. A region missing one of these
# (present elsewhere) means the converter is blind to part of that region.
CONVERTER_TABS = {
    "epus": {"PTM", "Anamnesa", "Diagnosa", "PKPR", "Konseling HIV", "TB Paru"},
}


def load_converter(source):
    mod = importlib.import_module(f"app.services.{source}_to_asik")
    return getattr(mod, f"{source}_to_asik")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="epus")
    ap.add_argument("--per-region", type=int, default=40,
                    help="patients to sample per region (after age filter)")
    ap.add_argument("--min-age", type=int, default=18,
                    help="age floor for the parity comparison (default adults 18)")
    ap.add_argument("--max-age", type=int, default=59,
                    help="age ceiling for the parity comparison (default 59)")
    ap.add_argument("--regions", default=None,
                    help="comma list of url/name substrings to restrict to")
    ap.add_argument("--min-ratio", type=float, default=0.80,
                    help="fail a region if its avg filled < this * best region")
    ap.add_argument("--form-delta", type=float, default=2.0,
                    help="flag a form whose avg fill differs by more than this across regions")
    ap.add_argument("--uncovered-top", type=int, default=8,
                    help="how many uncovered leaves to show per region")
    args = ap.parse_args()
    source = args.source
    convert = load_converter(source)
    crumb_leaves = load_breadcrumb_leaves(source)
    regions = [r.strip() for r in args.regions.split(",")] if args.regions else None

    db = SessionLocal()

    # ---- inventory -------------------------------------------------------
    inv = region_inventory(db, source)
    print("=" * 78)
    print(f"REGION INVENTORY  (source={source})")
    print("=" * 78)
    print(f"{'puskesmas':28} {'region url':32} {'rows':>7} {'matched':>8}")
    for r in inv:
        print(f"  {r['name'][:26]:26} {str(r['url']):32} {r['n_rows']:>7} {r['n_matched']:>8}")
    if len([r for r in inv if r["n_rows"]]) < 2:
        print("\nOnly one region with data — cross-region audit is a no-op. Exiting 0.")
        db.close()
        return

    # Over-fetch matched+asik rows, decrypt, age-filter, keep per-region.
    pool = sample_by_region(db, source, per_region=args.per_region,
                            matched_only=True, require_asik=True,
                            regions=regions, overfetch=40)

    shape_tabs = {}        # url -> set(tab names)
    shape_top = {}         # url -> set(top-level keys)
    shape_dp = {}          # url -> set(data_pasien keys) — stable per region, good for rename detection
    region_filled = {}     # url -> avg filled fields (adults)
    region_forms = {}      # url -> avg forms
    region_n = {}          # url -> n sampled (adults)
    formfill = defaultdict(lambda: defaultdict(list))  # url -> form -> [fill]
    uncovered = defaultdict(lambda: defaultdict(int))  # url -> leafpath -> count
    uncov_sample = defaultdict(dict)

    def is_consumed(p):
        leaf = p.split(" > ")[-1]
        return leaf in crumb_leaves or (p.startswith("penyakit_khusus") and leaf == "ICDX")

    def is_noise(p):
        return any(k in p for k in NOISE)

    for url, rows in pool.items():
        filled, forms = [], []
        tabs, top, dpk = Counter(), Counter(), Counter()
        n = 0
        for nik, blob in rows:
            try:
                raw = decrypt_json(blob)
            except Exception:
                continue
            # shape (collect from all rows, pre age-filter, so shape is well-sampled)
            for k in raw.keys():
                top[k] += 1
            for tn in (raw.get("tabs") or {}).keys():
                tabs[tn] += 1
            for k in (raw.get("data_pasien") or {}).keys():
                dpk[k] += 1
            # parity is age-controlled
            y = source_age(source, raw)
            if y is None or y < args.min_age or y > args.max_age:
                continue
            n += 1
            conv = convert(raw)
            forms.append(len(conv))
            tot = 0
            for fn, fields in conv.items():
                c = sum(1 for v in (fields or {}).values() if v is not None)
                tot += c
                formfill[url][fn].append(c)
            filled.append(tot)
            # uncovered leaves
            sink = defaultdict(list)
            for tkey in ("data_pasien", "penyakit_khusus"):
                walk(raw.get(tkey) or ({} if tkey == "data_pasien" else []), tkey, sink)
            for _tab, tv in (raw.get("tabs") or {}).items():
                walk((tv or {}).get("fields") or {}, "", sink)
            for path in sink:
                if not is_consumed(path) and not is_noise(path):
                    uncovered[url][path] += 1
                    uncov_sample[url].setdefault(path, sink[path][0])
            if n >= args.per_region:
                break
        shape_tabs[url] = set(tabs)
        shape_top[url] = set(top)
        shape_dp[url] = set(dpk)
        region_n[url] = n
        region_filled[url] = sum(filled) / n if n else 0.0
        region_forms[url] = sum(forms) / n if n else 0.0

    urls = [u for u in pool if region_n.get(u)]

    # ---- 1. shape diff ---------------------------------------------------
    print("\n" + "=" * 78)
    print("1. SHAPE — tab names per region")
    print("=" * 78)
    common = set.intersection(*[shape_tabs[u] for u in urls])
    union = set.union(*[shape_tabs[u] for u in urls])
    top_common = set.intersection(*[shape_top[u] for u in urls])
    top_union = set.union(*[shape_top[u] for u in urls])
    print(f"top-level keys common to all: {sorted(top_common)}")
    if top_union - top_common:
        print(f"top-level keys that VARY: {sorted(top_union - top_common)}")
    print(f"tabs common to all ({len(common)})")
    print(f"tabs that VARY by region: {sorted(union - common)}")
    for u in urls:
        uniq = shape_tabs[u] - common
        if uniq:
            print(f"   only in {u}: {sorted(uniq)}")

    # data_pasien keys are present in every record (unlike per-patient tabs), so a
    # key that varies by region is a reliable RENAME signal — the usual cause of a
    # region under-extracting identity/demographic fields.
    dp_common = set.intersection(*[shape_dp[u] for u in urls])
    dp_varies = set.union(*[shape_dp[u] for u in urls]) - dp_common
    if dp_varies:
        print(f"\ndata_pasien keys that VARY by region (likely renames — check the converter reads both):")
        for u in urls:
            uniq = shape_dp[u] - dp_common
            if uniq:
                print(f"   only in {u}: {sorted(uniq)}")

    crit = CONVERTER_TABS.get(source, set())
    missing_crit = []  # (url, tab)
    for u in urls:
        for t in crit:
            if t not in shape_tabs[u] and any(t in shape_tabs[o] for o in urls):
                missing_crit.append((u, t))
    print(f"\nconverter-critical tabs ({sorted(crit)}):")
    if missing_crit:
        for u, t in missing_crit:
            print(f"   [MISSING] {t!r} absent in {u} (present in another region) — converter is BLIND to it here")
    else:
        print("   ✓ all present in every region")

    # ---- 2. extraction parity -------------------------------------------
    print("\n" + "=" * 78)
    print(f"2. EXTRACTION PARITY  (ages {args.min_age}-{args.max_age}, n/region shown)")
    print("=" * 78)
    best = max(region_filled.values()) if region_filled else 0.0
    print(f"{'region':32} {'n':>3} {'avg forms':>9} {'avg filled':>11} {'ratio':>7}")
    underfill = []
    for u in urls:
        ratio = region_filled[u] / best if best else 1.0
        flag = "  <-- UNDER" if ratio < args.min_ratio else ""
        if ratio < args.min_ratio:
            underfill.append(u)
        print(f"  {u:30} {region_n[u]:>3} {region_forms[u]:>9.1f} "
              f"{region_filled[u]:>11.1f} {ratio:>6.0%}{flag}")

    print(f"\nforms whose avg fill differs > {args.form_delta} across regions:")
    allforms = set().union(*[set(formfill[u]) for u in urls]) if urls else set()
    flagged = []
    for fn in allforms:
        vals = {u: (sum(formfill[u].get(fn, [])) / len(formfill[u][fn])
                    if formfill[u].get(fn) else 0.0) for u in urls}
        if max(vals.values()) - min(vals.values()) > args.form_delta:
            flagged.append((max(vals.values()) - min(vals.values()), fn, vals))
    for delta, fn, vals in sorted(flagged, reverse=True)[:20]:
        cells = "  ".join(f"{u.split('.')[0]}={vals[u]:.1f}" for u in urls)
        print(f"   Δ{delta:5.1f}  {fn[:36]:36}  {cells}")
    if not flagged:
        print("   (none — converter fills consistently across regions)")

    # ---- 3. uncovered leaves per region ---------------------------------
    print("\n" + "=" * 78)
    print("3. UNCOVERED high-fill source leaves PER REGION (mapping candidates)")
    print("=" * 78)
    for u in urls:
        n = region_n[u]
        top = sorted(uncovered[u].items(), key=lambda kv: -kv[1])[:args.uncovered_top]
        print(f"\n  --- {u} (n={n}) ---")
        for path, c in top:
            sv = str(uncov_sample[u].get(path, ""))[:34].replace("\n", " ")
            print(f"     {round(100*c/n) if n else 0:3d}%  {path[:62]:62}  {sv!r}")

    # ---- verdict ---------------------------------------------------------
    print("\n" + "=" * 78)
    fails = len(underfill) + len(missing_crit)
    if fails:
        print(f"REGION AUDIT: {fails} issue(s) — "
              f"{len(underfill)} under-extracting, {len(missing_crit)} missing-critical-tab")
        print("Investigate the uncovered-leaves list for the under-extracting region(s):")
        print("a renamed key there is the usual cause (add a fallback in the converter).")
        db.close()
        sys.exit(1)
    print(f"REGION AUDIT PASSED ✓  ({len(urls)} regions, all within "
          f"{args.min_ratio:.0%} extraction parity, all critical tabs present)")
    db.close()


if __name__ == "__main__":
    main()
