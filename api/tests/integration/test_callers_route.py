from collections.abc import Callable

from fastapi.testclient import TestClient

from app.api.dependencies import AppState


def test_caller_history_returns_returning_flag(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _state = client_factory()
    # Plant a prior message from this caller.
    c.post(
        "/api/messages",
        headers=auth_headers,
        json={"call_sid": "CA1", "callback_number": "+13125551111", "reason": "catering"},
    )
    r = c.get(
        "/api/callers/history?phone=%2B13125551111",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_returning"] is True
    assert body["call_count"] >= 1
    assert any("catering" in (e["summary"] or "") for e in body["events"])


def test_caller_history_unknown_caller_is_empty(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory()
    r = c.get(
        "/api/callers/history?phone=%2B19999999999",
        headers=auth_headers,
    )
    body = r.json()
    assert body["is_returning"] is False
    assert body["events"] == []
