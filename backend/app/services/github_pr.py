"""GitHub PR reconcile for loop runs.

A run parks in `needs_review` while its fix PR is open, and nothing else moves
it. This polls each open PR and settles the run: merged -> MERGED, closed
without merge -> PR_REJECTED (which the nightly sweep re-fires). The merged or
rejected head branch is deleted so `loop-agent/*` branches don't pile up.

Best-effort: no token/repo configured is a no-op, and a failed GitHub call
leaves the run as-is for the next pass.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from app.config import settings
from app.crud import loop_run as crud
from app.models.loop_run import LoopRunStatus

log = logging.getLogger(__name__)

_API = "https://api.github.com"
_PR_NUM_RE = re.compile(r"/pull/(\d+)")


def _norm_repo(repo: str) -> str:
    repo = re.sub(r"^https?://github\.com/", "", repo.strip())
    return repo[:-4] if repo.endswith(".git") else repo


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ckg-loop-agent",
    }


def _pr_state(repo: str, number: int, token: str) -> dict | None:
    req = urllib.request.Request(f"{_API}/repos/{repo}/pulls/{number}", headers=_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        log.warning("loop reconcile: PR %s#%s fetch failed: %s", repo, number, e)
        return None
    return {"merged": bool(data.get("merged")), "state": data.get("state")}


def _delete_branch(repo: str, branch: str, token: str) -> None:
    req = urllib.request.Request(
        f"{_API}/repos/{repo}/git/refs/heads/{branch}", headers=_headers(token), method="DELETE",
    )
    try:
        urllib.request.urlopen(req, timeout=30).close()
    except Exception:
        pass  # already gone (repo auto-delete) or no rights — nothing to recover


def _gh_request(repo: str, path: str, token: str, payload: dict | None, method: str = "POST") -> tuple[int, dict]:
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{_API}/repos/{repo}{path}", data=body, headers=_headers(token), method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"GitHub {method} {path} -> {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"GitHub {method} {path} failed: {e.reason}") from e


def open_pr_for_run(run, puskesmas_name: str) -> str:
    """Create the PR for a changes_ready run's pushed branch; returns the URL.

    Only the run record feeds the title/body (the container is gone by then):
    decision + counts + gap summary + coverage findings + review verdict.
    Raises RuntimeError when token/repo is unconfigured or GitHub refuses —
    the caller surfaces that; the run stays changes_ready either way.
    """
    if not (settings.LOOP_GITHUB_TOKEN and settings.LOOP_GITHUB_REPO):
        raise RuntimeError("LOOP_GITHUB_TOKEN / LOOP_GITHUB_REPO not configured")
    if not run.branch_name:
        raise RuntimeError("run has no pushed branch")
    token = settings.LOOP_GITHUB_TOKEN
    repo = _norm_repo(settings.LOOP_GITHUB_REPO)

    findings = run.coverage_findings or []
    counts = ", ".join(filter(None, [
        f"test date {run.test_date}" if run.test_date else "",
        f"live {run.live_count}" if run.live_count is not None else "",
        f"scraped {run.scraped_count}" if run.scraped_count is not None else "",
    ])) or "no counts reported"
    lines = [
        f"## Loop agent — {puskesmas_name}",
        "",
        f"**Verdict: {run.decision or 'unknown'}** ({counts})",
        f"Run `{run.id}` · branch `{run.branch_name}`",
        "",
    ]
    if run.gap_summary:
        lines += ["## What we found on the live site", "", run.gap_summary, ""]
    cov_lines = []
    for f in findings:
        st = (f.get("status") or "?").lower()
        form = f.get("form") or "?"
        qs = "; ".join(f.get("questions") or []) or "?"
        if st == "mapped":
            cov_lines.append(f"- MAPPED {form}: {qs}  <-  {f.get('epus_source') or 'source not named'}")
        elif st == "absent":
            tabs = "; ".join(f.get("tabs_checked") or []) or "tabs not listed"
            cov_lines.append(f"- ABSENT {form} (checked: {tabs})")
        else:
            cov_lines.append(f"- CANDIDATE {form}: {qs} ({f.get('evidence') or 'no evidence given'})")
    if cov_lines:
        lines += ["## Coverage findings (ASIK questions)", *cov_lines, ""]
    if run.review_verdict:
        lines += ["## AI reviewer", run.review_verdict]
        for c in (run.review_comments or "").splitlines():
            if c.strip():
                lines.append(f"> {c}")
        lines.append("")
    _, data = _gh_request(repo, "/pulls", token, {
        "title": f"loop-agent: fix {puskesmas_name} scraper/converter",
        "head": run.branch_name,
        "base": "master",
        "body": "\n".join(lines),
    })
    pr_url = data.get("html_url") or ""
    pr_number = data.get("number")
    reviewers = [r for r in (settings.LOOP_PR_REVIEWERS or "").split(",") if r.strip()]
    assignees = [a for a in (settings.LOOP_PR_ASSIGNEES or "").split(",") if a.strip()]
    if pr_number and reviewers:
        try:
            _gh_request(repo, f"/pulls/{pr_number}/requested_reviewers", token,
                        {"reviewers": [r.strip() for r in reviewers]})
        except Exception as e:
            log.warning("PR reviewers request failed (non-blocking): %s", e)
    if pr_number and assignees:
        try:
            _gh_request(repo, f"/issues/{pr_number}/assignees", token,
                        {"assignees": [a.strip() for a in assignees]})
        except Exception as e:
            log.warning("PR assignees request failed (non-blocking): %s", e)
    return pr_url


def reconcile_needs_review(db: Session) -> dict[str, int]:
    """Poll every open needs_review PR and settle the run. Returns counts."""
    result = {"checked": 0, "merged": 0, "rejected": 0}
    if not (settings.LOOP_GITHUB_TOKEN and settings.LOOP_GITHUB_REPO):
        return result
    token = settings.LOOP_GITHUB_TOKEN
    repo = _norm_repo(settings.LOOP_GITHUB_REPO)
    for run in crud.list_needs_review_prs(db):
        m = _PR_NUM_RE.search(run.pr_url or "")
        if not m:
            continue
        result["checked"] += 1
        state = _pr_state(repo, int(m.group(1)), token)
        if state is None:
            continue
        if state["merged"]:
            crud.set_status(db, run, LoopRunStatus.MERGED)
            result["merged"] += 1
        elif state["state"] == "closed":
            crud.set_status(db, run, LoopRunStatus.PR_REJECTED)
            result["rejected"] += 1
        else:
            continue
        if run.branch_name:
            _delete_branch(repo, run.branch_name, token)
    return result
