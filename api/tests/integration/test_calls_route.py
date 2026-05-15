"""Integration tests for /api/calls/{sid}/{start,end,summary}."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.call import Outcome


@pytest.mark.asyncio
async def test_start_creates_call_doc(client_factory, firestore_db, secret):
    client, state = client_factory(firestore_db=firestore_db)
    started_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc).isoformat()

    resp = client.post(
        "/api/calls/CA-test-1/start",
        json={
            "started_at": started_at,
            "caller_phone": "+15551234567",
            "from_number": "+15559998888",
        },
        headers={"X-Tools-Auth": secret},
    )
    assert resp.status_code == 202
    assert resp.json() == {"ok": True}

    call = state.call_store.get_call("CA-test-1")
    assert call is not None
    assert call.caller_phone == "+15551234567"
    assert call.from_number == "+15559998888"
    assert call.outcome == Outcome.IN_PROGRESS


@pytest.mark.asyncio
async def test_end_sets_outcome_duration(client_factory, firestore_db, secret):
    client, state = client_factory(firestore_db=firestore_db)
    started = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=94)

    client.post(
        "/api/calls/CA-test-2/start",
        json={
            "started_at": started.isoformat(),
            "caller_phone": "+15551234567",
            "from_number": "+15559998888",
        },
        headers={"X-Tools-Auth": secret},
    )
    resp = client.post(
        "/api/calls/CA-test-2/end",
        json={
            "ended_at": ended.isoformat(),
            "outcome": "resolved",
            "duration_ms": 94000,
        },
        headers={"X-Tools-Auth": secret},
    )
    assert resp.status_code == 202
    call = state.call_store.get_call("CA-test-2")
    assert call is not None
    assert call.outcome == Outcome.RESOLVED
    assert call.duration_ms == 94000


@pytest.mark.asyncio
async def test_summary_sets_summary(client_factory, firestore_db, secret):
    client, state = client_factory(firestore_db=firestore_db)
    started = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    client.post(
        "/api/calls/CA-test-3/start",
        json={
            "started_at": started.isoformat(),
            "caller_phone": "+15551234567",
            "from_number": "+15559998888",
        },
        headers={"X-Tools-Auth": secret},
    )
    resp = client.post(
        "/api/calls/CA-test-3/summary",
        json={"summary": "Asked about hours and momos; sent order link"},
        headers={"X-Tools-Auth": secret},
    )
    assert resp.status_code == 202
    call = state.call_store.get_call("CA-test-3")
    assert call is not None
    assert call.summary == "Asked about hours and momos; sent order link"


@pytest.mark.asyncio
async def test_end_without_start_creates_call_via_upsert(
    client_factory, firestore_db, secret,
):
    """If hangup arrives without prior start (network blip), don't 404 —
    create the parent doc with the supplied end-time data and mark the
    call's startedAt = endedAt as a best effort."""
    client, state = client_factory(firestore_db=firestore_db)
    ended = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)

    resp = client.post(
        "/api/calls/CA-orphan/end",
        json={
            "ended_at": ended.isoformat(),
            "outcome": "failed",
            "duration_ms": 0,
            "caller_phone": "+15551234567",
            "from_number": "+15559998888",
        },
        headers={"X-Tools-Auth": secret},
    )
    assert resp.status_code == 202
    call = state.call_store.get_call("CA-orphan")
    assert call is not None
    assert call.outcome == Outcome.FAILED
