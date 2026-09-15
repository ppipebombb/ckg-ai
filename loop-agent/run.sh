#!/usr/bin/env bash
# Entrypoint for ONE loop-agent run inside the throwaway container.
#
# run.sh owns the SCAFFOLDING; the agent owns the VERDICT:
#
#   prepare workspace
#     -> ONE OpenCode session (PROMPT.md: log in to the live portal, capture
#        what it serves, run the real scraper, compare, judge; on a gap, fix
#        and re-prove inside the same session)
#     -> reviewer (GLM-5.3) on the diff
#     -> push branch + PR (or the patch into the log)
#     -> LOOP_RESULT (the worker parses it into the dashboard)
#
# The agent writes loop-agent/.check_result.json (verdict + evidence). This
# script never judges coverage — it only wraps that verdict into LOOP_RESULT.
# stdout is captured by the worker: every line streams to the dashboard.
set -uo pipefail

echo "[loop] preparing workspace for run ${LOOP_RUN_ID:-?} — ${LOOP_PUSKESMAS_NAME:-?} (${LOOP_PORTAL_URL:-?})"

# 1. Writable checkout from the read-only seed. `git clone` (not cp) so we get a
#    real .git for the pin checkout + branch + PR.
# The container runs as root; a bind-mounted /seed can be owned by a different
# UID on the host (e.g. Docker Desktop on Windows/WSL2), which trips git's
# safe.directory ownership check and blocks even a local clone. The flagged
# path resolves to /seed/.git (not /seed) and safe.directory is an exact-string
# match, so use the wildcard — this container is throwaway and only ever
# touches our own mounted repo and its own clone.
git config --global --add safe.directory '*'
git clone --quiet /seed /work || { echo "[loop] git clone failed"; exit 1; }
cd /work || exit 1

# 2. Pin checkout — acceptance tests can pin the pre-fix state. The pin
#    rewinds the SCRAPER/CONVERTER under review; the agent then has to find
#    and close the gap live.
if [ -n "${LOOP_PIN_REF:-}" ]; then
  echo "[loop] pinning pipeline to ${LOOP_PIN_REF}"
  git checkout --quiet "${LOOP_PIN_REF}" || { echo "[loop] pin checkout failed: ${LOOP_PIN_REF}"; exit 1; }
fi

# 2a. Overlay the CURRENT working-tree tooling from the read-only seed. The
#     clone only has COMMITTED code, and a pin like 10db694^ predates
#     loop-agent/ + the skills — so overlay them from /seed so the runner
#     always executes the latest prompt + tooling EVEN WHEN UNCOMMITTED. The
#     scraper/converter under review is left at the pinned state, NOT overlaid.
cp -rf /seed/loop-agent /work/ 2>/dev/null || true
cp -rf /seed/.claude /work/ 2>/dev/null || true
mkdir -p /work/backend/app/services /work/backend/app/data
cp -f /seed/backend/app/services/coverage_hunt.py /work/backend/app/services/ 2>/dev/null || true
cp -f /seed/backend/app/data/coverage_ledger.json /work/backend/app/data/ 2>/dev/null || true
# Snapshot the notes so the PR can show only what THIS run added, not the
# whole accumulated file.
cp loop-agent/LOOP_NOTES.md /tmp/notes_at_start.md 2>/dev/null || true

# 2b. Shim `backend/.venv/bin/python` -> system python. The clone has no .venv
#     (gitignored), and the base image installs the backend deps to the system
#     python, so the skill scripts' documented invocation works as written.
mkdir -p /work/backend/.venv/bin
ln -sf "$(command -v python)" /work/backend/.venv/bin/python

# 3. Git identity + optional authenticated remote for push + PR.
git config user.email "loop-agent@ckg.local"
git config user.name "CKG Loop Agent"
if [ -n "${LOOP_GITHUB_TOKEN:-}" ] && [ -n "${LOOP_GITHUB_REPO:-}" ]; then
  git remote set-url origin "https://x-access-token:${LOOP_GITHUB_TOKEN}@github.com/${LOOP_GITHUB_REPO}.git"
  export GH_TOKEN="${LOOP_GITHUB_TOKEN}"
  echo "[loop] github remote configured for ${LOOP_GITHUB_REPO} (push + PR)"
else
  echo "[loop] no github token — fixes stay on a local branch; the patch is printed to the run log"
fi

# 4. Generate the final opencode.json (committed guardrails + injected model/key).
python3 loop-agent/gen_opencode_config.py > /work/opencode.json || { echo "[loop] opencode config gen failed"; exit 1; }

# 4a. ASIK coverage hunt list (the agent's JOB 2 targets). Non-fatal BY DESIGN:
#     a coverage outage must never take down the portal check — the run
#     proceeds without the file and the agent skips hunting.
echo "[loop] generating ASIK coverage hunt list"
if (cd backend && .venv/bin/python -m app.services.coverage_hunt --out ../loop-agent/.hunt_list.md) >/dev/null 2>&1; then
  HUNT_N=$(grep -c '^- ' loop-agent/.hunt_list.md 2>/dev/null || true)
  echo "[loop] hunt list ready (${HUNT_N:-0} hunt-list items)"
else
  echo "[loop] hunt-list generation FAILED — proceeding without it (coverage hunting skipped this run)"
fi

# The exact tree the agent first checked — the base for the fix diff.
START_SHA=$(git rev-parse HEAD)

slug() { echo "${LOOP_PORTAL_URL:-portal}" | sed -E 's#^https?://##; s#[./]#-#g' | cut -d- -f1; }
REGION=$(slug)
# Suffix the branch with the run id: a re-run before the previous PR merges
# must not collide with the open PR's branch (GitHub rejects non-fast-forward
# pushes), and each fix-producing run deserves its own reviewable PR.
BRANCH="loop-agent/${REGION}-${LOOP_RUN_ID:0:6}"
git checkout -q -B "${BRANCH}" 2>/dev/null || git checkout -q "${BRANCH}"

emit_result() { # emit_result <decision> <pushed yes|no> — wraps the agent's verdict + review + PR into LOOP_RESULT
  python3 - "$1" "$BRANCH" "${2:-no}" <<'PYEOF'
import json, sys, pathlib
decision, branch, pushed = sys.argv[1], sys.argv[2], sys.argv[3] == "yes"
check = {}
cp = pathlib.Path("loop-agent/.check_result.json")
if cp.exists():
    try: check = json.loads(cp.read_text())
    except Exception: check = {}
rev = {}
rp = pathlib.Path("loop-agent/.review_result.json")
if rp.exists():
    try: rev = json.loads(rp.read_text())
    except Exception: rev = {}
pr_file = pathlib.Path("loop-agent/.pr_url")
if not check:
    check = {"gap_summary": "agent session produced no .check_result.json — session crashed or was killed"}
out = {
    "decision": decision,
    "test_date": check.get("test_date"),
    "live_count": check.get("live_count"),
    "scraped_count": check.get("scraped_count"),
    "gap_summary": check.get("gap_summary"),
    "coverage_findings": check.get("coverage_findings"),
    "branch_name": branch if decision in ("gap", "fixed") else "",
    "pushed": pushed,
    "pr_url": pr_file.read_text().strip() if pr_file.exists() else "",
    "review_verdict": rev.get("verdict", ""),
    "review_comments": "\n".join(rev.get("comments") or []),
}
print("LOOP_RESULT:" + json.dumps(out, ensure_ascii=False))
PYEOF
}

run_agent() { # run_agent <prompt-file> <label>
  # The session stream goes through format_stream.py so the dashboard log, the
  # Redis ring, and loop_run_events all carry readable lines instead of
  # OpenCode's raw JSON firehose. LOOP_RESULT always passes through untouched.
  echo "[loop] launching OpenCode (${2}) model=${LOOP_LLM_MODEL:-?}"
  opencode run "$(cat "$1")" --format json --print-logs 2>&1 | python3 loop-agent/format_stream.py
  local rc=$?
  echo "[loop] OpenCode exited rc=${rc}"
  return "${rc}"
}

commit_code_changes() { # stage the CODE under review; echo "yes" if a commit was made
  git add scrapers/epus backend/app/services/epus_to_asik.py 2>/dev/null || true
  if git diff --cached --quiet; then
    echo "no"
  else
    git commit -q -m "fix(loop-agent): ${LOOP_PUSKESMAS_NAME:-portal} — scraper/converter fix for live-check gap" || true
    echo "yes"
  fi
}

commit_notes() { # notes ride along INSIDE a fix PR, but never CREATE one — a
  # notes-only write is not a fix (the file is untracked on a fresh clone, so
  # any lint rewrite would otherwise read as a diff and open an empty PR).
  git add loop-agent/LOOP_NOTES.md 2>/dev/null || true
  if ! git diff --cached --quiet; then
    git commit -q -m "chore(loop-agent): ${LOOP_PUSKESMAS_NAME:-portal} — notes update" || true
  fi
}

# ---------------------------------------------------------------------------
# STEP 5 — THE SESSION: check -> judge -> (fix -> re-check), all inside.
# The verdict lands in loop-agent/.check_result.json, written by the agent.
# ---------------------------------------------------------------------------
python3 loop-agent/render_prompt.py > /work/.loop_prompt.txt
run_agent /work/.loop_prompt.txt "live check + fix session" || true

# A session that ends without the verdict file counts as crashed (the model can
# end its turn early). Continuations re-orient the SAME workspace — /tmp files,
# screenshots and uncommitted edits persist — instead of paying for a fresh
# check. Bounded so a genuinely broken run still terminates.
CONT_ATTEMPT=0
while [ ! -f loop-agent/.check_result.json ] && [ "${CONT_ATTEMPT}" -lt 2 ]; do
  CONT_ATTEMPT=$((CONT_ATTEMPT+1))
  echo "[loop] session produced NO verdict file — continuation attempt ${CONT_ATTEMPT}/2"
  cat > /work/.continue_prompt.txt <<'EOF'
Your previous session ENDED WITHOUT writing loop-agent/.check_result.json.
Without that file the whole run counts as crashed. Do NOT restart the check
from scratch: your work survives in /tmp/opencode (scripts, captures,
screenshots) and as uncommitted edits in this repo. Re-orient from that state,
finish the remaining PROMPT steps — including STEP 6 coverage findings — and
write loop-agent/.check_result.json NOW. If the portal is unreachable or login
is blocked, that is ALSO a verdict: write bad_login or error with your
findings, then stop. The one unacceptable outcome is ending without the file.
EOF
  run_agent /work/.continue_prompt.txt "verdict continuation ${CONT_ATTEMPT}" || true
done

# ---------------------------------------------------------------------------
# STEP 6 — notes hygiene + commit whatever the agent changed.
# HAS_FIX is decided by CODE changes only (scrapers/epus, epus_to_asik.py).
# ---------------------------------------------------------------------------
python3 loop-agent/notes_lint.py --fix || true
commit_code_changes >/dev/null
HAS_FIX=$(git diff --quiet "${START_SHA}..HEAD" 2>/dev/null && echo no || echo yes)
commit_notes

# A session that changed code but wrote NO verdict file crashed mid-thought.
# Never review or PR that diff — print it into the run log for forensics.
HAS_VERDICT="no"
[ -f loop-agent/.check_result.json ] && HAS_VERDICT="yes"
if [ "${HAS_FIX}" = "yes" ] && [ "${HAS_VERDICT}" = "no" ]; then
  echo "[loop] agent changed code but wrote NO .check_result.json — session crashed; NOT opening a PR"
  echo "[loop] ---- PATCH BEGIN (${BRANCH}) ----"
  git diff "${START_SHA}..HEAD" | head -c 100000
  echo ""
  echo "[loop] ---- PATCH END ----"
fi

# ---------------------------------------------------------------------------
# STEP 7 — REVIEW LOOP (one LLM call per round on the fix diff)
# ---------------------------------------------------------------------------
if [ "${HAS_FIX}" = "yes" ] && [ "${HAS_VERDICT}" = "yes" ]; then
  if [ "${LOOP_REVIEWER_ENABLED:-0}" != "1" ]; then
    echo "[loop] reviewer not configured — skipping review (PR/review lands with a human)"
    echo '{"verdict": "none", "comments": ["reviewer llm_config not set — review skipped"]}' > loop-agent/.review_result.json
  else
    export LOOP_BASE_REF="${START_SHA}"   # reviewer diffs the fix against the checked-out tree
    MAX_REV="${LOOP_MAX_REVIEW_ITERS:-3}"
    for i in $(seq 1 "${MAX_REV}"); do
      echo "[loop] REVIEW round ${i}/${MAX_REV}"
      python3 loop-agent/reviewer.py || true
      VERDICT_R=$(python3 -c 'import json;print(json.load(open("loop-agent/.review_result.json")).get("verdict","error"))')
      echo "[loop] reviewer verdict: ${VERDICT_R}"
      [ "${VERDICT_R}" = "approve" ] && break
      [ "${VERDICT_R}" != "request_changes" ] && break   # error -> non-blocking
      # Address the review: feed the comments back to the agent; the agent
      # re-verifies its own fix against the live portal (STEP 7 of the prompt).
      # The base prompt must be RENDERED (render_prompt), not the raw template.
      python3 loop-agent/render_prompt.py > /work/.review_prompt.txt
      python3 - >> /work/.review_prompt.txt <<PYEOF
import json, pathlib
rev = json.loads(pathlib.Path("loop-agent/.review_result.json").read_text())
print(
    "\n\nThe AI reviewer REQUESTED CHANGES on your fix. Address every comment, then "
    "RE-RUN your live check (STEP 2-5) to prove the portal is still covered with "
    "your changes, update .check_result.json, then stop. Comments:\n"
    + "\n".join("- " + c for c in rev.get("comments", []))
)
PYEOF
      run_agent /work/.review_prompt.txt "review round ${i}" || true
      commit_code_changes >/dev/null
      commit_notes
      python3 loop-agent/notes_lint.py --fix || true
    done
  fi
fi

# ---------------------------------------------------------------------------
# STEP 8 — PUSH + PR (+ auto-merge per config)
# ---------------------------------------------------------------------------
PR_OPENED="no"
PUSHED="no"
if [ "${HAS_FIX}" = "yes" ] && [ "${HAS_VERDICT}" = "yes" ]; then
  if [ -n "${LOOP_GITHUB_TOKEN:-}" ] && [ -n "${LOOP_GITHUB_REPO:-}" ]; then
    if git push -q -u origin "${BRANCH}" 2>/dev/null; then
      PUSHED="yes"
      # The branch is now safe on GitHub either way. The PR is the optional part:
      # LOOP_OPEN_PR=0 (config or per-run choice) parks the run as changes_ready
      # and the admin opens the PR from the dashboard when they want it.
      REVIEW_VERDICT=$(python3 -c 'import json;print(json.load(open("loop-agent/.review_result.json")).get("verdict","none"))' 2>/dev/null || echo none)
      if [ "${LOOP_OPEN_PR:-1}" != "1" ]; then
        echo "[loop] auto_open_pr off — branch ${BRANCH} pushed; open the PR from the dashboard when ready"
      else
      # Build the PR body in Python and pass it as a FILE — a shell heredoc
      # would execute the markdown backticks as command substitution. Structured
      # sections (finding / fix / proof) come from the agent's verdict file so a
      # human can review without reading a wall of text.
      python3 - > loop-agent/.pr_body.md <<PYEOF
import json, pathlib

def _load(p):
    f = pathlib.Path(p)
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except Exception:
        return {}

def _section(title, body):
    body = (body or "").strip()
    if not body:
        return ""
    return f"## {title}\n\n{body}\n\n"

check = _load("loop-agent/.check_result.json")
rev = _load("loop-agent/.review_result.json")
# Only the lines THIS run added to the notes — not the whole file.
start_notes = pathlib.Path("/tmp/notes_at_start.md")
cur_notes = pathlib.Path("loop-agent/LOOP_NOTES.md")
added = []
if cur_notes.exists():
    import difflib
    before = start_notes.read_text().splitlines() if start_notes.exists() else []
    after = cur_notes.read_text().splitlines()
    for line in difflib.unified_diff(before, after, lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++") and line[1:].strip():
            added.append(line[1:].strip())
comments = rev.get("comments") or []

verdict = check.get("verdict", "unknown")
counts = ", ".join(filter(None, [
    f"test date {check.get('test_date')}" if check.get("test_date") else "",
    f"live {check.get('live_count')}" if check.get("live_count") is not None else "",
    f"scraped {check.get('scraped_count')}" if check.get("scraped_count") is not None else "",
])) or "no counts reported"

# chr(96) = a markdown code tick — written this way so the heredoc never sees
# a raw backtick (bash would execute it as command substitution).
tick = chr(96)
out = (
    f"## Loop agent — ${LOOP_PUSKESMAS_NAME:-portal}\n\n"
    f"**Verdict: {verdict}** ({counts})\n"
    f"Run {tick}${LOOP_RUN_ID:-?}{tick} · portal ${LOOP_PORTAL_URL:-?} · branch {tick}${BRANCH}{tick}\n\n"
)

# Old verdict files only carry gap_summary — fall back to it as the Finding.
finding = check.get("finding") or check.get("gap_summary") or ""
out += _section("What we found on the live site", finding)
out += _section("The fix", check.get("fix"))
out += _section("How it was verified (re-proof)", check.get("proof"))
review_body = rev.get("verdict", "none")
if comments:
    review_body += "\n" + "\n".join("> " + c for c in comments)
out += _section("AI reviewer", review_body)
out += _section("Notes added this run", "\n".join(f"- {a}" for a in added))

cf = check.get("coverage_findings") or []

def _cov_line(f):
    st = (f.get("status") or "?").lower()
    form = f.get("form") or "?"
    qs = "; ".join(f.get("questions") or []) or "?"
    if st == "mapped":
        return f"- MAPPED {form}: {qs}  <-  {f.get('epus_source') or 'source not named'}"
    if st == "absent":
        tabs = "; ".join(f.get("tabs_checked") or []) or "tabs not listed"
        return f"- ABSENT {form} (checked: {tabs})"
    return f"- CANDIDATE {form}: {qs} ({f.get('evidence') or 'no evidence given'})"

cov_lines = [_cov_line(f) for f in cf][:40]
if len(cf) > 40:
    cov_lines.append(f"- ... {len(cf) - 40} more findings (full list stored on the run record)")
out += _section("Coverage findings (ASIK questions)", "\n".join(cov_lines))
print(out)

mapped_n = sum(1 for f in cf if (f.get("status") or "").lower() == "mapped")
title = f"loop-agent: fix ${LOOP_PUSKESMAS_NAME:-portal} scraper/converter"
pathlib.Path("loop-agent/.pr_title").write_text(title)
PYEOF
      # Notify humans on open: reviewers get a GitHub notification, assignees get
      # the PR in their list. A PR's own author cannot be its reviewer, so the
      # token owner belongs in LOOP_PR_ASSIGNEES, not LOOP_PR_REVIEWERS.
      PR_EXTRA=()
      [ -n "${LOOP_PR_REVIEWERS:-}" ] && PR_EXTRA+=(--reviewer "${LOOP_PR_REVIEWERS}")
      [ -n "${LOOP_PR_ASSIGNEES:-}" ] && PR_EXTRA+=(--assignee "${LOOP_PR_ASSIGNEES}")
      if gh pr create --base master --head "${BRANCH}" --title "$(cat loop-agent/.pr_title 2>/dev/null || echo "loop-agent: fix ${LOOP_PUSKESMAS_NAME:-portal} scraper/converter")" --body-file loop-agent/.pr_body.md "${PR_EXTRA[@]}" > loop-agent/.pr_url 2>/dev/null; then
        PR_OPENED="yes"
        echo "[loop] PR opened: $(cat loop-agent/.pr_url)"
        # Auto-merge ONLY in auto mode, reviewer-approved, and the agent's own
        # final verdict is covered.
        FINAL_VERDICT=$(python3 -c 'import json;print(json.load(open("loop-agent/.check_result.json")).get("verdict","error"))' 2>/dev/null || echo error)
        if [ "${LOOP_MERGE_MODE:-manual}" = "auto" ] && [ "${REVIEW_VERDICT}" = "approve" ] && [ "${FINAL_VERDICT}" = "covered" ]; then
          echo "[loop] auto-merge enabled + approved + covered -> merging PR"
          gh pr merge --merge --delete-branch=true 2>/dev/null || echo "[loop] auto-merge failed (PR stays open for a human)"
        fi
      else
        echo "[loop] gh pr create failed — branch ${BRANCH} is pushed; open the PR from the dashboard (Buat PR) or by hand"
      fi
      fi
    else
      echo "[loop] git push failed — patch follows in the log"
    fi
  fi
  if [ "${PUSHED}" = "no" ]; then
    # No token or push failed: put the patch in the run log so a human can
    # apply it. A pushed branch (PR on or off) needs no patch dump.
    echo "[loop] ---- PATCH BEGIN (${BRANCH}) ----"
    git diff "${START_SHA}..HEAD" | head -c 100000
    echo ""
    echo "[loop] ---- PATCH END ----"
  fi
fi

# ---------------------------------------------------------------------------
# STEP 9 — the verdict: the agent's own, wrapped for the worker
# ---------------------------------------------------------------------------
VERDICT=$(python3 -c 'import json;print(json.load(open("loop-agent/.check_result.json")).get("verdict","error"))' 2>/dev/null || echo error)
echo "[loop] agent verdict: ${VERDICT}"
if [ "${VERDICT}" = "covered" ] && [ "${HAS_FIX}" = "yes" ]; then
  emit_result "fixed" "$PUSHED"     # gap that is now closed; worker maps to needs_review/merged/changes_ready
elif [ "${HAS_FIX}" = "yes" ]; then
  emit_result "gap" "$PUSHED"       # partial/failed fix: PR or patch for a human
else
  emit_result "${VERDICT}" "$PUSHED"
fi
exit 0
