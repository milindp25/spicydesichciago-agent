"""Integration tests for /api/admin/stats/daily."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.call import Call, CallEvent, Outcome

OWNER_TOKEN = "Bearer fake:techtastellc@gmail.com"


@pytest.mark.asyncio
async def test_daily_returns_per_day_aggregates(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    now = datetime.now(timezone.utc)
    for i, sid in enumerate(["CA1", "CA2", "CA3"]):
        state.call_store.record_call_start(Call(
            call_sid=sid,
            started_at=now - timedelta(hours=i),
            caller_phone="+15551234567",
            from_number="+15559998888",
        ))
        # Mark CA1 as transferred, CA2 as messageTaken, CA3 leave inProgress
        if sid == "CA1":
            state.call_store.record_call_end(
                call_sid=sid,
                ended_at=now,
                outcome=Outcome.TRANSFERRED,
                duration_ms=60000,
            )
        if sid == "CA2":
            state.call_store.record_call_end(
                call_sid=sid,
                ended_at=now,
                outcome=Outcome.MESSAGE_TAKEN,
                duration_ms=80000,
            )

    resp = client.get(
        "/api/admin/stats/daily?days=1",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    today_key = body["days"][0]["date"]
    assert body["days"][0]["totalCalls"] == 3
    assert body["days"][0]["transfersCompleted"] == 1
    assert body["days"][0]["messagesTaken"] == 1


@pytest.mark.asyncio
async def test_daily_default_days_is_7(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    resp = client.get(
        "/api/admin/stats/daily",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    assert len(resp.json()["days"]) == 7


@pytest.mark.asyncio
async def test_daily_caps_days_at_30(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    resp = client.get(
        "/api/admin/stats/daily?days=100",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_daily_requires_auth(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    resp = client.get("/api/admin/stats/daily")
    assert resp.status_code == 401
