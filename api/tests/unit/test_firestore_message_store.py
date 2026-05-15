"""Tests for FirestoreMessageStore against the emulator."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.message import Message, MessageStatus
from app.infrastructure.firestore_message_store import FirestoreMessageStore


@pytest.fixture
def store(firestore_db):
    return FirestoreMessageStore(client=firestore_db)


def test_create_stores_message_returns_id(store):
    m = Message(
        call_sid="CA1",
        caller_phone="+15551234567",
        caller_name="Anika",
        reason="catering for Saturday",
        taken_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    msg_id = store.create(m)
    assert msg_id  # Firestore-generated id

    fetched = store.get(msg_id)
    assert fetched is not None
    assert fetched.reason == "catering for Saturday"
    assert fetched.status == MessageStatus.NEW


def test_list_unhandled_orders_newest_first(store):
    earlier = Message(
        call_sid="CA1",
        caller_phone="+15551234567",
        reason="first",
        taken_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
    )
    later = Message(
        call_sid="CA2",
        caller_phone="+15559998888",
        reason="second",
        taken_at=datetime(2026, 5, 14, 13, 0, tzinfo=timezone.utc),
    )
    store.create(earlier)
    store.create(later)

    msgs = list(store.list_unhandled(limit=10))
    assert [m.reason for m in msgs] == ["second", "first"]


def test_mark_handled_sets_status_and_metadata(store):
    m = Message(
        call_sid="CA1",
        caller_phone="+15551234567",
        reason="catering",
        taken_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    msg_id = store.create(m)

    handled_at = datetime(2026, 5, 15, tzinfo=timezone.utc)
    store.mark_handled(message_id=msg_id, handled_at=handled_at, handled_by="uid-owner")

    fetched = store.get(msg_id)
    assert fetched is not None
    assert fetched.status == MessageStatus.HANDLED
    assert fetched.handled_at == handled_at
    assert fetched.handled_by == "uid-owner"

    assert list(store.list_unhandled(limit=10)) == []
