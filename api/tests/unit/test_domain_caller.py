"""Tests for Caller domain model."""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.caller import Caller


def test_caller_minimal():
    c = Caller(
        phone="+15551234567",
        first_seen=datetime(2026, 4, 1, tzinfo=timezone.utc),
        last_seen=datetime(2026, 5, 14, tzinfo=timezone.utc),
        call_count=3,
    )
    assert c.last_outcome is None
    assert c.notes == ""


def test_caller_to_firestore_camelcase():
    c = Caller(
        phone="+15551234567",
        first_seen=datetime(2026, 4, 1, tzinfo=timezone.utc),
        last_seen=datetime(2026, 5, 14, tzinfo=timezone.utc),
        call_count=3,
        last_call_sid="CA123",
        last_outcome="messageTaken",
        notes="prefers Hindi",
    )
    fs = c.to_firestore()
    assert "firstSeen" in fs and "lastSeen" in fs and "callCount" in fs
    assert "lastCallSid" in fs and "lastOutcome" in fs
    assert "phone" not in fs  # phone is the doc id, not a field
    assert "call_count" not in fs  # snake_case must not leak


def test_caller_round_trip():
    c = Caller(
        phone="+15551234567",
        first_seen=datetime(2026, 4, 1, tzinfo=timezone.utc),
        last_seen=datetime(2026, 5, 14, tzinfo=timezone.utc),
        call_count=3,
        last_call_sid="CA123",
        last_outcome="resolved",
    )
    recovered = Caller.from_firestore(phone="+15551234567", data=c.to_firestore())
    assert recovered == c
