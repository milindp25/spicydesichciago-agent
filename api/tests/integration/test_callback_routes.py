from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from google.cloud import firestore

from app.api.dependencies import AppState
from app.services.callback_tokens import decode as decode_token
from app.services.callback_tokens import encode as encode_token

SECRET = "callback-test-secret-32-bytes-long"


def _payload() -> dict:
    return {
        "message_id": "msg-abc",
        "caller_phone": "+13125551111",
        "owner_phone": "+15555550199",
    }


def test_get_callback_view_renders_caller_phone(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    firestore_db: firestore.Client,
) -> None:
    c, _ = client_factory(
        firestore_db=firestore_db,
        callback_token_secret=SECRET,
        callback_public_url="https://api.test",
    )
    token = encode_token(_payload(), secret=SECRET, ttl_seconds=60)
    r = c.get(f"/api/callback/{token}")
    assert r.status_code == 200
    assert "+13125551111" in r.text
    assert f"/api/callback/{token}/start" in r.text
    assert r.headers["content-type"].startswith("text/html")


def test_get_callback_view_expired_returns_410(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    firestore_db: firestore.Client,
) -> None:
    c, _ = client_factory(
        firestore_db=firestore_db,
        callback_token_secret=SECRET,
        callback_public_url="https://api.test",
    )
    # Manually craft an expired token by encoding with ttl=-3600 (exp in past).
    token = encode_token(_payload(), secret=SECRET, ttl_seconds=-3600)
    r = c.get(f"/api/callback/{token}")
    assert r.status_code == 410
    assert "expired" in r.text.lower() or "link expired" in r.text.lower()


def test_get_callback_view_bad_signature_returns_410(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    firestore_db: firestore.Client,
) -> None:
    c, _ = client_factory(
        firestore_db=firestore_db,
        callback_token_secret=SECRET,
        callback_public_url="https://api.test",
    )
    token = encode_token(_payload(), secret="other-secret", ttl_seconds=60)
    r = c.get(f"/api/callback/{token}")
    assert r.status_code == 410


def test_post_start_creates_outbound_call(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    firestore_db: firestore.Client,
) -> None:
    c, state = client_factory(
        firestore_db=firestore_db,
        callback_token_secret=SECRET,
        callback_public_url="https://api.test",
    )
    token = encode_token(_payload(), secret=SECRET, ttl_seconds=60)
    r = c.post(f"/api/callback/{token}/start")
    assert r.status_code == 200
    assert "Calling you back" in r.text
    assert len(state.twilio.created_calls) == 1
    call = state.twilio.created_calls[0]
    assert call["to"] == "+15555550199"
    assert call["from_"] == "+15555550100"
    assert call["url"] == f"https://api.test/api/callback/{token}/twiml"


def test_post_twiml_dials_caller(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    firestore_db: firestore.Client,
) -> None:
    c, _ = client_factory(
        firestore_db=firestore_db,
        callback_token_secret=SECRET,
        callback_public_url="https://api.test",
    )
    token = encode_token(_payload(), secret=SECRET, ttl_seconds=60)
    r = c.post(f"/api/callback/{token}/twiml")
    assert r.status_code == 200
    assert "<Dial>" in r.text
    assert "+13125551111" in r.text
    assert r.headers["content-type"].startswith("application/xml")


def test_service_disabled_returns_503(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    firestore_db: firestore.Client,
) -> None:
    c, _ = client_factory(firestore_db=firestore_db, callback_token_secret="")
    # Use any string for token; should 503 before decode is reached.
    r = c.get("/api/callback/anything")
    assert r.status_code == 503
    r = c.post("/api/callback/anything/start")
    assert r.status_code == 503
    r = c.post("/api/callback/anything/twiml")
    assert r.status_code == 503


def test_decoded_token_roundtrip_sanity() -> None:
    tok = encode_token(_payload(), secret=SECRET, ttl_seconds=60)
    out = decode_token(tok, secret=SECRET)
    assert out["message_id"] == "msg-abc"
