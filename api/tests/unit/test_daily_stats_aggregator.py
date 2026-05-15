"""Tests for the pure daily-stats aggregator."""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.call import Call, Outcome
from app.services.daily_stats_aggregator import aggregate


def _call(sid: str, outcome: Outcome) -> Call:
    return Call(
        call_sid=sid,
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
        outcome=outcome,
    )


def test_empty_list_zero_counts():
    now = datetime(2026, 5, 14, 23, 0, tzinfo=timezone.utc)
    stats = aggregate("2026-05-14", [], now)
    assert stats.total_calls == 0
    assert stats.transfers_completed == 0
    assert stats.transfers_failed == 0
    assert stats.messages_taken == 0
    assert stats.date == "2026-05-14"
    assert stats.computed_at == now


def test_mixed_outcomes_counted():
    calls = [
        _call("CA1", Outcome.TRANSFERRED),
        _call("CA2", Outcome.TRANSFERRED),
        _call("CA3", Outcome.FAILED),
        _call("CA4", Outcome.MESSAGE_TAKEN),
        _call("CA5", Outcome.IN_PROGRESS),
    ]
    stats = aggregate("2026-05-14", calls, datetime.now(timezone.utc))
    assert stats.total_calls == 5
    assert stats.transfers_completed == 2
    assert stats.transfers_failed == 1
    assert stats.messages_taken == 1


def test_unknown_outcome_only_counts_total():
    # RESOLVED is a known outcome but not transferred/failed/messageTaken — it
    # should still increment total_calls but no per-bucket counter.
    calls = [_call("CA1", Outcome.RESOLVED)]
    stats = aggregate("2026-05-14", calls, datetime.now(timezone.utc))
    assert stats.total_calls == 1
    assert stats.transfers_completed == 0
    assert stats.transfers_failed == 0
    assert stats.messages_taken == 0
