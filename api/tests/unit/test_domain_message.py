"""Tests for Message domain model."""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.message import Message, MessageStatus


def test_message_defaults_to_new_status():
    m = Message(
        call_sid="CA123",
        caller_phone="+15551234567",
        reason="catering",
        taken_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    assert m.status == MessageStatus.NEW
    assert m.caller_name is None
    assert m.handled_at is None
    assert m.handled_by is None


def test_message_to_firestore_camelcase():
    m = Message(
        call_sid="CA123",
        caller_phone="+15551234567",
        caller_name="Anika",
        reason="catering for Saturday",
        taken_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    fs = m.to_firestore()
    assert fs["callSid"] == "CA123"
    assert fs["callerPhone"] == "+15551234567"
    assert fs["callerName"] == "Anika"
    assert fs["status"] == "new"
    assert "call_sid" not in fs


def test_message_handled_round_trip():
    m = Message(
        call_sid="CA123",
        caller_phone="+15551234567",
        reason="catering",
        taken_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        status=MessageStatus.HANDLED,
        handled_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        handled_by="Woavythv26dZ7XlJngL7lKakQ7N2",
    )
    recovered = Message.from_firestore(data=m.to_firestore())
    assert recovered == m
