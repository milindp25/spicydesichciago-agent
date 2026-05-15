"""Integration tests for FirestorePickupStateStore (emulator-backed)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.pickup import PickupRecord
from app.infrastructure.firestore_pickup_state_store import FirestorePickupStateStore


@pytest.fixture
def store(firestore_db):
    return FirestorePickupStateStore(client=firestore_db)


def test_get_missing_tenant_returns_none(store):
    assert store.get("spicy-desi") is None


def test_set_then_get_round_trip(store):
    record = PickupRecord(
        location_id="L1",
        set_at=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
        set_for_date="2026-05-15",
    )
    store.set("spicy-desi", record)
    fetched = store.get("spicy-desi")
    assert fetched == record


def test_set_overwrites_previous(store):
    first = PickupRecord(
        location_id="L1",
        set_at=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
        set_for_date="2026-05-15",
    )
    second = PickupRecord(
        location_id="L2",
        set_at=datetime(2026, 5, 16, 13, 30, tzinfo=timezone.utc),
        set_for_date="2026-05-16",
    )
    store.set("spicy-desi", first)
    store.set("spicy-desi", second)
    assert store.get("spicy-desi") == second


def test_separate_tenants_isolated(store):
    a = PickupRecord(
        location_id="LA",
        set_at=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
        set_for_date="2026-05-15",
    )
    b = PickupRecord(
        location_id="LB",
        set_at=datetime(2026, 5, 15, 13, 0, tzinfo=timezone.utc),
        set_for_date="2026-05-15",
    )
    store.set("tenant-a", a)
    store.set("tenant-b", b)
    assert store.get("tenant-a") == a
    assert store.get("tenant-b") == b
