"""Captcha solving for any model — vision self-test + DB-key fallback chain.

The skill's default captcha mode is ``agent``: the orchestrating model reads the
upscaled PNG with its OWN vision. That fails when the running model can't see
images (Kimi, text-only orchestrators). This script lets the agent *prove*
whether it can read images and, if not, switch the scraper to ``llm`` mode using
a vision-capable API key resolved from the DB.

Subcommands
-----------
  selftest                Generate a known-answer vision probe PNG. Read it with
                          your own vision, then run `selftest --check <digits>`.
  selftest --check 1234   Verify your read. Prints VISION_OK (exit 0) or
                          VISION_FAIL (exit 1). The expected answer is stored as
                          a salted hash — reading the meta file can't reveal it,
                          so passing means you genuinely read the pixels.
  resolve                 Preview the captcha vision config the chain picks (no
                          write, key masked). Health-checks each endpoint.
  apply [--config PATH]   Patch a scraper config.json -> captcha_solver to
                          `type:"llm"` with the resolved vision endpoint. Default
                          config: scrapers/asik/config.json. Backs up the prior
                          block to <config>.captcha.bak.
  restore [--config PATH] Put the backed-up captcha_solver block back (or reset to
                          `type:"agent"` if no backup exists).
  (resolve/apply) --no-health-check / --health-timeout <s>   tune the liveness probe.

Resolution chain (vision-safe; each endpoint health-checked, first LIVE wins —
never the general text-only `is_active` config)
  1. is_active_captcha=True        the config explicitly flagged "captcha only"
  2. base_url ~ ocr.juxtalabs.io   your local vision LLM (free, self-hosted)
  3. openai gpt-4o family          paid, reliable (gpt-4o, then gpt-4o-mini, …) —
                                    preferred failover when local OCR is DOWN
  4. free CLOUD vision (24/7)       Gemini / OpenRouter / Groq / GitHub Models —
                                    last resort (e.g. gpt-4o key also unavailable)
A DOWN endpoint is skipped (refused/timeout/5xx). If nothing is usable the script
errors and says what to add. It will NEVER hand a captcha to the general
`is_active` config — that may be a text-only model (e.g. gpt-oss-20b) and fail.

Usage (from repo root):
  backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/captcha_config.py <subcommand>
"""
import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[4] / "backend"
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))


def _load_env():
    env = BACKEND / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

from sqlalchemy import select                    # noqa: E402
from sqlalchemy.orm import load_only             # noqa: E402
from app.database import SessionLocal            # noqa: E402
from app.core.security import decrypt_json       # noqa: E402
from app.models.llm_config import LlmConfig      # noqa: E402

DEFAULT_CONFIG = REPO / "scrapers" / "asik" / "config.json"
_PROBE_DIR = Path(tempfile.gettempdir()) / "ckg_vision_selftest"


# --------------------------------------------------------------------------- #
# Vision self-test                                                            #
# --------------------------------------------------------------------------- #
def _render_probe(code: str, path: Path) -> None:
    """Draw 4 clean, large digits on white. Legible to any real vision model;
    invisible to a blind one (so the only way to pass is to read the pixels)."""
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.load_default(size=110)
    except TypeError:  # very old Pillow without the size kwarg
        font = ImageFont.load_default()

    img = Image.new("RGB", (520, 200), "white")
    draw = ImageDraw.Draw(img)
    # Center the digits with generous spacing.
    x = 40
    for ch in code:
        draw.text((x, 40), ch, fill="black", font=font)
        x += 115
    img.save(path)


def _selftest_generate() -> int:
    _PROBE_DIR.mkdir(parents=True, exist_ok=True)
    code = "".join(secrets.choice("0123456789") for _ in range(4))
    salt = secrets.token_hex(8)
    digest = hashlib.sha256((salt + code).encode()).hexdigest()
    probe = _PROBE_DIR / "probe.png"
    _render_probe(code, probe)
    (_PROBE_DIR / "meta.json").write_text(json.dumps({"salt": salt, "digest": digest}))
    print("VISION SELF-TEST")
    print(f"  Probe image : {probe}")
    print("  Step 1: Read the probe image above with YOUR OWN vision (4 digits).")
    print("  Step 2: Verify your read (do NOT read meta.json — it only holds a hash):")
    print(f"    backend/.venv/bin/python {Path(__file__).name} selftest --check <your-4-digits>")
    return 0


def _selftest_check(answer: str) -> int:
    meta_path = _PROBE_DIR / "meta.json"
    if not meta_path.exists():
        print("VISION_FAIL  (no probe generated — run `selftest` first)")
        return 1
    meta = json.loads(meta_path.read_text())
    guess = "".join(c for c in (answer or "") if c.isdigit())
    ok = hashlib.sha256((meta["salt"] + guess).encode()).hexdigest() == meta["digest"]
    if ok:
        print("VISION_OK  — you can read images. Use captcha `agent` mode (read the")
        print("           handoff PNG yourself; no API key needed).")
        return 0
    print("VISION_FAIL — you did not read the digits. Switch to `llm` mode with a DB")
    print("            vision key:  captcha_config.py apply")
    return 1


# --------------------------------------------------------------------------- #
# DB resolution chain                                                         #
# --------------------------------------------------------------------------- #
def _gpt_rank(model: str) -> tuple[int, str]:
    m = (model or "").lower()
    if m == "gpt-4o":
        return (0, m)
    if "gpt-4o" in m:          # gpt-4o-mini, gpt-4o-2024-…
        return (1, m)
    return (2, m)              # other gpt-4* (turbo, vision)


# Free cloud vision providers (24/7 uptime), recognised by base_url substring.
# The LAST-RESORT tier — tried only after local OCR AND the paid gpt-4o key are
# both unavailable. Add a DB config whose base_url matches one of these and it
# auto-slots in here. (See SKILL.md for the recommended Gemini/OpenRouter rows.)
_FREE_CLOUD = [
    ("generativelanguage.googleapis", "Google Gemini (free cloud, 24/7)"),
    ("openrouter.ai",                 "OpenRouter (free cloud, 24/7)"),
    ("api.groq.com",                  "Groq (free cloud, 24/7)"),
    ("models.github.ai",              "GitHub Models (free cloud, 24/7)"),
    ("models.inference.ai.azure",     "GitHub Models (free cloud, 24/7)"),
]


def _ordered_candidates(rows) -> list[tuple[object, str]]:
    """Vision-safe priority order, deduped by id. The first LIVE one wins (after a
    health check). NEVER includes the general is_active config — it may be a
    text-only model (e.g. gpt-oss-20b) that cannot read a captcha.
        1. captcha-only flag   2. local ocr.juxtalabs.io
        3. paid gpt-4o         4. free cloud (24/7, last resort)
    """
    out: list[tuple[object, str]] = []
    seen: set = set()

    def add(row, tier):
        if row is not None and row.id not in seen:
            seen.add(row.id)
            out.append((row, tier))

    for r in rows:
        if r.is_active_captcha:
            add(r, "captcha-only (is_active_captcha)")
    for r in rows:
        if "ocr.juxtalabs.io" in (r.base_url or ""):
            add(r, "ocr.juxtalabs.io (local, free)")
    gpt = sorted(
        [r for r in rows if r.provider == "openai" and "gpt-4" in (r.model or "")],
        key=lambda r: _gpt_rank(r.model),
    )
    for r in gpt:
        add(r, "gpt-4o (OpenAI, paid)")
    for host, name in _FREE_CLOUD:
        for r in rows:
            if host in (r.base_url or ""):
                add(r, name + " (last resort)")
    return out


def _health_ok(base_url: str, api_key: str, timeout: float) -> bool:
    """True if the endpoint answers at all (any HTTP status < 500). A refused
    connection / timeout / 5xx counts as DOWN — that's the local-OCR-offline case
    we want to fail over from. A 401/404 still means the host is alive."""
    import httpx
    url = f"{(base_url or '').rstrip('/')}/models"
    try:
        r = httpx.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


def _pick(rows, health_check: bool, timeout: float):
    """Probe candidates in priority order; stop at the first usable one.
    Returns (chosen_or_None, chosen_idx, report) where chosen = (row, tier, key)
    and report = list of [tier, label, base_url, status] for display."""
    candidates = _ordered_candidates(rows)
    report: list = []
    chosen = None
    chosen_idx = -1
    for i, (row, tier) in enumerate(candidates):
        if chosen is not None:
            report.append([tier, row.label, row.base_url, "not-probed"])
            continue
        try:
            api_key = decrypt_json(row.api_key_enc)["api_key"]
        except Exception:
            api_key = ""
        if not api_key:
            report.append([tier, row.label, row.base_url, "no-key"])
            continue
        if not health_check:
            report.append([tier, row.label, row.base_url, "unchecked"])
            chosen, chosen_idx = (row, tier, api_key), i
            continue
        ok = _health_ok(row.base_url, api_key, timeout)
        report.append([tier, row.label, row.base_url, "LIVE" if ok else "DOWN"])
        if ok:
            chosen, chosen_idx = (row, tier, api_key), i
    return chosen, chosen_idx, report


def _mask(key: str) -> str:
    if not key:
        return "(empty)"
    return f"{key[:4]}…{key[-4:]}" if len(key) > 8 else "****"


def _print_report(report: list, chosen_idx: int) -> None:
    if not report:
        return
    print("Captcha vision candidates (priority order):")
    for i, (tier, label, base_url, status) in enumerate(report):
        mark = "→" if i == chosen_idx else " "
        print(f"  {mark} [{status:>10}]  {tier}")
        print(f"               {label!r}  @ {base_url}")


def _resolved_solver(db, health_check: bool, timeout: float) -> dict:
    """Resolve + health-check the chain; return a ready captcha_solver dict
    (type=llm). Prints the candidate table. exit(2) if nothing usable."""
    rows = db.scalars(
        select(LlmConfig)
        .options(load_only(
            LlmConfig.id, LlmConfig.provider, LlmConfig.model, LlmConfig.base_url,
            LlmConfig.api_key_enc, LlmConfig.is_active, LlmConfig.is_active_captcha,
            LlmConfig.label,
        ))
        .where(LlmConfig.deleted_at.is_(None))
    ).all()
    chosen, chosen_idx, report = _pick(rows, health_check, timeout)
    _print_report(report, chosen_idx)
    if chosen is None:
        if not report:
            print(
                "\nERROR: no vision-capable captcha config in the DB.\n"
                "  The chain needs one of: a config flagged 'captcha only'\n"
                "  (is_active_captcha), an ocr.juxtalabs.io config, a free-cloud\n"
                "  vision config (Gemini/OpenRouter/Groq/GitHub Models), or a gpt-4o\n"
                "  config. Add one in the LLM Configs UI.\n"
                "  (Deliberately NOT falling back to the general active config — it\n"
                "   may be a text-only model that cannot read a captcha.)",
                file=sys.stderr,
            )
        else:
            print(
                "\nERROR: every vision candidate is DOWN or unusable (see table).\n"
                "  If your local ocr.juxtalabs.io is down, add a free CLOUD vision\n"
                "  config (e.g. Google Gemini) so the chain can fail over 24/7 —\n"
                "  see SKILL.md → 'Solving the ASIK login captcha'. Or re-run with\n"
                "  --no-health-check to force the top config anyway.",
                file=sys.stderr,
            )
        sys.exit(2)
    row, tier, api_key = chosen
    return {
        "_tier": tier,
        "_label": row.label,
        "type": "llm",
        "provider": row.provider,
        "model": row.model,
        "base_url": row.base_url,
        "api_key": api_key,
    }


def _resolve_cmd(health_check: bool, timeout: float) -> int:
    db = SessionLocal()
    try:
        solver = _resolved_solver(db, health_check, timeout)
    finally:
        db.close()
    print(f"\n→ would use: {solver['_label']!r}  [{solver['_tier']}]")
    print(f"  model {solver['model']}  @ {solver['base_url']}  key {_mask(solver['api_key'])}")
    print("\nApply it with:  captcha_config.py apply")
    return 0


# --------------------------------------------------------------------------- #
# config.json patching                                                        #
# --------------------------------------------------------------------------- #
def _apply_cmd(config_path: Path, health_check: bool, timeout: float) -> int:
    if not config_path.exists():
        print(f"ERROR: config not found: {config_path}\n"
              f"  (cp {config_path.parent}/config.example.json {config_path} first)",
              file=sys.stderr)
        return 2
    db = SessionLocal()
    try:
        solver = _resolved_solver(db, health_check, timeout)
    finally:
        db.close()
    tier = solver.pop("_tier")
    label = solver.pop("_label")

    cfg = json.loads(config_path.read_text())
    prev = cfg.get("captcha_solver")
    # Preserve a non-default handoff_timeout if one was set.
    if isinstance(prev, dict) and "handoff_timeout" in prev:
        solver["handoff_timeout"] = prev["handoff_timeout"]
    if prev is not None:
        (config_path.parent / f"{config_path.name}.captcha.bak").write_text(json.dumps(prev))
    cfg["captcha_solver"] = solver
    config_path.write_text(json.dumps(cfg, indent=2))
    print(f"Patched {config_path} -> captcha_solver.type = 'llm'")
    print(f"  using : {label!r}  [{tier}]")
    print(f"  model : {solver['model']}  @ {solver['base_url']}")
    print("  The scraper now auto-solves the captcha via this vision endpoint —")
    print("  no agent handoff needed. Run your scrape as usual.")
    return 0


def _restore_cmd(config_path: Path) -> int:
    if not config_path.exists():
        print(f"ERROR: config not found: {config_path}", file=sys.stderr)
        return 2
    cfg = json.loads(config_path.read_text())
    bak = config_path.parent / f"{config_path.name}.captcha.bak"
    if bak.exists():
        cfg["captcha_solver"] = json.loads(bak.read_text())
        bak.unlink()
        msg = "restored prior captcha_solver block"
    else:
        cfg["captcha_solver"] = {"type": "agent", "handoff_timeout": 240}
        msg = "no backup found — reset to type='agent'"
    config_path.write_text(json.dumps(cfg, indent=2))
    print(f"Patched {config_path} -> {msg}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Captcha vision self-test + DB-key fallback chain.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_self = sub.add_parser("selftest", help="vision self-test (generate, or --check)")
    p_self.add_argument("--check", metavar="DIGITS", default=None,
                        help="verify your read of the probe image")

    for p in (
        sub.add_parser("resolve", help="preview the DB-resolved captcha vision config"),
        (p_apply := sub.add_parser("apply", help="patch a scraper config.json to llm mode")),
    ):
        p.add_argument("--no-health-check", action="store_true",
                       help="skip the per-endpoint liveness probe; take the top config as-is")
        p.add_argument("--health-timeout", type=float, default=5.0,
                       help="liveness probe timeout seconds (default 5)")
    p_apply.add_argument("--config", default=str(DEFAULT_CONFIG))

    p_rest = sub.add_parser("restore", help="restore the prior captcha_solver block")
    p_rest.add_argument("--config", default=str(DEFAULT_CONFIG))

    args = ap.parse_args()
    if args.cmd == "selftest":
        return _selftest_check(args.check) if args.check is not None else _selftest_generate()
    if args.cmd == "resolve":
        return _resolve_cmd(not args.no_health_check, args.health_timeout)
    if args.cmd == "apply":
        return _apply_cmd(Path(args.config), not args.no_health_check, args.health_timeout)
    if args.cmd == "restore":
        return _restore_cmd(Path(args.config))
    return 1


if __name__ == "__main__":
    sys.exit(main())
