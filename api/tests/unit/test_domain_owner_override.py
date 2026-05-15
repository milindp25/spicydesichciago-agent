"""Tests for OwnerOverride domain model."""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.owner_override import OwnerOverride


def test_inactive_default():
    o = OwnerOverride(
        active=False,
        set_by="uid123",
        set_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    assert o.until_iso is None
    assert o.reason is None


def test_active_with_window():
    o = OwnerOverride(
        active=True,
        until_iso="2026-05-14T18:00:00Z",
        reason="wedding",
        set_by="uid123",
        set_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    fs = o.to_firestore()
    assert fs["active"] is True
    assert fs["untilIso"] == "2026-05-14T18:00:00Z"
    assert fs["setBy"] == "uid123"
    assert "set_by" not in fs


def test_round_trip():
    o = OwnerOverride(
        active=True,
        until_iso="2026-05-14T18:00:00Z",
        reason="wedding",
        set_by="uid123",
        set_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    recovered = OwnerOverride.from_firestore(o.to_firestore())
    assert recovered == o
