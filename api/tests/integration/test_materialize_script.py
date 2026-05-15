"""Tests for the materialize_daily_stats CLI entrypoint."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.domain.call import Call, Outcome
from app.infrastructure.firestore_call_store import FirestoreCallStore
from app.infrastructure.firestore_daily_stats_store import FirestoreDailyStatsStore
from app.services.daily_stats_materializer import DailyStatsMaterializer
from scripts import materialize_daily_stats

CHICAGO = ZoneInfo("America/Chicago")


def test_main_with_date_writes_doc_and_exits_zero(firestore_db, capsys):
    call_store = FirestoreCallStore(client=firestore_db)
    stats_store = FirestoreDailyStatsStore(client=firestore_db)
    materializer = DailyStatsMaterializer(
        call_store=call_store, stats_store=stats_store
    )

    date_str = "2026-05-14"
    noon_utc = datetime(2026, 5, 14, 12, 0, tzinfo=CHICAGO).astimezone(timezone.utc)
    call_store.record_call_start(Call(
        call_sid="CA1",
        started_at=noon_utc,
        caller_phone="+15551234567",
        from_number="+15559998888",
    ))
    call_store.record_call_end(
        call_sid="CA1",
        ended_at=noon_utc,
        outcome=Outcome.TRANSFERRED,
        duration_ms=10_000,
    )

    rc = materialize_daily_stats.main(
        ["--date", date_str], materializer=materializer
    )
    assert rc == 0

    persisted = stats_store.get(date_str)
    assert persisted is not None
    assert persisted.total_calls == 1
    assert persisted.transfers_completed == 1

    out = capsys.readouterr().out.strip()
    assert date_str in out
    assert "totalCalls" in out


def test_main_yesterday_writes_yesterday(firestore_db):
    call_store = FirestoreCallStore(client=firestore_db)
    stats_store = FirestoreDailyStatsStore(client=firestore_db)
    materializer = DailyStatsMaterializer(
        call_store=call_store, stats_store=stats_store
    )
    rc = materialize_daily_stats.main(
        ["--yesterday"], materializer=materializer
    )
    assert rc == 0
    from datetime import timedelta
    y = (datetime.now(CHICAGO).date() - timedelta(days=1)).isoformat()
    assert stats_store.get(y) is not None


def test_main_days_writes_multiple(firestore_db, capsys):
    call_store = FirestoreCallStore(client=firestore_db)
    stats_store = FirestoreDailyStatsStore(client=firestore_db)
    materializer = DailyStatsMaterializer(
        call_store=call_store, stats_store=stats_store
    )
    rc = materialize_daily_stats.main(
        ["--days", "3"], materializer=materializer
    )
    assert rc == 0
    out_lines = [
        line for line in capsys.readouterr().out.strip().splitlines() if line
    ]
    assert len(out_lines) == 3
