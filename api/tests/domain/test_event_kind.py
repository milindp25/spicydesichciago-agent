"""Tests for the EventKind taxonomy."""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.call import CallEvent, EventKind


def test_event_kind_values_match_wire_strings():
    """Smoke test against accidental rename — values must match camelCase wire format."""
    assert EventKind.CALL_STARTED.value == "callStarted"
    assert EventKind.CALL_ENDED.value == "callEnded"
    assert EventKind.CALL_SUMMARY.value == "callSummary"
    assert EventKind.TRANSFER_DECIDED.value == "transferDecided"
    assert EventKind.TRANSFER_INITIATED.value == "transferInitiated"
    assert EventKind.TRANSFER_COMPLETED.value == "transferCompleted"
    assert EventKind.TRANSFER_FAILED.value == "transferFailed"
    assert EventKind.MESSAGE_TAKEN.value == "messageTaken"
    assert EventKind.SMS_LINK_SENT.value == "smsLinkSent"
    assert EventKind.TOOL_CALLED.value == "toolCalled"
    assert EventKind.TOOL_ERROR.value == "toolError"


def test_call_event_roundtrip_with_enum_kind():
    """CallEvent built with EventKind.X.value round-trips through Firestore translation."""
    ts = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
    original = CallEvent(
        ts=ts,
        kind=EventKind.MESSAGE_TAKEN.value,
        payload={"messageId": "msg-1"},
    )
    restored = CallEvent.from_firestore(original.to_firestore())
    assert restored.ts == ts
    assert restored.kind == "messageTaken"
    assert restored.payload == {"messageId": "msg-1"}


def test_call_event_accepts_unknown_kind_for_backcompat():
    """Unknown kind strings (e.g. legacy data) must still parse via from_firestore."""
    ts = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
    data = {"ts": ts, "kind": "legacyFoo", "payload": {"x": 1}}
    event = CallEvent.from_firestore(data)
    assert event.kind == "legacyFoo"
    assert event.payload == {"x": 1}
