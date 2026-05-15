"""Integration tests for /api/admin/calls/* endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.domain.call import Call, CallEvent

OWNER_TOKEN = "Bearer fake:techtastellc@gmail.com"


@pytest.mark.asyncio
async def test_today_returns_only_todays_calls(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)

    chi = ZoneInfo("America/Chicago")
    today_chi = datetime.now(chi).replace(hour=10, minute=0, second=0, microsecond=0)
    yesterday_chi = today_chi - timedelta(days=1)

    state.call_store.record_call_start(Call(
        call_sid="CA-yest",
        started_at=yesterday_chi,
        caller_phone="+15551110000",
        from_number="+15559998888",
    ))
    state.call_store.record_call_start(Call(
        call_sid="CA-today",
        started_at=today_chi,
        caller_phone="+15551234567",
        from_number="+15559998888",
    ))

    resp = client.get(
        "/api/admin/calls/today",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    sids = [c["callSid"] for c in body["calls"]]
    assert "CA-yest" not in sids
    assert "CA-today" in sids


@pytest.mark.asyncio
async def test_call_detail_returns_doc_plus_events(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    started_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    state.call_store.record_call_start(Call(
        call_sid="CA-detail",
        started_at=started_at,
        caller_phone="+15551234567",
        from_number="+15559998888",
    ))
    state.call_store.append_event(
        call_sid="CA-detail",
        event=CallEvent(
            ts=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
            kind="toolCalled",
            payload={"tool": "listMenuCategories"},
        ),
        caller_phone_for_upsert="+15551234567",
        from_number_for_upsert="+15559998888",
    )

    resp = client.get(
        "/api/admin/calls/CA-detail",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["call"]["callSid"] == "CA-detail"
    assert body["call"]["callerPhone"] == "+15551234567"
    assert len(body["events"]) == 1
    assert body["events"][0]["kind"] == "toolCalled"
    assert body["events"][0]["payload"] == {"tool": "listMenuCategories"}
    # ts serialized as ISO 8601
    assert isinstance(body["events"][0]["ts"], str)


@pytest.mark.asyncio
async def test_call_detail_404_on_missing(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    resp = client.get(
        "/api/admin/calls/does-not-exist",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_calls_routes_require_auth(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    assert client.get("/api/admin/calls/today").status_code == 401
    assert client.get("/api/admin/calls/CA1").status_code == 401
