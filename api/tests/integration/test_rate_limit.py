"""Rate limiting smoke tests."""
from __future__ import annotations

import pytest


@pytest.fixture
def _strict_rate_limit(monkeypatch):
    """Lower the rate limit so the test isn't slow."""
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "5/minute")
    yield


def test_health_is_responsive_in_burst(client_factory, firestore_db):
    """healthz should respond consistently. slowapi default limit applies
    even here, but the default of 120/min in tests is far higher than the
    20-req burst we send, so all should pass."""
    client, _state = client_factory(firestore_db=firestore_db)
    for _ in range(20):
        resp = client.get("/healthz")
        assert resp.status_code == 200


def test_burst_above_default_returns_429(client_factory, firestore_db, _strict_rate_limit):
    """With RATE_LIMIT_DEFAULT=5/minute, the 6th+ request from the same
    test IP must 429."""
    client, _state = client_factory(firestore_db=firestore_db)
    seen_429 = False
    for _ in range(15):
        resp = client.get("/healthz")
        if resp.status_code == 429:
            seen_429 = True
            break
    assert seen_429, "expected 429 within 15 requests at 5/min limit"
