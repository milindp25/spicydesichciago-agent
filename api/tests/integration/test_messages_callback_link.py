from __future__ import annotations

import re
from collections.abc import Callable

from fastapi.testclient import TestClient
from google.cloud import firestore

from app.api.dependencies import AppState
from app.services.callback_tokens import decode as decode_token

SECRET = "callback-link-test-secret-32bytes!"


def test_owner_sms_includes_signed_callback_link_when_enabled(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, state = client_factory(
        firestore_db=firestore_db,
        callback_token_secret=SECRET,
        callback_public_url="https://api.spicydesichicago.com",
    )
    r = c.post(
        "/api/messages",
        headers=auth_headers,
        json={"call_sid": "CA1", "callback_number": "+13125551111", "reason": "catering"},
    )
    assert r.status_code == 202
    message_id = r.json()["message_id"]

    owner_msg = state.twilio.sms_calls[0]
    body = owner_msg["body"]
    assert "Tap to call back:" in body
    # Raw caller phone is NOT exposed on the "tel:" legacy line; but the caller phone
    # still appears earlier in the body (in parentheses), which is acceptable.
    assert "tel:" not in body
    # Extract the URL.
    m = re.search(r"https://api\.spicydesichicago\.com/api/callback/(\S+)", body)
    assert m, f"no callback url in {body!r}"
    token = m.group(1)
    decoded = decode_token(token, secret=SECRET)
    assert decoded["message_id"] == message_id
    assert decoded["caller_phone"] == "+13125551111"
    assert decoded["owner_phone"] == "+15555550199"


def test_owner_sms_falls_back_to_tel_link_when_secret_empty(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, state = client_factory(firestore_db=firestore_db, callback_token_secret="")
    r = c.post(
        "/api/messages",
        headers=auth_headers,
        json={"call_sid": "CA1", "callback_number": "+13125551111", "reason": "catering"},
    )
    assert r.status_code == 202
    owner_body = state.twilio.sms_calls[0]["body"]
    assert "tel:+13125551111" in owner_body
    assert "Tap to call back" not in owner_body
    assert "/api/callback/" not in owner_body
