"""Integration tests for /api/admin/messages/* endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.message import Message, MessageStatus

OWNER_TOKEN = "Bearer fake:techtastellc@gmail.com"
STRANGER_TOKEN = "Bearer fake:stranger@example.com"


def _seed_message(state, *, call_sid="CA1", phone="+15551234567", reason="catering") -> str:
    msg = Message(
        call_sid=call_sid,
        caller_phone=phone,
        reason=reason,
        taken_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
    )
    return state.message_store.create(msg)


@pytest.mark.asyncio
async def test_unhandled_returns_messages_newest_first(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    older_id = _seed_message(state, call_sid="CA-old", reason="first")
    # later one — we artificially set takenAt via direct Firestore write
    state.message_store._db.collection("messages").document(older_id).update({
        "takenAt": datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    })
    newer_id = _seed_message(state, call_sid="CA-new", reason="second")
    state.message_store._db.collection("messages").document(newer_id).update({
        "takenAt": datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    })

    resp = client.get(
        "/api/admin/messages/unhandled",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    assert [m["reason"] for m in msgs] == ["second", "first"]
    assert msgs[0]["callerPhone"] == "+15551234567"
    assert msgs[0]["id"]  # id field present


@pytest.mark.asyncio
async def test_unhandled_requires_auth(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    resp = client.get("/api/admin/messages/unhandled")
    assert resp.status_code == 401

    resp = client.get(
        "/api/admin/messages/unhandled",
        headers={"Authorization": "Bearer garbage"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unhandled_rejects_non_allowlisted_email(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    resp = client.get(
        "/api/admin/messages/unhandled",
        headers={"Authorization": STRANGER_TOKEN},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_handle_marks_message_handled(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    msg_id = _seed_message(state)

    resp = client.post(
        f"/api/admin/messages/{msg_id}/handle",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["status"] == "handled"

    msg = state.message_store.get(msg_id)
    assert msg is not None
    assert msg.status == MessageStatus.HANDLED
    assert msg.handled_by == "uid-techtastellc"
    assert msg.handled_at is not None


@pytest.mark.asyncio
async def test_handle_404_on_missing_message(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    resp = client.post(
        "/api/admin/messages/does-not-exist/handle",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 404
