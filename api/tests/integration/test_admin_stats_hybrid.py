"""Hybrid live + materialized tests for /api/admin/stats/daily."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.domain.call import Call, Outcome
from app.domain.daily_stats import DailyStats

OWNER_TOKEN = "Bearer fake:techtastellc@gmail.com"
CHICAGO = ZoneInfo("America/Chicago")


def _today_str() -> str:
    return datetime.now(CHICAGO).date().isoformat()


def _yesterday_str() -> str:
    return (datetime.now(CHICAGO).date() - timedelta(days=1)).isoformat()


@pytest.mark.asyncio
async def test_today_uses_live_when_no_materialized(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    now = datetime.now(timezone.utc)
    state.call_store.record_call_start(Call(
        call_sid="CA1",
        started_at=now,
        caller_phone="+15551234567",
        from_number="+15559998888",
    ))
    state.call_store.record_call_end(
        call_sid="CA1",
        ended_at=now,
        outcome=Outcome.TRANSFERRED,
        duration_ms=60_000,
    )

    resp = client.get(
        "/api/admin/stats/daily?days=1",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    day = resp.json()["days"][0]
    assert day["date"] == _today_str()
    assert day["source"] == "live"
    assert day["totalCalls"] == 1
    assert day["transfersCompleted"] == 1


@pytest.mark.asyncio
async def test_past_day_uses_materialized(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    y = _yesterday_str()
    state.daily_stats_store.set(DailyStats(
        date=y,
        total_calls=7,
        transfers_completed=4,
        transfers_failed=1,
        messages_taken=2,
        computed_at=datetime.now(timezone.utc),
    ))

    resp = client.get(
        "/api/admin/stats/daily?days=2",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    days = {d["date"]: d for d in resp.json()["days"]}
    assert days[y]["source"] == "materialized"
    assert days[y]["totalCalls"] == 7
    assert days[y]["transfersCompleted"] == 4
    assert days[y]["transfersFailed"] == 1
    assert days[y]["messagesTaken"] == 2


@pytest.mark.asyncio
async def test_mixed_materialized_and_live(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    y = _yesterday_str()
    state.daily_stats_store.set(DailyStats(
        date=y,
        total_calls=3,
        transfers_completed=1,
        computed_at=datetime.now(timezone.utc),
    ))
    # Today: seed one live call.
    now = datetime.now(timezone.utc)
    state.call_store.record_call_start(Call(
        call_sid="CA1",
        started_at=now,
        caller_phone="+15551234567",
        from_number="+15559998888",
    ))
    state.call_store.record_call_end(
        call_sid="CA1",
        ended_at=now,
        outcome=Outcome.MESSAGE_TAKEN,
        duration_ms=15_000,
    )

    resp = client.get(
        "/api/admin/stats/daily?days=2",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    days = {d["date"]: d for d in resp.json()["days"]}

    today = _today_str()
    assert days[today]["source"] == "live"
    assert days[today]["totalCalls"] == 1
    assert days[today]["messagesTaken"] == 1

    assert days[y]["source"] == "materialized"
    assert days[y]["totalCalls"] == 3
    assert days[y]["transfersCompleted"] == 1
