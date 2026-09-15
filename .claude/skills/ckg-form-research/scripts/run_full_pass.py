#!/usr/bin/env python3
"""
Deterministic orchestrator for the CKG full research pass.

WHY THIS EXISTS
---------------
The skill's *checking* was already deterministic (the audit/verify scripts), but
*orchestration* — which steps run, in what order, and whether one may be skipped —
was left to the LLM's prose-following. A weak model exploited that seam: it ran the
cheap offline scripts, silently skipped the captcha-gated live-ASIK-drift step, and
reported a clean "no drift" that those scripts could never contradict (they only
validate what DID run). See the war story in SKILL.md.

This runner closes the seam. It OWNS execution: it runs every required step, captures
each one's real output + exit code, and prints a COMPLETENESS MANIFEST and a GATE
verdict. A step that did not run shows as NOT_RUN and forces GATE: INCOMPLETE (exit 2)
— the model cannot bury it. The model's remaining job is the part only it can do:
triage the captured outputs (NEW-vs-KNOWN, candidate gaps) and write the report.

USAGE
-----
  backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/run_full_pass.py \
      --source epus [--verify-n 6] [--models oss] [--asik-dump <path>]

  --asik-dump <path>   ASIK live dump for drift detection (capture_target.py). If
                       omitted, the newest scrapers/<src>/asik output dump is used
                       (with a staleness warning). If none exists, the live-drift
                       step is NOT_RUN -> GATE: INCOMPLETE (honest: you have not
                       verified ASIK drift this run).

EXIT CODES (the gate)
  0  COMPLETE  + no deterministic regression   (findings may still need LLM triage)
  1  COMPLETE  but a MUST-FIX regression fired (audit_regions / verify_converter)
  2  INCOMPLETE: a required step did not validly run (NOT_RUN / infra error / timeout)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parents[3]  # scripts -> ckg-form-research -> skills -> .claude -> repo
ASIK_DIR = REPO / "scrapers" / "asik"
PY = sys.executable  # the venv python we were launched with (has playwright + scraper deps)
MANIFEST_FILE = SCRIPTS.parent / "last_pass_manifest.txt"

# status buckets
OK, MUST_FIX, TRIAGE, INFO, DRIFT, NOT_RUN, ERROR = (
    "RAN/OK", "RAN/MUST-FIX", "RAN/TRIAGE", "RAN/INFO", "RAN/DRIFT", "NOT_RUN", "ERROR")
_RAN = {OK, MUST_FIX, TRIAGE, INFO, DRIFT}  # counts toward completeness


def _run(cmd: list[str], timeout: int, cwd: Path = REPO) -> tuple[int | None, str]:
    """Run a step; return (returncode, combined output). rc=None on timeout/spawn fail."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return None, f"[TIMEOUT after {timeout}s] {' '.join(cmd)}"
    except Exception as e:  # spawn failure, missing file, etc.
        return None, f"[SPAWN ERROR] {e}"


def _classify_offline(name: str, rc: int | None) -> str:
    if rc is None:
        return ERROR
    if name == "audit_regions":
        return {0: OK, 1: MUST_FIX}.get(rc, ERROR)
    if name == "verify_converter":
        return {0: OK, 1: MUST_FIX}.get(rc, ERROR)  # 2 = region/infra -> ERROR
    if name == "audit_coverage":
        return {0: OK, 1: TRIAGE}.get(rc, ERROR)  # 1 = drift present (NEW vs KNOWN)
    if name == "audit_uncovered":
        return INFO if rc == 0 else ERROR
    if name == "audit_source_completeness":
        # 0 clean · 1 real scraper gap (module/section missed) · 3 triage-only · 2 = login/infra
        return {0: OK, 1: MUST_FIX, 3: TRIAGE}.get(rc, ERROR)
    return ERROR


def _newest_dump(source: str) -> Path | None:
    out = ASIK_DIR / "output"
    if not out.is_dir():
        return None
    dumps = sorted(out.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return dumps[0] if dumps else None


def _auto_scrape(asik_python: str, start_date: str | None, lookback: int) -> tuple[Path | None, str]:
    """Branch B: enable a vision captcha key, scrape ASIK headless, walking back dates until
    one has completed (Selesai) screenings. No model vision needed — the scraper auto-solves
    the captcha via the DB vision endpoint. Returns (fresh_dump_path | None, log)."""
    log = ["--- auto-asik: FRESH live scrape (Branch B captcha, headless) ---"]

    # 1) enable auto captcha solving (config captcha_solver -> type:"llm" via DB vision key)
    rc, out = _run([PY, str(SCRIPTS / "captcha_config.py"), "apply"], 120)
    log += [f"[captcha_config apply] exit={rc}", out.rstrip()]
    if rc != 0:
        log.append("auto-asik ABORTED: no usable vision captcha key (add one in the LLM Configs UI, "
                   "then re-run). Live drift NOT verified.")
        return None, "\n".join(log)

    # coverage warning: nakes-only hides self-assessment (mandiri) forms from drift detection
    try:
        import json as _json
        if _json.loads((ASIK_DIR / "config.json").read_text()).get("pelayanan_nakes_only") is not False:
            log.append("note: config.json pelayanan_nakes_only != false — mandiri (self-assessment) "
                       "forms won't be scraped, so drift on those is invisible. Set it false for full coverage.")
    except Exception:
        pass

    # 2) scrape, walking back dates until a date has completed screenings (capture_target accepts it)
    base = date.fromisoformat(start_date) if start_date else date.today()
    for off in range(lookback + 1):
        d = (base - timedelta(days=off)).isoformat()
        out_rel = f"output/auto_pass_{d}.json"
        out_abs = ASIK_DIR / out_rel
        log.append(f"[scrape selesai {d}] -> {out_rel}")
        rc, out = _run([asik_python, "scraper.py", "--tab", "selesai", "--headless",
                        "--use-session", "--max-pages", "1", "--date", d, "--output", out_rel],
                       1500, cwd=ASIK_DIR)
        if rc != 0 or not out_abs.is_file():
            log.append(f"  scrape failed (exit={rc}) or no output — trying earlier date")
            log.append("  " + out.rstrip()[-400:])
            continue
        cap_rc, _ = _run([PY, str(SCRIPTS / "capture_target.py"), "--dump", str(out_abs)], 600)
        if cap_rc == 2:
            log.append(f"  {d}: no completed screenings (dump too small) — trying earlier date")
            continue
        log.append(f"  {d}: usable dump ✓ ({out_abs.name})")
        return out_abs, "\n".join(log)

    log.append(f"auto-asik: no date in the last {lookback + 1} had completed screenings — live "
               "drift NOT verified. Widen --asik-lookback or pass a known-busy --asik-date.")
    return None, "\n".join(log)


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic full research-pass runner.")
    ap.add_argument("--source", default="epus")
    ap.add_argument("--verify-n", type=int, default=6, help="patients/region for verify_converter")
    ap.add_argument("--models", default="oss", help="verify_converter --models")
    ap.add_argument("--asik-dump", default=None, help="explicit ASIK dump for capture_target.py (wins over auto/newest)")
    ap.add_argument("--auto-asik", action="store_true",
                    help="drive a FRESH live ASIK scrape (Branch B captcha, headless) instead of reusing a dump")
    ap.add_argument("--asik-date", default=None, help="--auto-asik: start date (default today)")
    ap.add_argument("--asik-lookback", type=int, default=3,
                    help="--auto-asik: earlier days to try if a date has no completed screenings")
    ap.add_argument("--asik-python", default=PY,
                    help="interpreter for the Playwright scraper (default: this venv — it has playwright)")
    args = ap.parse_args()

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    src = args.source
    results: list[dict] = []  # {step, status, rc, note}
    chunks: list[str] = []

    chunks.append("=" * 78)
    chunks.append("CKG FULL RESEARCH PASS — DETERMINISTIC RUNNER")
    chunks.append(f"source={src}  started={started}  repo={REPO}")
    chunks.append("=" * 78)

    # --- the 5 captcha-free steps: always run, in order -------------------------
    # 4 offline (DB-side converter audits) + 1 LIVE EPUS source-completeness check.
    # The completeness check is live (logs into each region, no captcha) — it audits
    # the SCRAPER vs the live site, the seam the DB-side audits cannot see (jaksel
    # tab miss, 2026-06-05). It runs here because EPUS has no captcha to gate on.
    offline = [
        ("audit_regions", ["audit_regions.py", "--source", src], 900),
        ("verify_converter",
         ["verify_converter.py", "--source", src, "--all-regions",
          "--n", str(args.verify_n), "--models", args.models], 2400),
        ("audit_coverage", ["audit_coverage.py", "--source", src], 900),
        ("audit_uncovered", ["audit_uncovered.py", "--source", src], 900),
        ("audit_source_completeness",
         ["audit_source_completeness.py", "--source", src, "--per-region", "2"], 1500),
    ]
    for i, (name, rel, timeout) in enumerate(offline, 1):
        cmd = [PY, str(SCRIPTS / rel[0]), *rel[1:]]
        rc, out = _run(cmd, timeout)
        status = _classify_offline(name, rc)
        results.append({"step": name, "status": status, "rc": rc, "note": ""})
        chunks.append(f"\n>>> STEP {i}/6  {name}  ({' '.join(rel)})")
        chunks.append(out.rstrip())
        chunks.append(f"[exit={rc} -> {status}]")

    # --- step 6: live ASIK drift (the step a weak model skipped) ----------------
    chunks.append("\n>>> STEP 6/6  live ASIK drift  (capture_target.py)")
    if args.asik_dump:
        dump = Path(args.asik_dump)               # explicit dump wins
    elif args.auto_asik:
        dump, scrape_log = _auto_scrape(args.asik_python, args.asik_date, args.asik_lookback)
        chunks.append(scrape_log)
    else:
        dump = _newest_dump(src)                  # reuse newest existing dump (flag staleness)
    if dump and dump.is_file():
        age_days = (datetime.now().timestamp() - dump.stat().st_mtime) / 86400
        rc, out = _run([PY, str(SCRIPTS / "capture_target.py"), "--dump", str(dump)], 600)
        if rc == 0:
            status, note = OK, f"no new live forms (dump={dump.name}, {age_days:.1f}d old)"
        elif rc == 1:
            status, note = DRIFT, f"NEW LIVE forms found (dump={dump.name}, {age_days:.1f}d old)"
        elif rc == 2:
            status, note = NOT_RUN, f"dump too small to judge drift ({dump.name}) — not a valid check"
        else:
            status, note = ERROR, f"capture_target exit={rc}"
        if status in _RAN and age_days > 8:
            note += "  ** STALE (>8d): re-scrape for a current drift read **"
        chunks.append(out.rstrip())
        chunks.append(f"[exit={rc} -> {status}]  {note}")
    elif args.auto_asik:
        status = NOT_RUN
        note = "auto-asik produced no usable dump (see scrape log above) — drift NOT verified"
        chunks.append(f"[-> {status}]  {note}")
    else:
        status = NOT_RUN
        note = "no ASIK dump available — drift NOT verified this run"
        chunks.append("SKIPPED — no --asik-dump and no dump in scrapers/asik/output/.")
        chunks.append("For a fully autonomous live check, re-run with --auto-asik (it solves the")
        chunks.append("captcha via the DB vision key and scrapes headless). Or supply a dump manually:")
        chunks.append("  1) captcha_config.py apply   2) scrape a date WITH completed (Selesai) screenings")
        chunks.append("  3) re-run with --asik-dump scrapers/asik/output/<dump>.json")
        chunks.append(f"[-> {status}]  {note}")
    results.append({"step": "live_asik_drift", "status": status, "rc": None, "note": note})

    # --- manifest ---------------------------------------------------------------
    chunks.append("\n" + "=" * 78)
    chunks.append("COMPLETENESS MANIFEST")
    chunks.append("=" * 78)
    chunks.append(f"{'step':22} {'status':14} note")
    for r in results:
        chunks.append(f"{r['step']:22} {r['status']:14} {r['note']}")

    must_fix = [r["step"] for r in results if r["status"] == MUST_FIX]
    not_complete = [r["step"] for r in results if r["status"] in (NOT_RUN, ERROR)]
    triage = [r for r in results if r["status"] in (TRIAGE, INFO, DRIFT)]

    chunks.append("\nMUST-FIX (deterministic regressions): "
                  + (", ".join(must_fix) if must_fix else "none"))
    chunks.append("TRIAGE-REQUIRED (LLM judgment — report NEW-only vs RESEARCH_STATUS.md baseline):")
    if triage:
        for r in triage:
            if r["step"] == "audit_source_completeness":
                hint = "NEW live show-section / AJAX read the scraper doesn't capture — decide capture vs redundant, then allowlist or extend the scraper"
            else:
                hint = {TRIAGE: "drift present — classify each label/name as NEW or KNOWN",
                        INFO: "review top uncovered candidates for any NEW high-fill mappable gap",
                        DRIFT: "NEW LIVE ASIK forms — decide map vs shell-vs-skip"}[r["status"]]
            chunks.append(f"  - {r['step']}: {hint}")
    else:
        chunks.append("  - none")

    # --- gate -------------------------------------------------------------------
    if not_complete:
        gate, code = f"INCOMPLETE  (did not validly run: {', '.join(not_complete)})", 2
        verdict = ("This pass is INCOMPLETE. You MUST report it as INCOMPLETE and you MUST NOT "
                   "claim a result for any NOT_RUN step (e.g. do not write 'no ASIK drift' when "
                   "live_asik_drift did not run). Resolve the step, then re-run this runner.")
    elif must_fix:
        gate, code = f"MUST-FIX  (regressions: {', '.join(must_fix)})", 1
        verdict = ("Deterministic regression(s) fired. Fix the converter/schema, restart the "
                   "Celery worker, re-merge affected patients, then re-run this runner to 0.")
    else:
        gate, code = "COMPLETE — 0 MUST-FIX", 0
        verdict = ("Every required step RAN with no deterministic regression. Still TRIAGE the "
                   "items above and report NEW-only findings; update RESEARCH_STATUS.md if anything changed.")

    chunks.append("\n" + "=" * 78)
    chunks.append(f"GATE: {gate}")
    chunks.append("=" * 78)
    chunks.append(verdict)
    chunks.append(f"\nfinished={datetime.now(timezone.utc).isoformat(timespec='seconds')}  exit={code}")
    chunks.append("ECHO THE GATE LINE VERBATIM IN YOUR REPORT. The user reads it to confirm the "
                  "pass was complete and not silently shortcut.")

    # --- one-line at-a-glance summary (for daily/autonomous monitoring) ---------
    _short = {OK: "OK", MUST_FIX: "MUST-FIX", TRIAGE: "DRIFT?", INFO: "INFO",
              DRIFT: "NEW-FORMS", NOT_RUN: "NOT_RUN", ERROR: "ERR"}
    steps_str = " ".join(f"{r['step'].replace('_', '-')}={_short.get(r['status'], r['status'])}"
                         for r in results)
    triage_str = ",".join(r["step"] for r in results if r["status"] in (TRIAGE, INFO, DRIFT)) or "none"
    chunks.append("\n" + "-" * 78)
    chunks.append(f"SUMMARY  gate={gate}")
    chunks.append(f"         steps: {steps_str}")
    chunks.append(f"         must-fix: {', '.join(must_fix) or 'none'}   |   needs-triage: {triage_str}")
    chunks.append("-" * 78)

    report = "\n".join(chunks)
    print(report)
    try:
        MANIFEST_FILE.write_text(report)
    except Exception:
        pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
