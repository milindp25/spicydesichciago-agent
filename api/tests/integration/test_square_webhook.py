import base64
import hashlib
import hmac
import json
from collections.abc import Callable

from fastapi.testclient import TestClient

from app.api.dependencies import AppState


def test_rejects_bad_signature(
    client_factory: Callable[..., tuple[TestClient, AppState]],
) -> None:
    c, _ = client_factory()
    r = c.post(
        "/api/webhooks/square",
        headers={
            "X-Square-Hmacsha256-Signature": "bad",
            "Content-Type": "application/json",
        },
        content=json.dumps({"type": "catalog.version.updated"}),
    )
    assert r.status_code == 401


def test_invalidates_on_valid_signature(
    client_factory: Callable[..., tuple[TestClient, AppState]],
) -> None:
    c, state = client_factory()
    body = json.dumps({"type": "catalog.version.updated"})
    sig = base64.b64encode(
        hmac.new(
            state.square_webhook_signature_key.encode(),
            (state.square_webhook_url + body).encode(),
            hashlib.sha256,
        ).digest()
    ).decode()
    r = c.post(
        "/api/webhooks/square",
        headers={
            "X-Square-Hmacsha256-Signature": sig,
            "Content-Type": "application/json",
        },
        content=body,
    )
    assert r.status_code == 200
