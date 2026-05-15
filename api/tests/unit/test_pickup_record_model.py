"""Tests for PickupRecord domain model."""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.pickup import PickupRecord


def test_to_firestore_camel_case() -> None:
    r = PickupRecord(
        location_id="L1",
        set_at=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
        set_for_date="2026-05-15",
    )
    d = r.to_firestore()
    assert d == {
        "locationId": "L1",
        "setAt": datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
        "setForDate": "2026-05-15",
    }


def test_from_firestore_round_trip_datetime() -> None:
    src = PickupRecord(
        location_id="L1",
        set_at=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
        set_for_date="2026-05-15",
    )
    round_tripped = PickupRecord.from_firestore(src.to_firestore())
    assert round_tripped == src


def test_from_firestore_tolerates_iso_string_setAt() -> None:
    # Migrated JSON data may have setAt as an ISO string with +00:00 offset.
    r = PickupRecord.from_firestore(
        {
            "locationId": "L1",
            "setAt": "2026-05-15T12:00:00+00:00",
            "setForDate": "2026-05-15",
        }
    )
    assert r.location_id == "L1"
    assert r.set_at == datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
    assert r.set_for_date == "2026-05-15"


def test_from_firestore_tolerates_iso_string_with_z_suffix() -> None:
    r = PickupRecord.from_firestore(
        {
            "locationId": "L1",
            "setAt": "2026-05-15T12:00:00Z",
            "setForDate": "2026-05-15",
        }
    )
    assert r.set_at == datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
