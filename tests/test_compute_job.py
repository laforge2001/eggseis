"""Tests for compute Job + CancellationToken (no Qt)."""

from __future__ import annotations

from eggseis.compute.job import CancellationToken, Job


def test_token_default_not_cancelled():
    t = CancellationToken()
    assert t.cancelled is False


def test_token_cancel_sets_flag():
    t = CancellationToken()
    t.cancel()
    assert t.cancelled is True


def test_job_ids_are_unique_and_increasing():
    j1 = Job()
    j2 = Job()
    assert j1.id != j2.id
    assert j2.id > j1.id


def test_job_default_token_not_cancelled():
    j = Job()
    assert j.token.cancelled is False
