"""Tests for Call domain models."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.call import Call, CallEvent, Outcome


def test_outcome_values():
    """Enum has exactly the expected outcomes."""
    assert Outcome.IN_PROGRESS == "inProgress"
    assert Outcome.RESOLVED == "resolved"
    assert Outcome.TRANSFERRED == "transferred"
    assert Outcome.MESSAGE_TAKEN == "messageTaken"
    assert Outcome.FAILED == "failed"


def test_call_minimal_construction():
    """Call requires call_sid, started_at, caller_phone, from_number."""
    call = Call(
        call_sid="CA12345",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    assert call.outcome == Outcome.IN_PROGRESS
    assert call.ended_at is None
    assert call.summary is None
    assert call.tools_used == []
    assert call.duration_ms is None


def test_call_to_firestore_uses_camelcase():
    """to_firestore() produces camelCase keys matching dashboard convention."""
    call = Call(
        call_sid="CA12345",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
        tools_used=["listMenuCategories"],
    )
    fs = call.to_firestore()
    assert "callerPhone" in fs
    assert "fromNumber" in fs
    assert "toolsUsed" in fs
    assert "startedAt" in fs
    assert "caller_phone" not in fs  # snake_case must NOT leak
    assert fs["toolsUsed"] == ["listMenuCategories"]


def test_call_from_firestore_round_trip():
    """from_firestore(call.to_firestore()) produces an equivalent Call."""
    original = Call(
        call_sid="CA12345",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
        outcome=Outcome.RESOLVED,
        summary="Asked about hours",
        tools_used=["getPickupToday"],
    )
    recovered = Call.from_firestore(call_sid="CA12345", data=original.to_firestore())
    assert recovered == original


def test_call_event_minimal():
    """CallEvent requires ts and kind; payload defaults to empty."""
    ev = CallEvent(
        ts=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
        kind="toolCalled",
    )
    assert ev.payload == {}


def test_call_event_to_firestore():
    ev = CallEvent(
        ts=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
        kind="toolCalled",
        payload={"tool": "listMenuCategories"},
    )
    fs = ev.to_firestore()
    assert fs == {
        "ts": datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
        "kind": "toolCalled",
        "payload": {"tool": "listMenuCategories"},
    }
