"""Detect ASIK (target) drift: diff a fresh live ASIK scrape against the
committed target schema (asik_form_mapping.json).

The captcha-gated live capture is a SEPARATE manual step (keeps this script
deterministic): first run the ASIK scraper with include_blank_forms to dump
TODAY's forms, then point this script at that dump.

Capture step (manual, visible browser, you solve the captcha):
  cd scrapers/asik
  # config.json: include_blank_forms=true, pelayanan_nakes_only=false
  python3 scraper.py --no-headless --tab selesai --date <YYYY-MM-DD> \
      --max-patients 4 --output output/live_today.json

Then:
  backend/.venv/bin/python capture_target.py --dump scrapers/asik/output/live_today.json

Reports forms/questions present live but missing from the mapping (ASIK added
them — new mapping targets) and vice-versa (removed/renamed). A non-empty
"NEW LIVE" list = ASIK drift the converter research must address.
"""
import argparse
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[4] / "backend"
MAPPING_PATH = BACKEND / "app" / "data" / "asik_form_mapping.json"


def _norm(name):
    # Strip the live DOM ordering prefix ("1. ", "6a. ") so names match the
    # mapping. Mirrors build_mapping._norm_audit_title.
    return re.sub(r"^\d+[a-z]?\.\s*", "", (name or "")).strip()


def live_forms(dump):
    """{form_name: set(question_labels)} from a scraper dump with include_blank_forms."""
    out = {}
    for bucket in ("sedang_pemeriksaan", "selesai_pemeriksaan", "belum_pemeriksaan"):
        for pt in dump.get(bucket) or []:
            for arr in ("pemeriksaan_mandiri", "pelayanan_nakes"):
                for e in pt.get(arr) or []:
                    fn = _norm(e.get("layanan"))
                    if not fn:
                        continue
                    fd = e.get("form_data") or {}
                    out.setdefault(fn, set()).update(
                        k.strip() for k in fd.keys() if isinstance(k, str))
    return out


def canon_forms():
    mp = json.loads(MAPPING_PATH.read_text())
    out = {}
    for f in mp["forms"]:
        for name in {(f.get("paket_name") or "").strip(), (f.get("audit_form_title") or "").strip()}:
            if name:
                out.setdefault(name, set()).update(
                    (q.get("label") or "").strip() for q in (f.get("questions") or []))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True, help="ASIK scraper output JSON (include_blank_forms)")
    args = ap.parse_args()
    dump = json.loads(Path(args.dump).read_text())
    live = live_forms(dump)

    # Guard: ASIK --date does NOT fall back to earlier dates. A date with no
    # completed screenings yields an empty/near-empty dump — and an empty dump
    # has NO live forms, so the diff below would FALSELY read as "0 NEW LIVE →
    # clean" (exit 0). Refuse to judge drift on too little data. A real
    # include_blank_forms dump carries dozens of forms even for one patient.
    n_patients = sum(len(dump.get(b) or []) for b in
                     ("sedang_pemeriksaan", "selesai_pemeriksaan", "belum_pemeriksaan"))
    MIN_FORMS = 5
    if n_patients == 0 or len(live) < MIN_FORMS:
        print("=" * 70)
        print(f"⚠  DUMP TOO SMALL TO JUDGE DRIFT — {n_patients} patient(s), "
              f"{len(live)} live form(s) (need ≥ {MIN_FORMS}).")
        print("   ASIK --date has NO auto-fallback to prior dates: an empty/low-volume")
        print("   date would FALSELY read as 'no drift'. Re-scrape a date you KNOW has")
        print("   completed (Selesai) screenings, then re-run:")
        print("     cd scrapers/asik && python3 scraper.py --no-headless --tab selesai \\")
        print("         --date <YYYY-MM-DD> --max-patients 4 --output output/live_today.json")
        print("=" * 70)
        sys.exit(2)

    canon = canon_forms()

    new_forms = sorted(set(live) - set(canon))
    gone_forms = sorted(set(canon) - set(live))

    print("=" * 70)
    print(f"ASIK TARGET DRIFT  (live forms={len(live)}, mapping forms={len(canon)})")
    print("=" * 70)
    print(f"\nNEW LIVE forms not in mapping ({len(new_forms)}) — research these:")
    for f in new_forms:
        print(f"  + {f}  ({len(live[f])} questions)")
    print(f"\nIn mapping but NOT seen live ({len(gone_forms)}) — removed/renamed/not-in-sample:")
    for f in gone_forms[:40]:
        print(f"  - {f}")

    print("\nNEW questions inside shared forms:")
    any_q = False
    for f in sorted(set(live) & set(canon)):
        newq = live[f] - canon[f]
        # ignore trivial/empty
        newq = {q for q in newq if q}
        if newq:
            any_q = True
            print(f"  {f}:")
            for q in sorted(newq)[:8]:
                print(f"      + {q[:80]}")
    if not any_q:
        print("  (none)")

    print("\nNote: a full target rebuild (FRM/PPM codes + demographics) needs the")
    print("Padanan Excel via backend/app/data/build_mapping.py — see references/asik-target.md.")
    sys.exit(1 if (new_forms) else 0)


if __name__ == "__main__":
    main()
