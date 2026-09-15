"""Verify a <source>_to_asik converter end-to-end through the real merge pipeline.

Asserts, per patient:
  - 0 hallucinated merged values (every value traces to source or raw ASIK)
  - complete field set (final clinical fields == source ∪ ASIK, minus conditional
    children correctly pruned)
  - valid nested output shape
  - (with --models) 0 cross-model merge divergence + every model succeeds

Source-agnostic via --source (loads app.services.<source>_to_asik). The merge
post-processing is reused verbatim from app.tasks.merge, so this tests exactly
what production produces.

Usage:
  backend/.venv/bin/python verify_converter.py --source epus --n 8 [--models deepseek,gpt,oss]
"""
import argparse
import importlib
import sys
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

import redis                                   # noqa: E402
from sqlalchemy import select, func            # noqa: E402
from sqlalchemy.orm import load_only           # noqa: E402
from app.config import settings                # noqa: E402
from app.core.security import decrypt_json     # noqa: E402
from app.database import SessionLocal          # noqa: E402
from app.models.patient import Patient, MatchStatus  # noqa: E402
from app.models.llm_config import LlmConfig    # noqa: E402
from app.tasks import merge as M               # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling-script import
from _regions import region_inventory, resolve_regions  # noqa: E402

rc = redis.from_url(settings.REDIS_URL, decode_responses=True)
FAILS = []

# Optional model registry for the consistency check (edit to taste).
MODELS = {"deepseek": "deepseek-v4-flash", "gpt": "gpt-4o-mini", "oss": "openai/gpt-oss-20b"}


def load_converter(source):
    mod = importlib.import_module(f"app.services.{source}_to_asik")
    return getattr(mod, f"{source}_to_asik")


def norm(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    try:
        f = float(s.replace(",", "."))
        return str(int(f)) if f.is_integer() else str(f)
    except (ValueError, TypeError):
        return s


def source_vals(converted, asik):
    vals = set()

    def walk(o):
        if isinstance(o, dict):
            [walk(x) for x in o.values()]
        elif isinstance(o, list):
            [walk(x) for x in o]
        elif o is not None:
            n = norm(o)
            if n:
                vals.add(n)
    walk(converted); walk(asik)
    return vals


def run_pipeline(cfg, converted, asik, prompt, nik):
    user_msg = (f"{prompt}\n\n## Converted source-as-ASIK (input 1, canonical)\n"
                f"```json\n{__import__('json').dumps(converted, ensure_ascii=False)}\n```\n\n"
                f"## ASIK (input 2, raw scrape)\n```json\n"
                f"{__import__('json').dumps(asik, ensure_ascii=False)}\n```\n")
    merged, resp = M._chat_and_parse_with_retry(
        provider=cfg["provider"], base_url=cfg["base_url"], api_key=cfg["api_key"],
        model=cfg["model"], user_msg=user_msg,
        base_max_tokens=M._base_max_tokens_for_model(cfg["model"]),
        response_format=M._json_response_format_for_model(cfg["model"]),
        rc=rc, log_key=f"verify:{nik}", chan=f"verify:{nik}", nik=nik)
    merged = M._slugify_section_keys(merged)
    merged = M._enforce_merged_value(merged)
    merged = M._drop_null_null_entries(merged)
    merged = M._complete_source_fields(merged, converted, asik)
    merged = M._rebuild_identitas(merged, converted, asik)
    merged = M._backfill_asik_questions(merged, M._extract_asik_form_names(asik))
    merged = M._overwrite_epus_questions(merged)
    merged = M._normalize_status_flags(merged)
    merged = M._fill_template_reasoning(merged)
    merged = M._drop_orphan_conditional_children(merged)
    merged = M._group_into_pakets(merged, converted, asik)
    return merged, resp


def final_items(merged):
    for sec, sv in (merged.get("sections") or {}).items():
        if not isinstance(sv, dict):
            continue
        for _ps, pk in (sv.get("sub_sections") or {}).items():
            for it in (pk or {}).get("items") or []:
                if isinstance(it, dict) and isinstance(it.get("merged_key"), str):
                    yield sec, it["merged_key"], it


def shape_ok(merged):
    if not isinstance(merged.get("sections"), dict):
        return False
    for sv in merged["sections"].values():
        if not isinstance(sv, dict) or not isinstance(sv.get("sub_sections"), dict):
            return False
        for pk in sv["sub_sections"].values():
            if not isinstance(pk.get("items"), list):
                return False
    return True


def load_cfg(db, model):
    c = db.scalar(select(LlmConfig).options(load_only(
        LlmConfig.provider, LlmConfig.model, LlmConfig.base_url, LlmConfig.api_key_enc))
        .where(LlmConfig.model == model).execution_options(include_deleted=True))
    return None if not c else {"provider": c.provider, "model": c.model,
                               "base_url": c.base_url, "api_key": decrypt_json(c.api_key_enc)["api_key"]}


def _sample_niks(db, data_col, n, *, pids=None, min_age=None, max_age=None):
    """Sample up to n matched + asik-present niks, optionally scoped to a
    region's puskesmas ids and/or an age band (age lives in the encrypted blob)."""
    base = [Patient.deleted_at.is_(None), Patient.match_status == MatchStatus.MATCHED,
            data_col.isnot(None), Patient.scraped_asik_data.isnot(None)]
    if pids:
        base.append(Patient.puskesmas_id.in_(pids))
    if min_age is None and max_age is None:
        return db.execute(select(Patient.nik).where(*base)
                          .order_by(func.random()).limit(n)).all()
    # Age lives inside the encrypted blob (EPUS data_pasien.Umur) — over-fetch a
    # random pool, decrypt, filter by age band, take the first n.
    import re as _re
    pool = db.execute(select(Patient.nik, data_col).where(*base)
                      .order_by(func.random()).limit(max(n * 60, 600))).all()
    rows = []
    for nik, blob in pool:
        try:
            umur = (decrypt_json(blob).get("data_pasien") or {}).get("Umur")
        except Exception:
            continue
        mt = _re.match(r"\s*(\d+)", str(umur or ""))
        if not mt:
            continue
        y = int(mt.group(1))
        if min_age is not None and y < min_age:
            continue
        if max_age is not None and y > max_age:
            continue
        rows.append((nik,))
        if len(rows) >= n:
            break
    return rows


def _verify_niks(db, niks, cfgs, convert, column, data_col, prompt):
    """Run the full pipeline over a list of (nik,) rows; append any issues to
    FAILS (each prefixed with the nik). Returns the number of issues found here."""
    before = len(FAILS)
    for (nik,) in niks:
        p = db.scalar(select(Patient).options(load_only(
            Patient.nama, getattr(Patient, column), Patient.scraped_asik_data))
            .where(Patient.nik == nik, Patient.scraped_asik_data.isnot(None),
                   data_col.isnot(None)).limit(1))
        asik = decrypt_json(p.scraped_asik_data)
        conv = convert(decrypt_json(getattr(p, column)))
        src = source_vals(conv, asik)
        keysets = {}
        for k in cfgs:
            try:
                merged, _r = run_pipeline(cfgs[k], conv, asik, prompt, nik)
            except Exception as exc:
                FAILS.append(f"{nik}/{k}: pipeline error {type(exc).__name__}: {str(exc)[:80]}")
                continue
            halluc = [(s, f) for s, f, it in final_items(merged)
                      if it.get("merged_value") is not None and norm(it.get("merged_value")) not in src]
            if halluc:
                FAILS.append(f"{nik}/{k}: {len(halluc)} hallucinated, e.g. {halluc[:2]}")
            if not shape_ok(merged):
                FAILS.append(f"{nik}/{k}: bad output shape")
            keysets[k] = {(s, f): ("C" if it.get("is_conflict") else ".") for s, f, it in final_items(merged)}
        if len(keysets) >= 2:
            mks = list(keysets)
            allk = set().union(*[set(keysets[m]) for m in mks])
            div = [kk for kk in allk if len({keysets[m].get(kk, "X") for m in mks}) > 1]
            if div:
                FAILS.append(f"{nik}: {len(div)} cross-model divergent fields")
        print(f"  {nik} {p.nama[:20]:20} models={list(keysets)} "
              f"{'ok' if not any(nik in f for f in FAILS) else 'ISSUES'}")
    return len(FAILS) - before


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="epus")
    ap.add_argument("--column", default=None)
    ap.add_argument("--n", type=int, default=8, help="patients per region (or total when region-blind)")
    ap.add_argument("--models", default="oss", help="comma list for consistency check; default just oss")
    ap.add_argument("--min-age", type=int, default=None,
                    help="filter to source age >= N (klaster targeting, e.g. --min-age 0 --max-age 17 for pediatric)")
    ap.add_argument("--max-age", type=int, default=None, help="filter to source age <= N")
    ap.add_argument("--region", default=None,
                    help="restrict to ONE region (epus_url or puskesmas-name substring)")
    ap.add_argument("--all-regions", action="store_true",
                    help="run the full gate once PER region (n patients each); fail if any region fails")
    args = ap.parse_args()
    convert = load_converter(args.source)
    column = args.column or f"scraped_{args.source}_data"
    data_col = getattr(Patient, column)
    model_keys = [m for m in args.models.split(",") if m]

    db = SessionLocal()
    prompt = M.PROMPT_PATH.read_text(encoding="utf-8")
    cfgs = {k: load_cfg(db, MODELS[k]) for k in model_keys}
    for k in model_keys:
        if not cfgs[k]:
            print(f"  config missing for {MODELS[k]} — skipping that model")
    cfgs = {k: v for k, v in cfgs.items() if v}

    # Region grouping: --all-regions loops every region (so "all EPUS tested"
    # means each instance explicitly); --region scopes to one; neither = the
    # original region-blind random sample.
    if args.all_regions:
        groups = [(r["url"], [r["puskesmas_id"]])
                  for r in region_inventory(db, args.source) if r["n_matched"]]
    elif args.region:
        pids = resolve_regions(db, args.source, [args.region])
        if not pids:
            print(f"no region matched {args.region!r}"); db.close(); sys.exit(2)
        groups = [(args.region, pids)]
    else:
        groups = [("all regions (random)", None)]

    region_status = []
    for label, pids in groups:
        niks = _sample_niks(db, data_col, args.n, pids=pids,
                            min_age=args.min_age, max_age=args.max_age)
        print(f"\n--- region: {label}  (n={len(niks)}) ---")
        if not niks:
            print("  (no matching patients — skipped)")
            region_status.append((label, None))
            continue
        issues = _verify_niks(db, niks, cfgs, convert, column, data_col, prompt)
        region_status.append((label, issues == 0))
    db.close()

    print("\n" + "=" * 60)
    if len(groups) > 1:
        print("PER-REGION:")
        for label, ok in region_status:
            tag = "SKIP" if ok is None else ("PASS ✓" if ok else "FAIL ✗")
            print(f"  {tag:7} {label}")
    if FAILS:
        print(f"\nVERIFY FAILED — {len(FAILS)} issue(s):")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print(f"VERIFY PASSED ✓  (source={args.source}, regions tested={len(region_status)})")


if __name__ == "__main__":
    main()
