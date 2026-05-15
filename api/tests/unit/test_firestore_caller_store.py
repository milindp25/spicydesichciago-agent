"""Tests for FirestoreCallerStore against the emulator."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.caller import Caller
from app.infrastructure.firestore_caller_store import FirestoreCallerStore


@pytest.fixture
def store(firestore_db):
    return FirestoreCallerStore(client=firestore_db)


def test_upsert_first_call_creates_record(store):
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    store.upsert_on_call(
        phone="+15551234567",
        ts=now,
        call_sid="CA1",
        outcome="resolved",
    )
    c = store.get("+15551234567")
    assert c is not None
    assert c.first_seen == now
    assert c.last_seen == now
    assert c.call_count == 1
    assert c.last_call_sid == "CA1"
    assert c.last_outcome == "resolved"


def test_upsert_second_call_increments_count_keeps_first_seen(store):
    first = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    second = datetime(2026, 5, 14, 13, 0, tzinfo=timezone.utc)
    store.upsert_on_call(phone="+15551234567", ts=first, call_sid="CA1", outcome="resolved")
    store.upsert_on_call(phone="+15551234567", ts=second, call_sid="CA2", outcome="messageTaken")

    c = store.get("+15551234567")
    assert c is not None
    assert c.first_seen == first  # unchanged
    assert c.last_seen == second
    assert c.call_count == 2
    assert c.last_call_sid == "CA2"
    assert c.last_outcome == "messageTaken"


def test_get_missing_returns_none(store):
    assert store.get("+19999999999") is None
