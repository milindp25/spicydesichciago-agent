"""Integration tests for POST /api/calls/{sid}/transcript and
GET /api/admin/calls/{sid}/transcript."""
from __future__ import annotations

import pytest

OWNER_TOKEN = "Bearer fake:techtastellc@gmail.com"


@pytest.mark.asyncio
async def test_post_transcript_stores_turns(client_factory, firestore_db, secret):
    client, state = client_factory(firestore_db=firestore_db)
    resp = client.post(
        "/api/calls/CA-tx-1/transcript",
        json={
            "turns": [
                {"role": "caller", "text": "what time do you open?"},
                {"role": "agent", "text": "we open at 11am"},
            ]
        },
        headers={"X-Tools-Auth": secret},
    )
    assert resp.status_code == 202
    assert resp.json() == {"ok": True, "turn_count": 2}

    stored = state.transcript_store.get("CA-tx-1")
    assert stored is not None
    assert len(stored.turns) == 2
    assert stored.turns[0].role == "caller"


@pytest.mark.asyncio
async def test_post_transcript_rejects_empty_body(client_factory, firestore_db, secret):
    client, _ = client_factory(firestore_db=firestore_db)
    resp = client.post(
        "/api/calls/CA-tx-2/transcript",
        json={"turns": []},
        headers={"X-Tools-Auth": secret},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_transcript_rejects_bad_role(client_factory, firestore_db, secret):
    client, _ = client_factory(firestore_db=firestore_db)
    resp = client.post(
        "/api/calls/CA-tx-3/transcript",
        json={"turns": [{"role": "system", "text": "hi"}]},
        headers={"X-Tools-Auth": secret},
    )
    # Pydantic Literal validation -> request validation error
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_post_transcript_rejects_too_many_turns(client_factory, firestore_db, secret):
    client, _ = client_factory(firestore_db=firestore_db)
    turns = [{"role": "caller", "text": f"hi {i}"} for i in range(201)]
    resp = client.post(
        "/api/calls/CA-tx-4/transcript",
        json={"turns": turns},
        headers={"X-Tools-Auth": secret},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_transcript_rejects_empty_text(client_factory, firestore_db, secret):
    client, _ = client_factory(firestore_db=firestore_db)
    resp = client.post(
        "/api/calls/CA-tx-5/transcript",
        json={"turns": [{"role": "caller", "text": "   "}]},
        headers={"X-Tools-Auth": secret},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_transcript_rejects_long_text(client_factory, firestore_db, secret):
    client, _ = client_factory(firestore_db=firestore_db)
    resp = client.post(
        "/api/calls/CA-tx-6/transcript",
        json={"turns": [{"role": "caller", "text": "x" * 1001}]},
        headers={"X-Tools-Auth": secret},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_transcript_requires_auth(client_factory, firestore_db):
    client, _ = client_factory(firestore_db=firestore_db)
    resp = client.post(
        "/api/calls/CA-tx-7/transcript",
        json={"turns": [{"role": "caller", "text": "hi"}]},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_transcript_is_idempotent(client_factory, firestore_db, secret):
    client, state = client_factory(firestore_db=firestore_db)
    for body in (
        {"turns": [{"role": "caller", "text": "first"}]},
        {"turns": [{"role": "caller", "text": "second"}, {"role": "agent", "text": "ok"}]},
    ):
        client.post(
            "/api/calls/CA-tx-8/transcript",
            json=body,
            headers={"X-Tools-Auth": secret},
        )
    stored = state.transcript_store.get("CA-tx-8")
    assert stored is not None
    assert len(stored.turns) == 2
    assert stored.turns[0].text == "second"


@pytest.mark.asyncio
async def test_admin_get_transcript_returns_stored(client_factory, firestore_db, secret):
    client, _ = client_factory(firestore_db=firestore_db)
    client.post(
        "/api/calls/CA-tx-9/transcript",
        json={
            "turns": [
                {"role": "caller", "text": "hi"},
                {"role": "agent", "text": "hello"},
            ]
        },
        headers={"X-Tools-Auth": secret},
    )
    resp = client.get(
        "/api/admin/calls/CA-tx-9/transcript",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["callSid"] == "CA-tx-9"
    assert len(body["turns"]) == 2
    assert body["turns"][0] == {"role": "caller", "text": "hi"}
    assert isinstance(body["storedAt"], str)


@pytest.mark.asyncio
async def test_admin_get_transcript_404_when_missing(client_factory, firestore_db):
    client, _ = client_factory(firestore_db=firestore_db)
    resp = client.get(
        "/api/admin/calls/CA-missing/transcript",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_get_transcript_requires_auth(client_factory, firestore_db):
    client, _ = client_factory(firestore_db=firestore_db)
    resp = client.get("/api/admin/calls/CA-x/transcript")
    assert resp.status_code == 401
