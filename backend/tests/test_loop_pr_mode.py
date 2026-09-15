"""Loop run status mapping across the PR-mode matrix.

The open_pr toggle must never lose work: a fix-producing run with the PR off
lands in changes_ready ONLY when its branch actually reached GitHub (pushed);
an unpushed patch (no token / push failed) parks in needs_review, and a PR
that failed to open still parks the run in needs_review.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.loop_run import LoopRunStatus  # noqa: E402
from app.tasks.loop_agent import _map_result_to_status  # noqa: E402


def test_fixed_without_pr_and_open_pr_off_pushed_is_changes_ready():
    assert (
        _map_result_to_status("fixed", "manual", has_pr=False, open_pr=False, pushed=True)
        == LoopRunStatus.CHANGES_READY
    )


def test_gap_without_pr_and_open_pr_off_pushed_is_changes_ready():
    assert (
        _map_result_to_status("gap", "manual", has_pr=False, open_pr=False, pushed=True)
        == LoopRunStatus.CHANGES_READY
    )


def test_fix_without_pr_and_without_push_never_claims_changes_ready():
    assert (
        _map_result_to_status("fixed", "manual", has_pr=False, open_pr=False, pushed=False)
        == LoopRunStatus.NEEDS_REVIEW
    )


def test_fixed_with_pr_requested_but_failed_still_needs_review():
    assert (
        _map_result_to_status("fixed", "manual", has_pr=False, open_pr=True, pushed=True)
        == LoopRunStatus.NEEDS_REVIEW
    )


def test_fixed_with_pr_manual_mode_is_needs_review():
    assert (
        _map_result_to_status("fixed", "manual", has_pr=True, open_pr=True, pushed=True)
        == LoopRunStatus.NEEDS_REVIEW
    )


def test_fixed_with_pr_auto_mode_is_merged():
    assert (
        _map_result_to_status("fixed", "auto", has_pr=True, open_pr=True, pushed=True)
        == LoopRunStatus.MERGED
    )


def test_conclusion_verdicts_ignore_pr_flags():
    assert (
        _map_result_to_status("covered", "manual", has_pr=False, open_pr=False, pushed=False)
        == LoopRunStatus.COVERED
    )
    assert (
        _map_result_to_status("no_data", "manual", has_pr=False, open_pr=False, pushed=False)
        == LoopRunStatus.NO_DATA
    )
    assert (
        _map_result_to_status("bad_login", "manual", has_pr=False, open_pr=False, pushed=False)
        == LoopRunStatus.BAD_CREDS
    )


def test_unknown_decision_fails():
    assert (
        _map_result_to_status(None, "manual", has_pr=False, open_pr=False, pushed=False)
        == LoopRunStatus.FAILED
    )
