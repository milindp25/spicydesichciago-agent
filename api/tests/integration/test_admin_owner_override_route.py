"""Integration tests for /api/admin/owner-override."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

OWNER_TOKEN = "Bearer fake:techtastellc@gmail.com"


@pytest.mark.asyncio
async def test_get_when_unset_returns_inactive(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    resp = client.get(
        "/api/admin/owner-override",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is False
    assert body["untilIso"] is None


@pytest.mark.asyncio
async def test_post_sets_override(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    until = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    resp = client.post(
        "/api/admin/owner-override",
        headers={"Authorization": OWNER_TOKEN},
        json={"until_iso": until, "reason": "wedding"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is True
    assert body["untilIso"] == until
    assert body["reason"] == "wedding"
    assert body["setBy"] == "uid-techtastellc"


@pytest.mark.asyncio
async def test_delete_clears_override(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    until = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    client.post(
        "/api/admin/owner-override",
        headers={"Authorization": OWNER_TOKEN},
        json={"until_iso": until, "reason": "wedding"},
    )

    resp = client.delete(
        "/api/admin/owner-override",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is False
    assert body["untilIso"] is None


@pytest.mark.asyncio
async def test_post_rejects_past_until(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    resp = client.post(
        "/api/admin/owner-override",
        headers={"Authorization": OWNER_TOKEN},
        json={"until_iso": past, "reason": "test"},
    )
    assert resp.status_code == 400
    assert "past" in resp.json()["detail"].lower() or "future" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_routes_require_auth(client_factory, firestore_db):
    client, state = client_factory(firestore_db=firestore_db)
    resp = client.get("/api/admin/owner-override")
    assert resp.status_code == 401
    resp = client.post("/api/admin/owner-override", json={"until_iso": "x", "reason": "y"})
    assert resp.status_code == 401
    resp = client.delete("/api/admin/owner-override")
    assert resp.status_code == 401
