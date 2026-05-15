"""Tests for FirestoreOwnerOverrideStore."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.owner_override import OwnerOverride
from app.infrastructure.firestore_owner_override_store import FirestoreOwnerOverrideStore


@pytest.fixture
def store(firestore_db):
    return FirestoreOwnerOverrideStore(client=firestore_db)


def test_get_current_when_absent_returns_none(store):
    assert store.get_current() is None


def test_set_then_get_round_trip(store):
    o = OwnerOverride(
        active=True,
        until_iso="2026-05-14T18:00:00Z",
        reason="wedding",
        set_by="uid-owner",
        set_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    store.set(o)
    fetched = store.get_current()
    assert fetched == o


def test_clear_resets_to_inactive(store):
    store.set(
        OwnerOverride(
            active=True,
            until_iso="2026-05-14T18:00:00Z",
            reason="wedding",
            set_by="uid-owner",
            set_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        )
    )
    store.clear(cleared_by="uid-owner")
    fetched = store.get_current()
    assert fetched is not None
    assert fetched.active is False
    assert fetched.until_iso is None
    assert fetched.reason is None
