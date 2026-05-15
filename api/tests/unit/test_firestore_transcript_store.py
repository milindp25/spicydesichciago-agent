"""Tests for FirestoreTranscriptStore against the emulator."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.transcript import Turn
from app.infrastructure.firestore_transcript_store import FirestoreTranscriptStore


@pytest.fixture
def store(firestore_db):
    return FirestoreTranscriptStore(client=firestore_db)


def test_set_and_get_roundtrip(store):
    stored_at = datetime(2026, 5, 14, 12, 5, tzinfo=timezone.utc)
    turns = [
        Turn(role="caller", text="what time do you open?"),
        Turn(role="agent", text="we open at 11am"),
    ]
    store.set(call_sid="CA1", turns=turns, stored_at=stored_at)

    fetched = store.get("CA1")
    assert fetched is not None
    assert fetched.call_sid == "CA1"
    assert fetched.stored_at == stored_at
    assert len(fetched.turns) == 2
    assert fetched.turns[0].role == "caller"
    assert fetched.turns[0].text == "what time do you open?"
    assert fetched.turns[1].role == "agent"


def test_get_returns_none_when_missing(store):
    assert store.get("CA-missing") is None


def test_set_overwrites_existing(store):
    stored_at = datetime(2026, 5, 14, 12, 5, tzinfo=timezone.utc)
    store.set(
        call_sid="CA1",
        turns=[Turn(role="caller", text="first")],
        stored_at=stored_at,
    )
    later = datetime(2026, 5, 14, 12, 10, tzinfo=timezone.utc)
    store.set(
        call_sid="CA1",
        turns=[
            Turn(role="caller", text="second"),
            Turn(role="agent", text="ok"),
        ],
        stored_at=later,
    )
    fetched = store.get("CA1")
    assert fetched is not None
    assert fetched.stored_at == later
    assert len(fetched.turns) == 2
    assert fetched.turns[0].text == "second"
