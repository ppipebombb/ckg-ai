#!/usr/bin/env python3
"""reviewer.py — one-shot LLM review of the agent's fix (PLAN §7).

A plain script, not an agent: one OpenAI-compatible chat-completions call with
the branch diff + a fixed checklist, expecting strict JSON back. The reviewer
model/key come from the loop-reviewer llm_config (injected as LOOP_REVIEWER_*
env by the worker). Writes loop-agent/.review_result.json:

  {"verdict": "approve" | "request_changes" | "error", "comments": ["..."]}

Failures are non-blocking: verdict "error" means the pipeline opens the PR for
human review instead of iterating.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / ".review_result.json"

BASE_REF = os.environ.get("LOOP_BASE_REF", "master")

CHECKLIST = """You are reviewing an automated fix to the CKG ePuskesmas scraper/converter.
The fix was written by an AI agent from a deterministic gap report. Judge ONLY the
diff. Checklist — each item is a possible request_changes reason:

1. REGRESSION RISK: could the change alter behavior for portals/regions that work
   today? Additive changes (new module keys, new parsers, new allowlist entries)
   are safe; changes to existing parsing paths need scrutiny.
2. READ-ONLY DISCIPLINE: the scraper must never write to the portal. Allowed:
   GET requests, the /login POST, and the production scraper's own read-only
   lookups (POST /klaster_siklushidup/{pid}/getlist via its helpers). Flag any
   other POST/PUT/DELETE, any navigation that could trigger the portal's
   on-load writes, any write endpoint added to the fetch set.
3. SCOPE: the diff must only touch scrapers/epus/** and/or
   backend/app/services/epus_to_asik.py (plus the notes file). Anything else ->
   request_changes.
4. NO PATIENT DATA: no patient names, NIKs (16-digit numbers), or record dumps
   may appear in the diff. Field labels and structure are fine.
5. SANITY: no obvious dead code, no secrets/keys, no debugging debris.
6. COMMENT GATE: every added or modified comment must record a DECISION the code
   cannot show (why this approach over the obvious alternative) or a WARNING (a
   constraint that bites later). Flag comments that justify a workaround or
   defend a hack ("NOTE:", "HACK:", "WORKAROUND:", "needed because",
   "acceptable because"), narrate what the code already says, or reference the
   process instead of the code ("per the review", "as the reviewer requested",
   "addresses comment N"). Such a comment means the code is wrong: request
   changes and require the underlying code to be fixed, not the comment reworded.
7. COVERAGE CLAIMS: when the diff adds ASIK question mappings to
   epus_to_asik.py (coverage work), every new breadcrumb must name a real EPUS
   tab/field the run actually captured, and every mapped value must trace to
   scraped source data — an invented or assumed value is a hallucination.
   Flag mappings whose EPUS source is vague ("somewhere in PTM"), whose value
   coercion invents data the source does not show, or whose change is not
   additive (alters behavior for portals that already work).

Respond with STRICT JSON only (no prose outside the JSON):
{"verdict": "approve" | "request_changes",
 "comments": ["one actionable issue per string; empty when approve"]}
"""


def _diff() -> str:
    proc = subprocess.run(
        ["git", "diff", f"{BASE_REF}...HEAD"], capture_output=True, text=True, cwd=str(HERE.parent)
    )
    text = proc.stdout or ""
    if len(text) > 60_000:
        text = text[:60_000] + "\n... (diff truncated)"
    return text


def _call_llm(diff: str) -> dict:
    base = os.environ.get("LOOP_REVIEWER_BASE_URL", "").rstrip("/")
    key = os.environ.get("LOOP_REVIEWER_API_KEY", "")
    model = os.environ.get("LOOP_REVIEWER_MODEL", "")
    if not (base and key and model):
        raise RuntimeError("reviewer llm_config env incomplete (LOOP_REVIEWER_*)")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": CHECKLIST},
            {"role": "user", "content": f"Diff to review:\n\n```diff\n{diff}\n```"},
        ],
        "temperature": 0,
    }
    reasoning = os.environ.get("LOOP_REVIEWER_REASONING", "").strip()
    if reasoning:
        body["reasoning_effort"] = reasoning
    route = (os.environ.get("LOOP_REVIEWER_ROUTE_ORDER")
             or os.environ.get("LOOP_LLM_ROUTE_ORDER") or "").strip()
    if route:
        body["provider"] = {"order": [route], "allow_fallbacks": False}
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read().decode())
    content = data["choices"][0]["message"]["content"]
    # Tolerate fences / prose around the JSON object.
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in reviewer reply: {content[:200]}")
    parsed = json.loads(content[start:end + 1])
    verdict = parsed.get("verdict")
    if verdict not in ("approve", "request_changes"):
        raise ValueError(f"bad verdict: {verdict!r}")
    comments = [str(c) for c in (parsed.get("comments") or [])]
    return {"verdict": verdict, "comments": comments}


def main() -> int:
    diff = _diff()
    if not diff.strip():
        OUT.write_text(json.dumps({"verdict": "error", "comments": ["empty diff — nothing to review"]}))
        print("REVIEW_RESULT:{\"verdict\": \"error\"}")
        return 0
    try:
        result = _call_llm(diff)
    except Exception as e:  # non-blocking by design
        result = {"verdict": "error", "comments": [f"reviewer call failed: {e}"]}
    OUT.write_text(json.dumps(result, ensure_ascii=False))
    # Human-readable lines for the run log (the REVIEW_RESULT line is machine
    # output; format_stream.py drops it in favor of these).
    print(f"[reviewer] verdict: {result['verdict']}")
    for c in result.get("comments") or []:
        print(f"[reviewer] comment: {c}")
    print("REVIEW_RESULT:" + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
