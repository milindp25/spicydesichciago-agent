from collections.abc import Callable

from fastapi.testclient import TestClient

from app.api.dependencies import AppState


def test_returns_take_message_outside_hours(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory()
    r = c.post(
        "/api/transfers?now=2026-05-03T09:00:00Z",
        headers=auth_headers,
        json={"call_sid": "CA1", "reason": "owner please"},
    )
    assert r.status_code == 200
    assert r.json()["action"] == "take_message"


def test_returns_transfer_in_hours(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory()
    r = c.post(
        "/api/transfers?now=2026-01-05T20:00:00Z",
        headers=auth_headers,
        json={"call_sid": "CA1", "reason": "owner please"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "transfer"
    assert body["target"] == "+15555550199"
