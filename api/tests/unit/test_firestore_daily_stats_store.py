"""Tests for FirestoreDailyStatsStore against the emulator."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.daily_stats import DailyStats
from app.infrastructure.firestore_daily_stats_store import FirestoreDailyStatsStore


@pytest.fixture
def store(firestore_db):
    return FirestoreDailyStatsStore(client=firestore_db)


def test_get_missing_returns_none(store):
    assert store.get("2026-05-14") is None


def test_set_then_get_roundtrip(store):
    stats = DailyStats(
        date="2026-05-14",
        total_calls=12,
        transfers_completed=3,
        transfers_failed=1,
        messages_taken=5,
        computed_at=datetime(2026, 5, 15, 6, 0, tzinfo=timezone.utc),
    )
    store.set(stats)
    fetched = store.get("2026-05-14")
    assert fetched is not None
    assert fetched.date == "2026-05-14"
    assert fetched.total_calls == 12
    assert fetched.transfers_completed == 3
    assert fetched.transfers_failed == 1
    assert fetched.messages_taken == 5
    assert fetched.computed_at == stats.computed_at


def test_set_overwrites_existing(store):
    first = DailyStats(
        date="2026-05-14",
        total_calls=1,
        computed_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
    )
    store.set(first)
    second = DailyStats(
        date="2026-05-14",
        total_calls=99,
        transfers_completed=7,
        computed_at=datetime(2026, 5, 15, 6, 0, tzinfo=timezone.utc),
    )
    store.set(second)
    fetched = store.get("2026-05-14")
    assert fetched is not None
    assert fetched.total_calls == 99
    assert fetched.transfers_completed == 7
