"""Unit tests for the merge-status decision + transport-error classifier.

These guard the silent-success fix: a merge job with any unmerged patient must
end FAILED, never SUCCESS. Pure functions — no DB / LLM / Celery needed.
"""
from app.models.merge_job import MergeStatus
from app.tasks.merge import _decide_merge_status, _is_transport_error


def test_all_succeeded_is_success():
    assert _decide_merge_status(0) is MergeStatus.SUCCESS


def test_any_failure_is_failed():
    assert _decide_merge_status(1) is MergeStatus.FAILED
    assert _decide_merge_status(37) is MergeStatus.FAILED


def test_total_outage_is_failed():
    # 0 succeeded / N failed — the exact shape of the gpt-oss 530 incident.
    assert _decide_merge_status(10) is MergeStatus.FAILED


def test_transport_error_classifier_positive():
    assert _is_transport_error("LLM HTTP 530: origin down")
    assert _is_transport_error("LLM HTTP 502: bad gateway")
    assert _is_transport_error("LLM stream error: connection reset")
    assert _is_transport_error("<urlopen error timed out>")


def test_transport_error_classifier_negative():
    # JSON/data errors are NOT transport — they signal a poison record.
    assert not _is_transport_error("Expecting value: line 1 column 1 (char 0)")
    assert not _is_transport_error("merge shape invalid: sections is a dict")
    assert not _is_transport_error("")
    assert not _is_transport_error(None)
