"""Integration tests for DailyStatsMaterializer."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.domain.call import Call, Outcome
from app.infrastructure.firestore_call_store import FirestoreCallStore
from app.infrastructure.firestore_daily_stats_store import FirestoreDailyStatsStore
from app.services.daily_stats_materializer import (
    DailyStatsMaterializer,
    chicago_day_window_utc,
)

CHICAGO = ZoneInfo("America/Chicago")


def test_chicago_day_window_round_trips_to_utc():
    start, end = chicago_day_window_utc("2026-05-14")
    # 24-hour window
    assert (end - start).total_seconds() == 24 * 3600
    # Both timestamps are UTC
    assert start.tzinfo is not None
    assert end.tzinfo is not None


def test_materialize_writes_aggregated_counts(firestore_db):
    call_store = FirestoreCallStore(client=firestore_db)
    stats_store = FirestoreDailyStatsStore(client=firestore_db)
    materializer = DailyStatsMaterializer(
        call_store=call_store, stats_store=stats_store
    )

    # Pick a target Chicago date and seed calls inside it.
    date_str = "2026-05-14"
    # Noon Chicago = guaranteed inside the day window.
    noon_chi = datetime(2026, 5, 14, 12, 0, tzinfo=CHICAGO)
    noon_utc = noon_chi.astimezone(timezone.utc)

    def seed(sid: str, outcome: Outcome) -> None:
        call_store.record_call_start(Call(
            call_sid=sid,
            started_at=noon_utc,
            caller_phone="+15551234567",
            from_number="+15559998888",
        ))
        if outcome != Outcome.IN_PROGRESS:
            call_store.record_call_end(
                call_sid=sid,
                ended_at=noon_utc,
                outcome=outcome,
                duration_ms=10_000,
            )

    seed("CA1", Outcome.TRANSFERRED)
    seed("CA2", Outcome.TRANSFERRED)
    seed("CA3", Outcome.FAILED)
    seed("CA4", Outcome.MESSAGE_TAKEN)
    seed("CA5", Outcome.IN_PROGRESS)

    # And a call outside the window — should not be counted.
    other_day = datetime(2026, 5, 13, 12, 0, tzinfo=CHICAGO).astimezone(timezone.utc)
    call_store.record_call_start(Call(
        call_sid="OUT",
        started_at=other_day,
        caller_phone="+15551234567",
        from_number="+15559998888",
    ))

    stats = materializer.materialize(date_str)
    assert stats.total_calls == 5
    assert stats.transfers_completed == 2
    assert stats.transfers_failed == 1
    assert stats.messages_taken == 1

    # Persisted under the date key.
    persisted = stats_store.get(date_str)
    assert persisted is not None
    assert persisted.total_calls == 5
    assert persisted.transfers_completed == 2


def test_materialize_idempotent_rewrites(firestore_db):
    call_store = FirestoreCallStore(client=firestore_db)
    stats_store = FirestoreDailyStatsStore(client=firestore_db)
    materializer = DailyStatsMaterializer(
        call_store=call_store, stats_store=stats_store
    )

    # Run twice with no calls — second run shouldn't error and should overwrite.
    s1 = materializer.materialize("2026-05-14")
    s2 = materializer.materialize("2026-05-14")
    assert s1.total_calls == 0
    assert s2.total_calls == 0
